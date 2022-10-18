from abc import abstractmethod
from http.client import responses
import json
import logging


from django.contrib.auth.models import User
from django.conf import settings

#from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.middleware import csrf

from django.views.generic import ListView, DetailView, FormView, RedirectView, View
from django.urls import reverse_lazy
from django.shortcuts import redirect
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response

from astropy.coordinates import SkyCoord
from astropy import units
import jsons
from marshmallow import Schema, fields, ValidationError, validates_schema, validate

from hop import Stream
from hop.auth import Auth

from rest_framework import viewsets

from hermes.brokers import hopskotch
from hermes.models import Message
from hermes.forms import MessageForm
from hermes.serializers import MessageSerializer

from datetime import datetime
import astropy.time


logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)


def _extract_hop_auth(request) -> Auth:
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


def coordinates_valid(data):
        for row in data:
            try:
                ra, dec = float(row['ra']), float(row['dec'])
                SkyCoord(ra, dec, unit=(units.deg, units.deg))
            except:
                try:
                    SkyCoord(row['ra'], row['dec'], unit=(units.hourangle, units.deg))
                except:
                    raise ValidationError('Coordinates do not all have valid RA and Dec')


class CandidateDataSchema(Schema):
    candidate_id = fields.String(required=True)
    ra = fields.String(required=True)
    dec = fields.String(required=True)
    discovery_date = fields.String(required=True)
    telescope = fields.String()
    instrument = fields.String()
    band = fields.String(required=True)
    brightness = fields.Float()
    brightnessError = fields.Float()
    brightnessUnit = fields.String()

    @validates_schema(skip_on_field_errors=True)
    def validate_coordinates(self, data):
        coordinates_valid(data)

    @validates_schema(skip_on_field_errors=True)
    def validate_brightness_unit(self, data):
        brightness_units = ['AB mag', 'Vega mag']
        for row in data:
            if row['brightness_unit'] not in brightness_units:
                raise ValidationError(f'Unrecognized brightness unit. Accepted brightness units are {brightness_units}')

class MessageSchema(Schema):
    title = fields.String(required=True)
    topic = fields.String(required=True)
    event_id = fields.String()
    message_text = fields.String(required=True)
    submitter = fields.String(required=True)
    authors = fields.String()
    @property
    @abstractmethod
    def data(self):
        pass


class CandidateMessageSchema(MessageSchema):
    data = fields.Nested(CandidateDataSchema)


class PhotometryDataSchema(Schema):
    target_name = fields.String()
    ra = fields.String()
    dec = fields.String()
    date_observed = fields.String(required=True)
    date_format = fields.String()
    telescope = fields.String(required=True)
    instrument = fields.String()
    band = fields.String(required=True)
    brightness = fields.Float(required=True)
    brightness_error = fields.Float(required=True)
    brightness_unit = fields.String(validate=validate.OneOf(choices=["AB mag", "Vega mag", "mJy", "erg / s / cm² / Å"]), required=True)

    @validates_schema(skip_on_field_errors=True)
    def validate_coordinates(self, data):
        coordinates_valid(data)

    @validates_schema(skip_on_field_errors=True)
    def validate_date_observed(self, data):
        for row in data:
            if 'date_format' in row:
                if 'jd' in row['date_format'].lower():
                    try: 
                        float(row['date_observed'])
                    except ValueError:
                        raise ValidationError(f'Date observed: {row["date_observed"]} does parse based on provided date format: {row["date_format"]}')
                else:
                    try:
                        date_observed = datetime.strptime(row['date_observed'], row['date_format'])
                    except ValueError:
                        raise ValidationError(f'Date observed: {row["date_observed"]} does parse based on provided date format: {row["date_format"]}')
            else:
                try:
                    date_observed = astropy.time.Time(row["date_observed"])
                except ValueError:
                    raise ValidationError(f'Date observed: {row["date_observed"]} does not parse and no expected date format was provided.')


class PhotometryMessageSchema(MessageSchema):
    data = fields.Nested(PhotometryDataSchema)


class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    pagination_class = None



