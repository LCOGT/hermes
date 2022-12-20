from django.contrib import admin
from hermes.models import Message, Target, NonLocalizedEvent, NonLocalizedEventSequence


admin.site.register(Message)
admin.site.register(Target)
admin.site.register(NonLocalizedEvent)
admin.site.register(NonLocalizedEventSequence)
