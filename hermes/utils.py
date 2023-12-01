from django.core.cache import cache
from django.http import QueryDict
from rest_framework import parsers
from hermes.models import Message
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib


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
    output = f'#### {name}:\n'

    # Only add keys present in the ordering into the markdown table so it is manageable
    keys_present = {key for datum in data for key in datum.keys() if key in key_ordering}
    ordered_keys = sorted(keys_present, key=key_ordering.index)

    # Add the header line for the markdown table
    output += f"| {' | '.join(ordered_keys)} |\n"

    # Add the mardown dashed line row below the header
    output += f"| {' | '.join(['---' for key in ordered_keys])} |\n"

    # Now add the table values for each row
    for datum in data:
        output += '|'
        for key in ordered_keys:
            output += f" {datum.get(key, '')} |"
        output += '\n'

    return output


def convert_to_plaintext(message):
    # TODO: Incorporate the message uuid into here somewhere
    formatted_message = """{authors}\n\n{message}\n\n""".format(
        authors=message.get('authors'),
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
