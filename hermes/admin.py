from django.contrib import admin
from hermes.models import Profile, OAuthToken, Message, Target, NonLocalizedEvent, NonLocalizedEventSequence


admin.site.register(Profile)
admin.site.register(OAuthToken)
admin.site.register(Message)
admin.site.register(Target)
admin.site.register(NonLocalizedEvent)
admin.site.register(NonLocalizedEventSequence)
