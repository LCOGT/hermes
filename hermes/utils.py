from django.core.cache import cache
from django.http import QueryDict
from rest_framework import parsers
from rest_framework.renderers import JSONRenderer
from rest_framework.exceptions import APIException
import json
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from hop.http_scram import SCRAMAuth
from hop.io import Consumer, Deserializer
import smtplib
import bson
import uuid
import requests
from urllib.parse import urljoin
from django.conf import settings
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


# Use custom JSON encoder to remove bytestrings from the deserialized bson output
# Bytestrings seem to just be raw data bytes, which aren't utf-8 encoded so can't be JSONified
class RemoveBytesEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return '...'
        return json.JSONEncoder.default(self, obj)


class RemoveBytesRenderer(JSONRenderer):
    encoder_class = RemoveBytesEncoder


def convert_messages(bson_data):
    for i, message in enumerate(bson_data['messages']):
        bson_data['messages'][i] = convert_message(message)
    return bson_data


def convert_message(bson_message):
    """ take BSON formatted messages from scimma archive responses and convert to the proper form (JSON/AVRO/)
    """
    # Use the hop facilities to deserialize the bson message into something closer to JSON
    message = Consumer.ExternalMessage(
        data=bson_message['message'],
        headers=bson_message['metadata']['headers'],
        topic=bson_message['metadata']['topic'],
        partition=None,
        offset=None,
        timestamp=bson_message['metadata']['timestamp'],
        key=bson_message['metadata'].get('key')
    )
    payload = Deserializer.deserialize(message)
    format = 'json'
    # This step converts all the bytestrings stored within the message data into string strings
    message = {'metadata': bson_message['metadata'], 'annotations': bson_message['annotations']}
    if(message['metadata'].get('key')):
        message['metadata']['key'] = message['metadata']['key'].decode('utf-8')
    headers = bson_message.get('metadata', {}).get('headers', [])
    message['metadata']['headers'] = {}
    for header in headers:
        if header[0] == '_id':
            message['metadata']['headers'][header[0]] = str(uuid.UUID(bytes=header[1]))
        else:
            try:
                message['metadata']['headers'][header[0]] = header[1].decode('utf-8')
            except UnicodeDecodeError:
                message['metadata']['headers'][header[0]] = header[1]
        if header[0] == '_format':
            format = header[1].decode('utf-8')

    # Right now, only differentiate the gcntextnotice type - treat all other types the same
    match format:
        case 'gcntextnotice':
            message['message'] = payload.fields
        case _:
            message['message'] = payload.content

    return message


def get_all_public_topics():
    # TODO: Get the public topics from scimma admin or scimma archive rather than from hermes database
    all_topics = cache.get("all_public_topics", None)
    if not all_topics:
        all_topics = []
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
