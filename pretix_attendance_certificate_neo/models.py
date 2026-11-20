import string

from django.db import models, transaction
from django.db.models import Q
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _
from django_scopes import scope
from i18nfield.fields import I18nCharField, I18nTextField
from pretix.base.models import LoggedModel


def bg_name(instance, filename: str) -> str:
    secret = get_random_string(
        length=16, allowed_chars=string.ascii_letters + string.digits
    )
    return "pub/{org}/{ev}/attendance_certificates/{id}-{secret}.pdf".format(
        org=instance.scope_organizer.slug,
        ev=instance.event.slug if instance.event_id else "_organizer",
        id=instance.pk,
        secret=secret,
    )


class AttendanceCertificateLayout(LoggedModel):
    event = models.ForeignKey(
        "pretixbase.Event",
        on_delete=models.CASCADE,
        related_name="attendance_certificate_layouts",
        null=True,
        blank=True,
    )
    organizer = models.ForeignKey(
        "pretixbase.Organizer",
        on_delete=models.CASCADE,
        related_name="attendance_certificate_layouts",
        null=True,
        blank=True,
    )
    active_events = models.ManyToManyField(
        "pretixbase.Event",
        through="LayoutActivation",
        through_fields=("layout", "event"),
        blank=True,
        related_name="active_organizer_certificate_layouts",
    )
    name = models.CharField(max_length=190, verbose_name=_("Name"))
    layout = models.TextField(
        default=(
            '[{"type":"textarea","left":"13.09","bottom":"49.73","fontsize":"23.6","color":[0,0,0,1],'
            '"fontfamily":"Open Sans","bold":true,"italic":false,"width":"121.83","content":"attendee_name",'  # noqa
            '"text":"Marco","align":"center"}]'
        )
    )
    background = models.FileField(
        null=True, blank=True, upload_to=bg_name, max_length=255
    )
    mail_subject = I18nCharField(
        verbose_name=_("Email subject"),
        max_length=255,
        default="[{event}] Your certificate of attendance",
    )
    mail_text = I18nTextField(
        verbose_name=_("Email text"),
        default=(
            "Hello,\n\n"
            "please find your certificate of attendance for {event} attached to "
            "this email.\n\n"
            "Best regards"
        ),
    )

    def __str__(self):
        return self.name

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(event__isnull=False, organizer__isnull=True)
                    | Q(event__isnull=True, organizer__isnull=False)
                ),
                name="attendance_certificate_layout_event_xor_organizer",
            )
        ]

    @property
    def scope_organizer(self):
        return self.organizer or self.event.organizer

    @transaction.atomic
    def copy_to_event(self, event, *, name):
        layout = AttendanceCertificateLayout.objects.create(
            event=event,
            name=name,
            layout=self.layout,
            mail_subject=self.mail_subject,
            mail_text=self.mail_text,
        )
        if self.background:
            with self.background.storage.open(self.background.name, "rb") as background:
                layout.background.save("background.pdf", background)
        return layout

    @classmethod
    def visible_to(cls, event):
        """All layouts an event may view/manage: its own plus every
        organizer-wide one, regardless of whether it has been activated."""
        return cls.objects.filter(Q(event=event) | Q(organizer=event.organizer))


class TimestampMode(models.TextChoices):
    OFF = "off", _("Off")
    OPTIONAL = "optional", _("On, if possible (sign without if unreachable)")
    REQUIRED = "required", _("On, required (fail if unreachable)")


