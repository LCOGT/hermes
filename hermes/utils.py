from django.core.cache import cache
from hermes.models import Message
from hop.auth import Auth
import jsons


TNS_TYPES = [
    'Afterglow',
    'AGN',
    'Computed-Ia',
    'Computed-IIb',
    'Computed-IIn',
    'Computed-IIP',
    'Computed-PISN',
    'CV',
    'FBOT',
    'FRB',
    'Galaxy',
    'Gap',
    'Gap I',
    'Gap II',
    'ILRT',
    'Impostor-SN',
    'Kilonova',
    'LBV',
    'Light-Echo',
    'LRN',
    'M dwarf',
    'Nova',
    'QSO',
    'SLSN-I',
    'SLSN-II',
    'SLSN-R',
    'SN',
    'SN I',
    'SN I-faint',
    'SN I-rapid',
    'SN Ia',
    'SN Ia-91bg-like',
    'SN Ia-91T-like',
    'SN Ia-Ca-rich',
    'SN Ia-CSM',
    'SN Ia-pec',
    'SN Ia-SC',
    'SN Iax[02cx-like]',
    'SN Ib',
    'SN Ib-Ca-rich',
    'SN Ib-pec',
    'SN Ib/c',
    'SN Ib/c-Ca-rich',
    'SN Ibn',
    'SN Ibn/Icn',
    'SN Ic',
    'SN Ic-BL',
    'SN Ic-Ca-rich',
    'SN Ic-pec',
    'SN Icn',
    'SN II',
    'SN II-pec',
    'SN IIb',
    'SN IIL',
    'SN IIn',
    'SN IIn-pec',
    'SN IIP',
    'Std-spec',
    'TDE',
    'TDE-H',
    'TDE-H-He',
    'TDE-He',
    'Varstar',
    'WR',
    'WR-WC',
    'WR-WN',
    'WR-WO',
    'Other'
]


def get_all_public_topics():
    all_topics = cache.get("all_public_topics", None)
    if not all_topics:
        all_topics = sorted(list(Message.objects.order_by().values_list('topic', flat=True).distinct()))
        cache.set("all_public_topics", all_topics, 3600)
    return all_topics


def extract_hop_auth(request) -> Auth:
    """Return a hop.Auth instance from either the request.header or the request.session.

    The reqeust.header takes precidence over the request.session.

    If this the request is comming from the HERMES front-end, then a hop.auth.Auth instance was inserted
    into the request's session dictionary upon logon in AuthenticationBackend.authenticate.
    This method extracts it. (`jsons` is used (vs. json) because Auth is non-trivial to
    serialize/deserialize, and the stdlib `json` package won't handle it correctly).

    If this this request is coming via the API, then a SCiMMA Auth SCRAM credential must be
    extracted from the request header and then used to instanciate the returned hop.Auth.
    """
    if 'SCIMMA-API-Auth-Username' in request.headers:
        # A SCiMMA Auth SCRAM credential came in request.headers. Use it to get hop.auth.Auth instance.
        username = request.headers['SCIMMA-API-Auth-Username']
        password = request.headers['SCIMMA-API-Auth-Password']
        hop_user_auth = Auth(username, password)
    else:
        # deserialize the hop.auth.Auth instance from the request.session
        hop_user_auth: Auth = jsons.load(request.session['hop_user_auth_json'], Auth)

    return hop_user_auth
