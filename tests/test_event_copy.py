import pytest
from django.core.files.base import ContentFile
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Event, Organizer
from pretix.base.signals import event_copy_data


def _new_event(organizer, slug="copy"):
    return Event.objects.create(
        organizer=organizer,
        name="Copy",
        slug=slug,
        date_from=now(),
        live=True,
        plugins="pretix_attendance_certificate_neo",
    )


@pytest.mark.django_db
def test_event_copy_copies_event_owned_layout(event, layout):
    with scopes_disabled():
        new_event = _new_event(event.organizer)
        event_copy_data.send(sender=new_event, other=event)

        copied = new_event.attendance_certificate_layouts.get()
        assert copied.pk != layout.pk
        assert copied.name == layout.name
        assert str(copied.mail_subject) == str(layout.mail_subject)
        assert str(copied.mail_text) == str(layout.mail_text)
        # The source event's own layout must be untouched.
        assert event.attendance_certificate_layouts.get().pk == layout.pk


@pytest.mark.django_db
def test_event_copy_copies_background_file_independently(event, layout):
    with scopes_disabled():
        layout.background.save("background.pdf", ContentFile(b"%PDF-fake"))
        old_background_name = layout.background.name

        new_event = _new_event(event.organizer)
        event_copy_data.send(sender=new_event, other=event)

        copied = new_event.attendance_certificate_layouts.get()
        assert copied.background.name
        assert copied.background.name != old_background_name


@pytest.mark.django_db
def test_event_copy_copies_organizer_layout_activation(event, organizer_layout):
    with scopes_disabled():
        organizer_layout.active_events.add(event)

        new_event = _new_event(event.organizer)
        event_copy_data.send(sender=new_event, other=event)

        assert organizer_layout.active_events.filter(pk=new_event.pk).exists()
        # Still activated for the original event too - not moved, copied.
        assert organizer_layout.active_events.filter(pk=event.pk).exists()


@pytest.mark.django_db
def test_event_copy_skips_activation_across_organizers(event, organizer_layout):
    with scopes_disabled():
        organizer_layout.active_events.add(event)
        other_organizer = Organizer.objects.create(name="Other", slug="other")
        new_event = _new_event(other_organizer, slug="other-event")

        event_copy_data.send(sender=new_event, other=event)

        assert not organizer_layout.active_events.filter(pk=new_event.pk).exists()


# Fields copy_to_event deliberately does not take over from the source. Any
# other field must arrive in the copy unchanged - so adding a field to the
# model makes this test fail until copy_to_event (used by the "copy to this
# event" button and by event copying) handles it, or it is listed here.
NOT_COPIED = {
    "id": "a new row",
    "event": "set to the target event",
    "organizer": "a copy is always event-owned",
    "name": "passed in explicitly",
    "background": "copied as a new, independent file (checked separately)",
    "active_events": "activations are handled by the caller",
}


@pytest.mark.django_db
def test_copy_to_event_takes_over_every_field(event, settings, tmp_path):
    from pretix_attendance_certificate_neo.models import AttendanceCertificateLayout

    settings.MEDIA_ROOT = tmp_path
    fields = {
        f.name
        for f in AttendanceCertificateLayout._meta.get_fields()
        if f.concrete or f.many_to_many
    }
    unknown = set(NOT_COPIED) - fields
    assert not unknown, f"NOT_COPIED lists fields that no longer exist: {unknown}"

    with scopes_disabled():
        source = AttendanceCertificateLayout.objects.create(
            organizer=event.organizer,
            name="Source",
            layout='[{"type": "textarea"}]',
            mail_subject={"en": "Subject", "de": "Betreff"},
            mail_text={"en": "Body", "de": "Text"},
        )
        source.background.save("background.pdf", ContentFile(b"%PDF-source"))
        copy = source.copy_to_event(event, name="Copy")

        for name in sorted(fields - set(NOT_COPIED)):
            field = AttendanceCertificateLayout._meta.get_field(name)
            assert field.value_from_object(copy) == field.value_from_object(source), (
                f'copy_to_event does not copy "{name}" - copy it there or add it '
                "to NOT_COPIED with a reason"
            )
            # A field still at its default proves nothing.
            if field.has_default():
                assert field.value_from_object(source) != field.get_default(), (
                    f'set "{name}" to a non-default value in this test'
                )

        assert (copy.event, copy.organizer, copy.name) == (event, None, "Copy")
        assert copy.background.name != source.background.name
        with copy.background.open("rb") as f:
            assert f.read() == b"%PDF-source"