class OrganizerSigningCertificate(models.Model):
    """The organizer-wide certificate used to digitally sign every certificate
    of attendance of the organizer's events (PAdES, see signing.py).

    The private key is stored unencrypted, like other secrets pretix keeps for
    an organizer (e.g. SMTP passwords). Access is limited to organizer admins
    and the key never leaves the server."""

    organizer = models.OneToOneField(
        "pretixbase.Organizer",
        on_delete=models.CASCADE,
        related_name="attendance_certificate_signing",
    )
    certificate_pem = models.TextField()
    private_key_pem = models.TextField()
    # Further certificates of the chain (intermediate/root CA) from an imported
    # .p12, PEM concatenated. Embedded into every signature.
    chain_pem = models.TextField(blank=True, default="")
    enabled = models.BooleanField(
        default=True,
        verbose_name=_("Sign certificates of attendance"),
        help_text=_(
            "If enabled, every certificate of attendance of this organizer is "
            "digitally signed with this certificate."
        ),
    )
    reason = models.CharField(
        max_length=190,
        blank=True,
        default="Certificate of attendance",
        verbose_name=_("Reason"),
        help_text=_("Stored in the signature, shown by PDF readers."),
    )
    timestamp_mode = models.CharField(
        max_length=16,
        choices=TimestampMode.choices,
        default=TimestampMode.OFF,
        verbose_name=_("Trusted timestamp"),
        help_text=_(
            "A timestamp from an independent time stamping authority (RFC 3161) "
            "proves when a certificate was signed and keeps the signature "
            "verifiable after your certificate expires. If the authority is "
            'unreachable, "if possible" signs without a timestamp and logs a '
            'warning, "required" refuses to create the certificate (e.g. '
            "the mail run stops)."
        ),
    )
    timestamp_url = models.URLField(
        max_length=255,
        blank=True,
        verbose_name=_("Timestamp server URL"),
        help_text=_(
            "Address of the time stamping authority, e.g. "
            "http://timestamp.digicert.com or http://timestamp.sectigo.com. "
            "Only a hash of the signature is sent, never the document."
        ),
    )
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Signing certificate of {self.organizer_id}"


class LayoutActivation(models.Model):  # noqa: DJ008
    """Per-event settings of a template.

    For an organizer-wide template the existence of this row *is* the
    activation for the event. Event-owned templates are always available, so
    for them the row is optional and only carries the check-in list.
    """

    layout = models.ForeignKey(
        AttendanceCertificateLayout,
        on_delete=models.CASCADE,
        related_name="activations",
    )
    event = models.ForeignKey(
        "pretixbase.Event",
        on_delete=models.CASCADE,
        related_name="attendance_certificate_activations",
    )
    checkin_list = models.ForeignKey(
        "pretixbase.CheckinList",
        null=True,
        blank=True,
        # Deleting the list must never widen who is eligible: a pre_delete
        # hook (see signals.py) deactivates the template before this runs.
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("Check-in list"),
        help_text=_(
            "Only attendees checked in on this list are eligible for the "
            "template. Leave empty to make it available to everyone."
        ),
    )

    active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
        help_text=_(
            "Deactivated templates are not offered for this event. This is "
            "set automatically when the tied check-in list is deleted."
        ),
    )

    class Meta:
        unique_together = (("layout", "event"),)


def available_layouts(event):
    """Layouts actually usable for rendering a certificate for this event:
    its own layouts plus organizer-wide ones explicitly activated for it, minus
    any that were deactivated."""
    deactivated = LayoutActivation.objects.filter(event=event, active=False)
    return (
        AttendanceCertificateLayout.objects.filter(
            Q(event=event) | Q(organizer=event.organizer, active_events=event)
        )
        .exclude(pk__in=deactivated.values("layout_id"))
        .order_by("name", "pk")
        .distinct()
    )


class CertificateOption:
    """One template as seen from one attendee."""

    def __init__(self, layout, checkin_list, applicable):
        self.layout = layout
        self.checkin_list = checkin_list
        self.applicable = applicable

    @property
    def pk(self):
        return self.layout.pk


def certificate_options(position):
    """All templates available for the position's event, each flagged
    with whether the attendee is eligible (the template is tied to no check-in
    list, or the attendee has a successful check-in on that list)."""
    from pretix.base.models import Checkin

    event = position.order.event
    activations = {
        a.layout_id: a
        for a in LayoutActivation.objects.filter(event=event).select_related(
            "checkin_list"
        )
    }
    with scope(organizer=event.organizer):
        checked_in = set(
            Checkin.all.filter(position=position, successful=True).values_list(
                "list_id", flat=True
            )
        )
    options = []
    for layout in available_layouts(event):
        activation = activations.get(layout.pk)
        checkin_list = activation.checkin_list if activation else None
        options.append(
            CertificateOption(
                layout,
                checkin_list,
                checkin_list is None or checkin_list.pk in checked_in,
            )
        )
    return options
