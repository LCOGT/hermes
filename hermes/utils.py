from django.core.cache import cache
from django.http import QueryDict
from rest_framework import parsers
from rest_framework.exceptions import APIException
from hermes.models import Message
import json
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import bson
import uuid
import requests
from urllib.parse import urljoin
from django.conf import settings
import threading
import base64
import re
from scramp import ScramClient
import secrets
import logging


# Set some logger
logger = logging.getLogger(__name__)


TARGET_ORDER = [
    'name',
    'ra',
    'dec',
    'pm_ra',
    'pm_dec',
    'epoch',
    'new_discovery',
    'redshift',
    'host_name',
    'host_redshift'
]

ASTROMETRY_ORDER = [
    'target_name',
    'date_obs',
    'ra',
    'ra_error',
    'dec',
    'dec_error',
    'telescope',
    'instrument'
]

PHOTOMETRY_ORDER = [
    'target_name',
    'date_obs',
    'brightness',
    'brightness_error',
    'limiting_brightness',
    'limiting_brightness_error',
    'bandpass',
    'telescope',
    'instrument'
]

REFERENCES_ORDER = [
    'source',
    'citation',
    'url'
]

def get_all_public_topics():
    all_topics = cache.get("all_public_topics", None)
    if not all_topics:
        all_topics = sorted(list(Message.objects.order_by().values_list('topic', flat=True).distinct()))
        cache.set("all_public_topics", all_topics, 3600)
    return all_topics


def convert_list_to_markdown_table(name, data, key_ordering):
    output = f'# {name}\n'

    # Only add keys present in the ordering into the markdown table so it is manageable
    keys_present = {key for datum in data for key in datum.keys() if key in key_ordering}
    ordered_keys = sorted(keys_present, key=key_ordering.index)

    # Calculate the max character length (min 3) for each key to pad whitespace to that value
    whitespace = defaultdict(lambda: 3)
    for key in keys_present:
        whitespace[key] = max(len(str(key)), whitespace[key])
        for datum in data:
            whitespace[key] = max(len(str(datum.get(key, ''))), whitespace[key])

    # Add the header line for the markdown table
    output += f"| {' | '.join([key.ljust(whitespace[key]) for key in ordered_keys])} |\n"

    # Add the mardown dashed line row below the header
    output += f"| {' | '.join(['---'.ljust(whitespace[key], '-') for key in ordered_keys])} |\n"

    # Now add the table values for each row
    for datum in data:
        output += '|'
        for key in ordered_keys:
            output += f" {str(datum.get(key, '')).ljust(whitespace[key])} |"
        output += '\n'

    return output


def convert_to_plaintext(message):
    # TODO: Incorporate the message uuid into here somewhere
    authors = message.get('authors')
    pluralized_reports = 'reports'
    if ' and ' in authors or ',' in authors:
        pluralized_reports = 'report'
    formatted_message = """{authors} {reports}:\n\n{message}\n\n""".format(
        authors=message.get('authors'),
        reports=pluralized_reports,
        message=message.get('message_text')
    )
    if len(message['data'].get('targets', [])) > 0:
        formatted_message += convert_list_to_markdown_table(
            name='Targets', data=message['data']['targets'],
            key_ordering=TARGET_ORDER
        )
        formatted_message += '\n'
    if len(message['data'].get('photometry', [])) > 0:
        formatted_message += convert_list_to_markdown_table(
            name='Photometry', data=message['data']['photometry'],
            key_ordering=PHOTOMETRY_ORDER
        )
        formatted_message += '\n'
    if len(message['data'].get('astrometry', [])) > 0:
        formatted_message += convert_list_to_markdown_table(
            name='Astrometry', data=message['data']['astrometry'],
            key_ordering=ASTROMETRY_ORDER
        )
        formatted_message += '\n'
    if len(message['data'].get('references', [])) > 0:
        formatted_message += convert_list_to_markdown_table(
            name='References', data=message['data']['references'],
            key_ordering=REFERENCES_ORDER
        )
        formatted_message += '\n'

    return formatted_message


def send_email(recipient_email, sender_email, sender_password,
               email_title, email_body, smtp_url='smtp.gmail.com:587'):
    """
    Send the email via smtp
    
    Parameters
    ----------
    recipient_email : String
                      Email address of the recipients
    sender_email : str
                   Email address of the sender (must be a Google account)
    sender_password : str
                   Password for the sender email account
    email_body : str
                 Body of the email
    smtp_url : str
            URL of the smtp server to send the email
    """

    # Create the container (outer) email message.
    msg = MIMEMultipart()
    msg['Subject'] = email_title
    msg['From'] = sender_email
    msg['To'] = recipient_email

    msg.attach(MIMEText(email_body, 'html'))

    # Send the email via our the localhost SMTP server.
    server = smtplib.SMTP(smtp_url)
    server.ehlo()
    server.starttls()
    server.login(sender_email, sender_password)
    server.sendmail(sender_email, recipient_email, msg.as_string())
    server.quit()


