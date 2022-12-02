from abc import ABC, abstractmethod
from gzip import decompress
import io
import os
import logging
import requests

from astropy.io import fits
import healpy as hp
import numpy as np


logger = logging.getLogger(__name__)


class BaseParser(ABC):
    @abstractmethod
    def parse(self, message):
        ''' Method takes in a message instance, and fills in its data field with JSON data
            This method could also get or create some other model instances in order to link
            them to this message with different relationships.
        '''
        pass

    @staticmethod
    def get_confidence_regions(skymap_fits_url):
        ''' This helper method takes in the url of a skymap_fits_file and attempts to parse out
            the 50 and 90 area confidence values. It returns a tuple of (area_50, area_90).
        '''
        try:
            buffer = io.BytesIO()
            if '.gz' in skymap_fits_url:
                buffer.write(decompress(requests.get(skymap_fits_url, stream=True).content))
            else:
                buffer.write(requests.get(skymap_fits_url, stream=True).content)
            buffer.seek(0)
            hdul = fits.open(buffer, memmap=False)

            # Get the total number of healpixels in the map
            n_pixels = len(hdul[1].data)
            # Covert that to the nside parameter
            nside = hp.npix2nside(n_pixels)
            # Sort the probabilities so we can do the cumulative sum on them
            if 'PROB' in hdul[1].data.dtype.names:
                probabilities = hdul[1].data['PROB']
            else:
                probabilities = hdul[1].data['PROBDENSITY']
            probabilities.sort()
            # Reverse the list so that the largest pixels are first
            probabilities = probabilities[::-1]
            cumulative_probabilities = np.cumsum(probabilities)
            # The number of pixels in the 90 (or 50) percent range is just given by the first set of pixels that add up
            # to 0.9 (0.5)
            index_90 = np.min(np.flatnonzero(cumulative_probabilities >= 0.9))
            index_50 = np.min(np.flatnonzero(cumulative_probabilities >= 0.5))
            # Because the healpixel projection has equal area pixels, the total area is just the heal pixel area * the
            # number of heal pixels
            healpixel_area = hp.nside2pixarea(nside, degrees=True)
            area_50 = (index_50 + 1) * healpixel_area
            area_90 = (index_90 + 1) * healpixel_area

            return area_50, area_90
        except Exception as e:
            logger.error(f'Unable to parse {skymap_fits_url} for confidence regions: {e}')

        return None, None


    @staticmethod
    def convert_notice_type(notice_type):
        if 'warning' in notice_type.lower():
            return 'EARLY_WARNING'
        if 'initial' in notice_type.lower():
            return 'INITIAL'
        elif 'preliminary' in notice_type.lower():
            return 'PRELIMINARY'
        elif 'update' in notice_type.lower():
            return 'UPDATE'
        elif 'retraction' in notice_type.lower():
            return 'RETRACTION'
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


class DefaultParser(BaseParser):

    def __repr__(self):
        return 'Default Parser'

    def parse(self, message):
        return {}