class TopicViewSet(viewsets.ViewSet):
    """This ViewSet does not have a Model backing it. It uses the SCiMMA Auth (Hop Auth) API
    to construct a response and return a dictionary:
        {
        'read': <topic list>,
        'write': <topic-list>,
        }
    """
    def list(self, request, *args, **kwargs) -> JsonResponse:
        """
        """
        username = request.user.username
        try:
            user_hop_auth: Auth = _extract_hop_auth(request)
        except KeyError as err:
            # This means no SCRAM creds were saved in this request's Session dict
            # TODO: what to do for HERMES Guest (AnonymousUser)
            logger.error(f'TopicViewSet {err}')
            default_topics = {
                'read': ['hermes.test', 'gcn.circular'],
                'write': ['hermes.test'],
                }
            logger.error(f'TopicViewSet returning default topics: {default_topics}')
            return JsonResponse(data=default_topics)

        credential_name = user_hop_auth.username
        user_api_token = hopskotch.get_user_api_token(username)

        topics = hopskotch.get_user_topics(username, credential_name, user_api_token)
        logger.info(f'TopicViewSet.list topics for {username}: {topics}')

        response = JsonResponse(data=topics)
        return response


class MessageListView(ListView):
    # change the model form Message to User for OIDC experimentation
    model = User
    template_name = 'hermes/message_list.html'


class MessageDetailView(DetailView):
    model = Message


class MessageFormView(FormView):
    template_name = "hermes/generic_message.html"
    form_class = MessageForm
    success_url = reverse_lazy('index')

    def form_valid(self, form):
        super().form_valid(form)
        new_message_data = form.cleaned_data

        # List of universal Fields
        non_json_fields = ['title', 'author', 'message_text']
        non_json_dict = {key: new_message_data[key] for key in new_message_data.keys() if key in non_json_fields}
        message = Message(**non_json_dict)

        # convert form specific data to JSON
        json_dict = {key: new_message_data[key] for key in new_message_data.keys() if key not in non_json_fields}
        json_data = json.dumps(json_dict, indent=4)
        message.data = json_data

        message.save()

        return redirect(self.get_success_url())


