from django.core.cache import cache
from hermes.models import Message
from astropy.table import Table
import io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib
import datetime


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
            formatted_message += "\n\n"
            string_buffer = io.StringIO()
            Table(message['data'][table]).write(string_buffer, format='ascii.basic')
            formatted_message += string_buffer.getvalue()
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
