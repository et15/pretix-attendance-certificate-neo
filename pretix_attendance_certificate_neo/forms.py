from django import forms
from django.utils.translation import gettext_lazy as _
from pretix.plugins.sendmail.forms import FormPlaceholderMixin

from pretix_attendance_certificate_neo.models import (
    AttendanceCertificateLayout,
    OrganizerSigningCertificate,
    TimestampMode,
    name_conflict_error,
)
from pretix_attendance_certificate_neo.signing import (
    InvalidCertificate,
    load_pkcs12,
    validate_timestamp_url,
)

# Organizer-wide templates have no single event to ask which placeholders
# exist, so they get a general note instead of the generated list.
ORGANIZER_PLACEHOLDER_HELP = _(
    "Placeholders: {event} (event name), {name} (attendee's full name), "
    '{name_for_salutation} (name as used in a salutation, e.g. "Mr Doe"), '
    "{code} (order code), {url} (link to the order page). Heads-up: "
    "{name_given_name} (first name) and {name_family_name} (last name) only exist "
    "for events that collect the name in parts. For any other event they are sent "
    "as literal text, so use {name} if the template is shared between events. "
    "Which further placeholders exist (e.g. event meta data) depends on the event."
)


class OrganizerLayoutForm(FormPlaceholderMixin, forms.ModelForm):
    class Meta:
        model = AttendanceCertificateLayout
        fields = ["name", "mail_subject", "mail_text"]

    def __init__(self, *args, **kwargs):
        locales = kwargs.pop("locales", None)
        # Only set for event templates (see EventLayoutFormMixin).
        self.event = kwargs.pop("event", None)
        super().__init__(*args, **kwargs)
        # I18nCharField/I18nTextField build one sub-field per locale in
        # settings.LANGUAGES by default (dozens) unless told otherwise - a
        # plain ModelForm has no event/organizer to infer that from, so the
        # view passes the right locale list in explicitly.
        if locales:
            for fname in ("mail_subject", "mail_text"):
                field = self.fields[fname]
                self.fields[fname] = field.__class__(
                    locales=locales,
                    widget=field.widget.__class__,
                    label=field.label,
                    required=field.required,
                )
        for fname in ("mail_subject", "mail_text"):
            if self.event is None:
                self.fields[fname].help_text = ORGANIZER_PLACEHOLDER_HELP
            else:
                # Exactly what the "Send out certificates" page does: lists the
                # placeholders pretix offers for this event and rejects unknown
                # ones on save.
                self._set_field_placeholders(
                    fname, ["event", "order", "position_or_address"]
                )

    def clean_name(self):
        name = self.cleaned_data["name"]
        error = name_conflict_error(self.instance, name, event=self.event)
        if error:
            raise forms.ValidationError(error)
        return name


class SigningSettingsForm(forms.ModelForm):
    class Meta:
        model = OrganizerSigningCertificate
        fields = ["enabled", "reason", "timestamp_mode", "timestamp_url"]

    def clean(self):
        data = super().clean()
        mode = data.get("timestamp_mode")
        url = data.get("timestamp_url")
        if mode and mode != TimestampMode.OFF:
            if not url:
                self.add_error(
                    "timestamp_url",
                    _("Please enter the address of a timestamp server."),
                )
            else:
                try:
                    validate_timestamp_url(url)
                except ValueError as e:
                    self.add_error("timestamp_url", str(e))
        return data


class GenerateCertificateForm(forms.Form):
    common_name = forms.CharField(
        max_length=64,
        label=_("Name"),
        help_text=_("Shown as the signer, e.g. the name of your organization."),
    )
    organization = forms.CharField(
        max_length=64, required=False, label=_("Organization")
    )
    valid_years = forms.IntegerField(
        min_value=1,
        max_value=30,
        initial=5,
        label=_("Validity in years"),
        help_text=_(
            "Signed documents stay verifiable after expiry, but new "
            "certificates can only be signed with a certificate you replace "
            "in time."
        ),
    )


class ImportCertificateForm(forms.Form):
    pkcs12 = forms.FileField(
        label=_("Certificate with private key (.p12 / .pfx)"),
    )
    password = forms.CharField(
        required=False,
        label=_("Password"),
        widget=forms.PasswordInput(render_value=False),
    )

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        try:
            data["pems"] = load_pkcs12(
                data["pkcs12"].read(), data.get("password") or None
            )
        except InvalidCertificate:
            raise forms.ValidationError(
                _("The file could not be read. Check the file and the password.")
            ) from None
        return data
