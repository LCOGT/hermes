from abc import ABC, abstractmethod
from gzip import decompress
import io
import os
import logging
import requests

from astropy.io import fits
import healpy as hp
import numpy as np

from hermes.models import NonLocalizedEventSequence

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    @abstractmethod
    def parse(self, message, data):
        ''' Method takes in a message instance and a data dict.
            This method could also get or create some other model instances in order to link
            them to this message with different relationships.
            Should return True if the message can be parsed, False if it cannot.
        '''
        pass

    @staticmethod
    def convert_notice_type(notice_type):
        if 'warning' in notice_type.lower():
            return NonLocalizedEventSequence.NonLocalizedEventSequenceType.EARLY_WARNING
        if 'initial' in notice_type.lower():
            return NonLocalizedEventSequence.NonLocalizedEventSequenceType.INITIAL
        elif 'preliminary' in notice_type.lower():
            return NonLocalizedEventSequence.NonLocalizedEventSequenceType.PRELIMINARY
        elif 'update' in notice_type.lower():
            return NonLocalizedEventSequence.NonLocalizedEventSequenceType.UPDATE
        elif 'retraction' in notice_type.lower():
            return NonLocalizedEventSequence.NonLocalizedEventSequenceType.RETRACTION
        return ''

    @staticmethod
    def get_moc_url_from_skymap_fits_url(skymap_fits_url):
        base, filename = os.path.split(skymap_fits_url)
        # Repair broken skymap filenames given in gcn mock alerts right now
        if filename.endswith('.fit'):
            filename = filename + 's'
        # Replace the non-MOC skymap url provided with the MOC version, but keep the ,# on the end
        filename = filename.replace('LALInference.fits.gz', 'LALInference.multiorder.fits')
        filename = filename.replace('bayestar.fits.gz', 'bayestar.multiorder.fits')
        return os.path.join(base, filename)
