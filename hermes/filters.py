from django_filters import rest_framework as filters
from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.measure import D

from hermes.models import Message, NonLocalizedEvent, NonLocalizedEventSequence, Target

import math
EARTH_RADIUS_METERS = 6371008.77141506


class MessageFilter(filters.FilterSet):
    cone_search = filters.CharFilter(method='filter_cone_search', label='Cone Search',
                                     help_text='RA, Dec, Radius (degrees)')
    polygon_search = filters.CharFilter(method='filter_polygon_search', label='Polygon Search',
                                        help_text='Comma-separated pairs of space-delimited coordinates (degrees).')
    event_id = filters.CharFilter(field_name='nonlocalizedevents__event_id', lookup_expr='icontains', label='Event Id contains')
    event_id_exact = filters.CharFilter(field_name='nonlocalizedevents__event_id', lookup_expr='exact', label='Event Id exact')
    message_contains = filters.CharFilter(field_name='message_text', lookup_expr='icontains', help_text='Message text contains keyword')
    data_has_key = filters.CharFilter(field_name='data', lookup_expr='has_key', help_text='Structured data contains key')
    topic = filters.CharFilter(field_name='topic', lookup_expr='icontains', help_text='Topic contains keyword')
    topic_exact = filters.CharFilter(field_name='topic', lookup_expr='exact', help_text='Topic exact')
    authors = filters.CharFilter(field_name='authors', lookup_expr='icontains', help_text='Authors contains keyword')
    submitter = filters.CharFilter(field_name='submitter', lookup_expr='icontains', help_text='Submitter contains keyword')
    title = filters.CharFilter(field_name='title', lookup_expr='icontains', help_text='Title contains keyword')

    class Meta:
        model = Message
        fields = (
            'topic', 'title', 'published', 'authors', 'created', 'modified', 'cone_search', 'polygon_search', 'event_id',
            'event_id_exact', 'data_has_key', 'topic_exact', 'message_contains', 'submitter'
        )


    def filter_cone_search(self, queryset, name, value):
        ra, dec, radius = value.split(',')

        ra = float(ra)
        dec = float(dec)

        radius_meters = 2 * math.pi * EARTH_RADIUS_METERS * float(radius) / 360

        return queryset.filter(targets__coordinate__distance_lte=(Point(ra, dec), D(m=radius_meters)))

    def filter_polygon_search(self, queryset, name, value):
        # TODO: document this function in a docstring with example value input and resulting vertices
        value += ', ' + value.split(', ', 1)[0]
        vertices = tuple((float(v.split(' ')[0]), float(v.split(' ')[1])) for v in value.split(', '))  # TODO: explain!
        polygon = Polygon(vertices, srid=4035)
        return queryset.filter(targets__coordinate__within=polygon)


class NonLocalizedEventFilter(filters.FilterSet):
    event_id_exact = filters.CharFilter(field_name='event_id', lookup_expr='exact', label='Event Id exact')
    event_id = filters.CharFilter(field_name='event_id', lookup_expr='icontains', label='Event Id contains')

    class Meta:
        model = NonLocalizedEvent
        fields = (
            'event_id', 'event_id_exact'
        )


class NonLocalizedEventSequenceFilter(filters.FilterSet):
    event_id = filters.CharFilter(field_name='event__event_id', lookup_expr='icontains', label='Event Id contains')
    event_id_exact = filters.CharFilter(field_name='event__event_id', lookup_expr='exact', label='Event Id exact')
    sequence_type = filters.MultipleChoiceFilter(field_name='sequence_type', choices=NonLocalizedEventSequence.SEQUENCE_TYPES)
    exclude_sequence_type = filters.MultipleChoiceFilter(field_name='sequence_type', choices=NonLocalizedEventSequence.SEQUENCE_TYPES, exclude=True)

    class Meta:
        model = NonLocalizedEventSequence
        fields = (
            'event_id', 'event_id_exact', 'sequence_number', 'sequence_type'
        )


class TargetFilter(filters.FilterSet):
    cone_search = filters.CharFilter(method='filter_cone_search', label='Cone Search',
                                     help_text='RA, Dec, Radius (degrees)')
    polygon_search = filters.CharFilter(method='filter_polygon_search', label='Polygon Search',
                                        help_text='Comma-separated pairs of space-delimited coordinates (degrees).')
    event_id = filters.CharFilter(field_name='messages__nonlocalizedevents__event_id', lookup_expr='icontains', label='Event Id contains')
    name = filters.CharFilter(field_name='name', lookup_expr='icontains', help_text='Name contains keyword')
    name_exact = filters.CharFilter(field_name='name', lookup_expr='exact', help_text='Name exact')

    class Meta:
        model = Target
        fields = (
            'name', 'cone_search', 'polygon_search', 'name_exact'
        )

    def filter_cone_search(self, queryset, name, value):
        ra, dec, radius = value.split(',')

        ra = float(ra)
        dec = float(dec)

        radius_meters = 2 * math.pi * EARTH_RADIUS_METERS * float(radius) / 360

        return queryset.filter(coordinate__distance_lte=(Point(ra, dec), D(m=radius_meters)))

    def filter_polygon_search(self, queryset, name, value):
        # TODO: document this function in a docstring with example value input and resulting vertices
        value += ', ' + value.split(', ', 1)[0]
        vertices = tuple((float(v.split(' ')[0]), float(v.split(' ')[1])) for v in value.split(', '))  # TODO: explain!
        polygon = Polygon(vertices, srid=4035)
        return queryset.filter(coordinate__within=polygon)
