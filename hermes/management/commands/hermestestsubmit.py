import csv
import datetime
import logging

from django.core.management.base import BaseCommand, CommandError
#from django.conf import settings

import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def get_hermes_photometry_data(filename):
    """Read a photometry.csv file to get some test data to submit. CSV looks Like this:

    time,filter,magnitude,error
    55959.06999999983,r,15.582,0.005
    55959.06999999983,V,15.676,0.007
    55959.06999999983,B,15.591,0.008

    This is just for testing and creates a nonsensical example Photometry report.
    """
    if filename is not None:
        # Convert CSV into python dict with csv.DictReader:
        with open(filename, newline='') as csvfile:
            photometry_reader = csv.DictReader(csvfile, delimiter=',')
            data = [row for row in photometry_reader]
    else:
        data = [
            {'time': '55957.06999999983', 'filter': 'r', 'magnitude': '15.582', 'error': '0.005'},
            {'time': '55958.06999999983', 'filter': 'V', 'magnitude': '15.676', 'error': '0.007'},
            {'time': '55959.06999999983', 'filter': 'B', 'magnitude': '15.591', 'error': '0.008'}
        ]

    hermes_photometry_data = []
    for example_photometry in data:
        hermes_photometry_data.append({
            'photometryId': 'NotARealTarget',  # target_name
            'dateObs': example_photometry['time'],
            'band': example_photometry['filter'],
            'brightness': example_photometry['magnitude'],
            'brightnessError': example_photometry['error'],
            'brightnessUnit': 'AB mag',
        })
    return hermes_photometry_data

class Command(BaseCommand):
    help = 'Submit a test message to Hopskotch hermes.test topic via HERMES API. Example code for how to do this.'

    def add_arguments(self, parser):
        # parser is an argparse.ArguementParser
        parser.add_argument('-a', '--author', required=True, help='Author (Submitter) of HERMES message.')
        parser.add_argument('-u', '--username', required=True, help='Username of SCiMMA Auth Credential')
        parser.add_argument('-p', '--password', required=True, help='Password of SCiMMA Auth Credential')
        parser.add_argument('-U', '--url', required=True, help='Base URL for HERMES deployment')
        parser.add_argument('-f', '--filename', required=False, help='Name of photometry csv file')

    def handle(self, *args, **options):
        logger.debug(f'args: {args}')
        logger.debug(f'options: {options}')

        # extract the command-line arguments
        author = options.get('author')
        username = options.get('username')
        password = options.get('password')
        base_url = options.get('url')
        photomentry_csv_filename = options.get('filename', None)

        # Construct the submit URL from the command-line supplied base URL.
        submit_url = f'{base_url}/submit_message/'

        # Headers - pass the SCiMMA Auth SCRAM credential in the request header
        headers = {
            'SCIMMA-API-Auth-Username': username,
            'SCIMMA-API-Auth-Password': password,
        }

        # Construct the request data dictionary. (this is just fake data to send in the message)
        hermes_photometry_data = get_hermes_photometry_data(photomentry_csv_filename)
        alert_data = {
            'topic': 'hermes.test',
            'title': 'Test Message from hermestestsubmit.py',
            'author': author,
            'data': {
                'photometry_data': hermes_photometry_data,
            },
            'message_text': f'Test alert from hermestest.py at {datetime.datetime.now()}',
        }

        # make the request
        submit_response = requests.post(url=submit_url, json=alert_data, headers=headers)
        logger.info(f'hermestestsubmit response.status_code: {submit_response.status_code}')
        logger.info(f'hermestestsubmit response.text: {submit_response.text}')