def upload_file_to_hop(file, topic, auth):
    """ Takes a Django InMemoryUploadedFile object and uploads it to the hop archive as a public file.
        Returns the download link to that uploaded file if it was uploaded successfully.
    """
    # First generate a uuid for it
    id = uuid.uuid4()
    # Seek to begining of file in case we already read to the end to send to TNS
    file.file.seek(0)
    data = bson.dumps({'message': file.file.read(), 'headers': {'format': b"blob", "_id": id.bytes}})
    upload_url = urljoin(settings.SCIMMA_ARCHIVE_BASE_URL, f'topic/{topic}')
    try:
        response = requests.post(upload_url, data=data, auth=SCRAMAuth(auth, shortcut=True))
        response.raise_for_status()
    except Exception as ex:
        logger.error(f"Error uploading file {file.name} to the SCIMMA Archiv: {repr(ex)}")
        raise APIException(ex)
    download_url = urljoin(settings.SCIMMA_ARCHIVE_BASE_URL, f'msg/{id}/raw_file/{file.name}')
    return download_url


class MultipartJsonFileParser(parsers.MultiPartParser):
    """ This Request parser is used for multipart/form-data that contains both files and json encoded data
        A list of files is expected to be sent in the 'files' key,
        and a json encoded data blob is expected in the 'data' key.
    """

    def parse(self, stream, media_type=None, parser_context=None):
        result = super().parse(
            stream,
            media_type=media_type,
            parser_context=parser_context
        )
        data = json.loads(result.data['data'])
        query_dict = QueryDict('', mutable=True)
        query_dict.update(data)
        return parsers.DataAndFiles(query_dict, result.files)