def submit_to_hop(request, message):
    """Open the Hopskotch kafka stream for write and publish an Alert

    The request holds the Session dict which has the 'hop_user_auth_json` key
    whose value can be deserialized into a hop.auth.Auth instance to open the
    stream with. (The hop.auth.Auth instance was added to the Session dict upon
    logon via the HopskotchOIDCAuthenticationBackend.authenticate method).
    """
    try:
        hop_auth: Auth = _extract_hop_auth(request)
    except KeyError as err:
        logger.error(f'Hopskotch Authorization for User {request.user.username} not found.  err: {err}')
        # TODO: REMOVE THE FOLLOWING CODE AFTER TESTING!!
        # use the Hermes service account temporarily while testing...
        logger.warning(f'Submitting with Hermes service account authorization (testing only)')
        hop_auth: Auth = hopskotch.get_hermes_hop_authorization()

    # TODO: provide some indication of the User/vo_person_id submitting the message
    logger.info(f'submit_to_hop User {request.user} with credentials {hop_auth.username}')

    try:
        topic = 'hermes.test'
        stream = Stream(auth=hop_auth)
        # open for write ('w')
        with stream.open(f'kafka://kafka.scimma.org/{topic}', 'w') as s:
            metadata = {'topic': topic}
            s.write(message, metadata)
    except Exception as e:
        return Response({'message': f'Error posting message to kafka: {e}'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response({"message": {"Message was submitted successfully"}}, status=status.HTTP_200_OK)


class HopSubmitView(APIView):
    """
    Submit a message to the hop client
    """

    def post(self, request, *args, **kwargs):
        """Sumbit to Hopskotch

        Requests to this method go through rest_framework.authentication.SessionMiddleware
        and as such require a CSRF token in the header. see GetCSRFTokenView.
        """
        # request.data does not read the data stream again. So,
        # that is more appropriate than request.body which does
        # (read the stream again).
        # NO:
        #logger.info(f'type(request.body): {type(request.body)}')
        #logger.info(f'request.body: {request.body}')
        # YES:
        logger.debug(f'request.data: {request.data}')

        return submit_to_hop(request, request.data)

    def get(self, request, *args, **kwargs):
        return Response({"message": "Supply any valid json to send a message to kafka."}, status=status.HTTP_200_OK)


class HopSubmitCandidatesView(APIView):
    def get(self, request, *args, **kwargs):
        message = """This endpoint is used to send a message with a list of potential candidates corresponding to a 
        non-localized event.
        
        Requests should be structured as below:
        
        {title: <Title of the message>,
         topic: <kafka topic to post message to>, 
         submitter: <submitter of the message>,
         authors: <Text full list of authors on a message>
         message_text: <Text of the message to send>,
         event_id: <ID of the non-localized event for these candidates>,
         data: {[{candidate_id: <ID of the candidate>,
                  ra: <Right Ascension in hh:mm:ss.ssss or decimal degrees>,
                  dec: <Declination in dd:mm:ss.ssss or decimal degrees>,
                  discovery_date: <Date/time of the candidate discovery>,
                  date_format: <Python strptime format string or "mjd" or "jd">,
                  telescope: <Discovery telescope>,
                  instrument: <Discovery instrument>,
                  band: <Wavelength band of the discovery observation>,
                  brightness: <Brightness of the candidate at discovery>,
                  brightness_error: <Brightness error of the candidate at discovery>,
                  brightness_unit: <Brightness units for the discovery, 
                                   current supported values: [AB mag, Vega mag]>
                           }, ...]}
        }
        """
        return Response({"message": message}, status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        candidate_schema = CandidateMessageSchema()
        candidates, errors = candidate_schema.load(request.json)

        logger.debug(f"Request data: {request.json}")
        if errors:
            return Response(errors, status.HTTP_400_BAD_REQUEST)

        return submit_to_hop(request, vars(candidates))


class SubmitPhotometryView(APIView):
    def get(self, request, *args, **kwargs):
        message = """This endpoint is used to send a message to report photometry of one or more targets.
         
        Requests should be structured as below:

        {title: <Title of the message>,
         topic: <kafka topic to post message to>, 
         submitter: <submitter of the message>,
         authors: <Text full list of authors on a message>
         message_text: <Text of the message to send>,
         event_id: <ID of the non-localized event for these candidates>,
         data: {[{target_name: <Name of the observed target>,
                  ra: <Right Ascension in hh:mm:ss.ssss or decimal degrees>,
                  dec: <Declination in dd:mm:ss.ssss or decimal degrees>,
                  date_observed: <Date/time of the observation>,
                  telescope: <Discovery telescope>,
                  instrument: <Discovery instrument>,
                  band: <Wavelength band of the discovery observation>,
                  brightness: <Brightness of the candidate at discovery>,
                  brightness_error: <Brightness error of the candidate at discovery>,
                  brightness_unit: <Brightness units for the discovery, 
                                   current supported values: [AB mag, Vega mag, mJy, and erg / s / cm² / Å]>
                           }, ...]}
        }
        """
        return Response({"message": message}, status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        photometry_schema = PhotometryMessageSchema()
        photometry, errors = photometry_schema.load(request.json)

        if errors:
            logger.debug(f"Request data: {request.json}")
            return Response(errors, status.HTTP_400_BAD_REQUEST)

        return submit_to_hop(request, vars(photometry))


class LoginRedirectView(RedirectView):
    pattern_name = 'login-redirect'

    def get(self, request, *args, **kwargs):

        logger.debug(f'LoginRedirectView.get -- request.user: {request.user}')

        login_redirect_url = f'{settings.HERMES_FRONT_END_BASE_URL}#/?user={request.user.email}'
        logger.info(f'LoginRedirectView.get -- setting self.url and redirecting to {login_redirect_url}')
        self.url = login_redirect_url

        return super().get(request, *args, **kwargs)

class LogoutRedirectView(RedirectView):
    pattern_name = 'logout-redirect'

    def get(self, request, *args, **kwargs):

        logout_redirect_url = f'{settings.HERMES_FRONT_END_BASE_URL}'
        logger.info(f'LogoutRedirectView.get setting self.url and redirecting to {logout_redirect_url}')
        self.url = logout_redirect_url

        return super().get(request, *args, **kwargs)


class GetCSRFTokenView(View):
    pattern_name = 'get-csrf-token'

    def get(self, request, *args, **kwargs) -> JsonResponse:
        """return a CSRF token from the middleware in a JsonResponse:
        key: 'token'
        value: <csrf token>

        The frontend can call this method upon start-up, store the token
        in a cookie, and include it in subsequent calls like this:
        headers: {'X-CSRFToken': this_token}
        """
        token = csrf.get_token(request)
        response = JsonResponse(data={'token': token})
        # this is where you can modify or log the response before returning it
        return response
