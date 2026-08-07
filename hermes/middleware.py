import logging
import datetime
import time

from influxdb import InfluxDBClient

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.contrib.auth import logout
from django.http import HttpResponse

try:
    import gevent
    from gevent.pool import Pool as GeventPool
except ImportError:
    gevent = None
    GeventPool = None

logger = logging.getLogger(__name__)


class SCiMMAAuthSessionRefresh:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.
        logger.debug(f'Checking Keycloak login OIDC token expiration...')

        # Check the oidc token expiration - if expired, return a HTTP 401 to indicate client should logout
        oidc_expiration_seconds = request.session.get('oidc_id_token_expiration')
        if oidc_expiration_seconds:
            if datetime.datetime.utcnow() > datetime.datetime.fromtimestamp(float(oidc_expiration_seconds)):
                logger.debug(f"OIDC login has expired for user {request.user}, forcing logout and returning 401")
                logout(request)
                return HttpResponse('Unauthorized', status=401)

        response = self.get_response(request)  # pass the request to the next Middleware in the list

        # Code to be executed for each request/response after
        # the view is called.
        return response


class InfluxDBRequestLogger:
    """Middleware that logs a metric for every request to an InfluxDB v1 database.

    Each request is recorded as a single point with the endpoint, authenticated
    user (if any), status code, response size and latency. Writes are dispatched to
    a bounded pool of background gevent greenlets; once the pool is
    saturated further metrics are dropped and a warning is logged.

    """

    # Throttle the "write pool saturated" warning to at most once per this many seconds.
    _DROP_LOG_INTERVAL_SECONDS = 60

    def __init__(self, get_response):
        self.get_response = get_response

        if not settings.INFLUXDB_ENABLED:
            # Tell Django to drop this middleware entirely so it adds zero overhead.
            raise MiddlewareNotUsed()

        self.measurement = settings.INFLUXDB_MEASUREMENT
        self._client = self._build_client()
        if settings.INFLUXDB_ASYNCHRONOUS_MODE and gevent is not None:
            self._write_pool = GeventPool(settings.INFLUXDB_MAX_CONCURRENT_WRITES)
        else:
            self._write_pool = None
        self._dropped_writes = 0
        self._last_drop_log = 0.0

    def _build_client(self):
        """Construct the InfluxDB v1 client, or return None if it cannot be built."""
        # The connection uses mTLS: the client cert/key authenticate us to the InfluxDB
        # gateway. The gateway serves a publicly-trusted (AWS ACM) cert, so the server is
        # verified against the system CA bundle (verify_ssl=True below).
        cert_path = settings.INFLUXDB_CLIENT_CERT
        key_path = settings.INFLUXDB_CLIENT_KEY
        if not (cert_path and key_path):
            logger.warning(
                'InfluxDB mTLS client cert/key not configured '
                '(INFLUXDB_CLIENT_CERT / INFLUXDB_CLIENT_KEY); '
                'request metrics will not be logged.'
            )
            return None

        try:
            return InfluxDBClient(
                host=settings.INFLUXDB_HOST,
                port=settings.INFLUXDB_PORT,
                username=settings.INFLUXDB_USERNAME or None,
                password=settings.INFLUXDB_PASSWORD or None,
                database=settings.INFLUXDB_DATABASE,
                ssl=True,
                verify_ssl=True,
                cert=(cert_path, key_path),
                timeout=settings.INFLUXDB_TIMEOUT,
                pool_size=settings.INFLUXDB_MAX_CONCURRENT_WRITES,
            )
        except Exception:
            logger.exception('Failed to construct InfluxDB client; request metrics will not be logged.')
            return None

    def __call__(self, request):
        start = time.monotonic()
        request_time = datetime.datetime.now(datetime.timezone.utc)

        response = self.get_response(request)

        if self._client is not None:
            latency_ms = (time.monotonic() - start) * 1000.0
            try:
                point = self._build_point(request, response, request_time, latency_ms)
                self._dispatch_write(point)
            except Exception:
                logger.exception('Failed to log request metric to InfluxDB.')

        return response

    def _build_point(self, request, response, request_time, latency_ms):
        # Use the resolved URL route (e.g. "api/v0/messages/<pk>/") rather than the raw
        # path so tag cardinality stays bounded by the number of routes rather than by
        # every distinct path-parameter value.
        resolver_match = getattr(request, 'resolver_match', None)
        if resolver_match is not None and resolver_match.route:
            endpoint = resolver_match.route
        else:
            endpoint = '<unresolved>'

        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            username = user.get_username()
        else:
            username = 'anonymous'

        content_length = response.get('Content-Length')
        if content_length is not None:
            response_size = int(content_length)
        elif getattr(response, 'streaming', False):
            response_size = -1  # size is unknown for streaming responses
        else:
            response_size = len(response.content)

        return {
            'measurement': self.measurement,
            'time': request_time,
            'tags': {
                'endpoint': endpoint,
                'method': request.method,
                'status_code': response.status_code,
                'user': username,
                'authenticated': username != 'anonymous',
            },
            'fields': {
                'path': request.get_full_path(),
                'client_ip': self._client_ip(request),
                'response_size': response_size,
                'latency_ms': round(latency_ms, 3),
                'count': 1,
            },
        }

    @staticmethod
    def _client_ip(request):
        # the real client is the leftmost X-Forwarded-For entry
        # REMOTE_ADDR is the fallback for dev. The leftmost x-forwarded-for is
        # client-supplied and therefore spoofable, which is acceptable for observability.
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')

    def _dispatch_write(self, point):
        # Without gevent (dev/tests) write inline.
        if self._write_pool is None:
            self._write_point(point)
            return

        # if nothing is free in the pool, log and drop the write request
        if self._write_pool.free_count() <= 0:
            self._log_dropped_write()
        else:
            self._write_pool.spawn(self._write_point, point)

    def _log_dropped_write(self):
        self._dropped_writes += 1
        now = time.monotonic()
        if now - self._last_drop_log >= self._DROP_LOG_INTERVAL_SECONDS:
            logger.warning(
                'InfluxDB write pool saturated; dropped %d request metric(s) so far '
                '(is InfluxDB slow or unreachable?).', self._dropped_writes
            )
            self._last_drop_log = now

    def _write_point(self, point):
        try:
            self._client.write_points([point])
        except Exception:
            logger.exception('Failed to write request metric to InfluxDB.')