class SCRAMAuth(requests.auth.AuthBase):
    """ SCRAMAuth class to use with requests library, provided by Chris Weaver of SCIMMA
    """
    def __init__(self, credential, shortcut: bool = False, check_final=True):
        self._thread_local = threading.local()
        # these are immutable, so we do not bother making them thread-local
        self.username = credential.username
        self.password = credential.password
        self.mechanism = credential.mechanism.upper()
        self.shortcut = shortcut
        self.check_final = check_final

    def init_per_thread_state(self):
        if not hasattr(self._thread_local, "init"):
            self._thread_local.init = True
            self._thread_local.num_calls = 0
            self._thread_local.saved_body = None

    def _redo_request(self, r: requests.Response, auth_header: str, final: bool = False, **kwargs):
        # Consume content and release the original connection
        # to allow our new request to reuse the same one.
        r.content
        r.close()
        prep = r.request.copy()
        requests.cookies.extract_cookies_to_jar(prep._cookies, r.request, r.raw)
        prep.prepare_cookies(prep._cookies)
        if final and self.shortcut and self._thread_local.saved_body is not None:
            prep.prepare_body(self._thread_local.saved_body, None)

        prep.headers['Authorization'] = auth_header
        prep.register_hook("response", self.process)
        _r = r.connection.send(prep, **kwargs)
        _r.history.append(r)
        _r.request = prep
        return _r

    def _generate_client_first(self):
        """Perform the client-side preparation for the first round of the SCRAM exchange.
            Returns: The encoded data for the Authorization header
        """
        self._thread_local.nonce = secrets.token_urlsafe()
        self._thread_local.sclient = ScramClient([self.mechanism],
                                                 self.username, self.password,
                                                 c_nonce=self._thread_local.nonce)
        cfirst = self._thread_local.sclient.get_client_first()
        logger.debug(f" client first: {cfirst}")
        cfirst = cfirst.encode("utf-8")
        return f"{self.mechanism} data={base64.b64encode(cfirst).decode('utf-8')}"

    def _handle_first(self, r: requests.Response, **kwargs):
        # Need to examine which auth mechanisms the server declares it accepts to find out
        # if the one we can do is on the list
        mechanisms = requests.utils.parse_list_header(r.headers.get("www-authenticate", ""))
        matching_mech = False
        for mechanism in mechanisms:
            if mechanism.upper() == self.mechanism or \
                    mechanism.upper().startswith(self.mechanism + " "):
                matching_mech = True
                break
        if not matching_mech:
            self._thread_local.num_calls = 0
            return r
        # At this point we know our mechanism is allowed, so we begin the SCRAM exchange

        self._thread_local.num_calls = 1
        return self._redo_request(r, auth_header=self._generate_client_first(), **kwargs)

    def _handle_final(self, r: requests.Response, **kwargs):
        # To contiue the handshake, the server should have set the www-authenticate header to
        # the mechanism we are using, followed by the data we need to use.
        # Check for this, and isolate the data to parse.
        logger.debug(f"Authenticate header sent by server: {r.headers.get('www-authenticate')}")
        m = re.fullmatch(f"{self.mechanism} (.+)", r.headers.get("www-authenticate"),
                         flags=re.IGNORECASE)
        if not m:
            print("No matching auth header")
            self._thread_local.num_calls = 0
            return r
        auth_data = requests.utils.parse_dict_header(m.group(1))
        # Next, make sure that both of the fields we need were actually sent in the dictionary
        if auth_data.get("sid", None) is None:
            self._thread_local.num_calls = 0
            return r
            raise RuntimeError("Missing sid in SCRAM server first: " + m.group(1))
        if auth_data.get("data", None) is None:
            self._thread_local.num_calls = 0
            return r
            raise RuntimeError("Missing data in SCRAM server first: " + m.group(1))

        self._thread_local.sid = auth_data.get("sid")
        sfirst = auth_data.get("data")
        logger.debug(f" sid: {self._thread_local.sid}")
        sfirst = base64.b64decode(sfirst).decode("utf-8")
        logger.debug(f" server first: {sfirst}")
        self._thread_local.sclient.set_server_first(sfirst)
        cfinal = self._thread_local.sclient.get_client_final()
        logger.debug(f" client final: {cfinal}")
        cfinal = base64.b64encode(cfinal.encode("utf-8")).decode('utf-8')
        self._thread_local.num_calls = 2
        return self._redo_request(r, auth_header=f"{self.mechanism} "
                                  f"sid={self._thread_local.sid},data={cfinal}", final=True)

    def _check_server_final(self, r: requests.Response, **kwargs):
        # The standard says that we MUST authenticate the server by checking the
        # ServerSignature, and treat it as an error if they do not match.
        logger.debug(f" authentication-info: {r.headers.get('authentication-info', None)}")
        raw_auth_data = r.headers.get("authentication-info", "")
        auth_data = requests.utils.parse_dict_header(raw_auth_data)
        # Next, make sure that both of the fields we need were actually sent in the dictionary
        if auth_data.get("sid", None) is None:
            self._thread_local.num_calls = 0
            raise RuntimeError("Missing sid in SCRAM server final: " + raw_auth_data)
        if auth_data.get("data", None) is None:
            self._thread_local.num_calls = 0
            raise RuntimeError("Missing data in SCRAM server final: " + raw_auth_data)
        if auth_data.get("sid") != self._thread_local.sid:
            self._thread_local.num_calls = 0
            raise RuntimeError("sid mismatch in server final www-authenticate header")
        sfinal = auth_data.get("data")
        self._thread_local.sclient.set_server_final(base64.b64decode(sfinal).decode("utf-8"))

    def process(self, r: requests.Response, **kwargs):
        if self._thread_local.num_calls < 2 and "www-authenticate" not in r.headers:
            self._thread_local.num_calls = 0
            return r
        if self._thread_local.num_calls >= 2:
            self._check_server_final(r)
            # prevent infinite looping if something goes wrong
            r.request.deregister_hook("response", self.process)

        if r.status_code == 401:
            if self._thread_local.num_calls == 0:
                return self._handle_first(r, **kwargs)
            elif self._thread_local.num_calls == 1:
                return self._handle_final(r, **kwargs)
        return r

    def __call__(self, r):
        self.init_per_thread_state()

        r.register_hook("response", self.process)
        # This is a bit hacky and not fully general:
        # If we are using the shortcut of assuming that we must do SCRAM authentication,
        # we assume that the request will have to be repeated, so we remove the body initially and
        # squirrel it away to be re-attached to the final request at the end of the SCRAM handshake.
        # This has the advantage of not sending the potentially large body data repeatedly.
        if self.shortcut:
            self._thread_local.saved_body = r.body
            r.prepare_body(b"", None)
            r.headers["Content-Length"] = 0
            r.headers['Authorization'] = self._generate_client_first()
            self._thread_local.num_calls = 1  # skip state ahead

        return r
