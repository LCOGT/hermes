from django.core.cache import cache
from hermes.models import Message
from astropy.table import Table
import io


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


def convert_to_plaintext(message):
    # TODO: Incorporate the message uuid into here somewhere
    formatted_message = """{title}

{authors}

{message}""".format(title=message.get('title'),
                            authors=message.get('authors'),
                            message=message.get('message_text'))
    for table in ['target', 'photometry', 'astrometry', 'references']:
        if len(message['data'].get(table, [])) > 0:
            formatted_message += "\n"
            string_buffer = io.StringIO()
            Table(message['data'][table]).write(string_buffer, format='ascii.basic')
            formatted_message += string_buffer.getvalue()
    return formatted_message
