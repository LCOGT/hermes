from django import forms


class MessageForm(forms.Form):
    title = forms.CharField(max_length=50)
    authors = forms.CharField(max_length=50)
    message_text = forms.CharField(widget=forms.Textarea, required=False)
    thing1 = forms.BooleanField(required=False)
    thing2 = forms.FloatField(required=False)
    thing3 = forms.CharField(required=False)
