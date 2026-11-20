"""Names of the active templates of an event (its own, not deactivated ones,
plus the organizer-wide ones activated for it) must be unique, ignoring case
and surrounding whitespace - otherwise attendees and admins cannot tell
certificates apart. Deactivated templates may share a name; the check happens
when one is activated."""

import json
import re

import pytest
from django.core.files.storage import FileSystemStorage
from django.urls import reverse
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Event, LogEntry

from pretix_attendance_certificate_neo.models import (
    AttendanceCertificateLayout,
    LayoutActivation,
    available_layouts,
)

URL_PREFIX = "plugins:pretix_attendance_certificate_neo:"


@pytest.fixture(autouse=True)
def _no_scopes():
    # For the direct ORM setup/checks; requests still run in pretix's own
    # organizer scope.
    with scopes_disabled():
        yield


def _event_url(name, event, **kwargs):
    return reverse(
        URL_PREFIX + name,
        kwargs={"organizer": event.organizer.slug, "event": event.slug, **kwargs},
    )


def _org_update_url(event, layout):
    return reverse(
        URL_PREFIX + "organizer.layouts.update",
        kwargs={"organizer": event.organizer.slug, "layout": layout.pk},
    )


def _org_add_url(event):
    return reverse(
        URL_PREFIX + "organizer.layouts.add",
        kwargs={"organizer": event.organizer.slug},
    )


def _other_event(event, slug="other"):
    return Event.objects.create(
        organizer=event.organizer,
        name="Other",
        slug=slug,
        date_from=now(),
        plugins="pretix_attendance_certificate_neo",
    )


def _names(event):
    with scopes_disabled():
        return sorted(layout.name for layout in available_layouts(event))


def _form_errors(response):
    return response.context["form"].errors


def _deactivate(layout, event):
    LayoutActivation.objects.update_or_create(
        layout=layout, event=event, defaults={"active": False}
    )


def _toggle(client, event, layout, **kwargs):
    return client.post(_event_url("layouts.toggle", event, layout=layout.pk), **kwargs)


def _copy(client, event, layout, **kwargs):
    return client.post(_event_url("layouts.copy", event, layout=layout.pk), **kwargs)


# --- Creating and renaming event templates ---------------------------------


@pytest.mark.django_db
def test_create_rejects_name_of_activated_organizer_template(
    logged_in_client, event, organizer_layout
):
    organizer_layout.active_events.add(event)
    response = logged_in_client.post(
        _event_url("layouts.add", event), {"name": organizer_layout.name}
    )
    assert response.status_code == 200
    assert "name" in _form_errors(response)
    assert not AttendanceCertificateLayout.objects.filter(event=event).exists()


@pytest.mark.django_db
def test_create_allows_name_of_inactive_organizer_template(
    logged_in_client, event, organizer_layout
):
    response = logged_in_client.post(
        _event_url("layouts.add", event), {"name": organizer_layout.name}
    )
    assert response.status_code == 302
    assert AttendanceCertificateLayout.objects.filter(
        event=event, name=organizer_layout.name
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["Default", "default", "  DEFAULT  "])
def test_create_rejects_name_of_active_event_template(
    logged_in_client, event, layout, name
):
    response = logged_in_client.post(_event_url("layouts.add", event), {"name": name})
    assert response.status_code == 200
    assert "name" in _form_errors(response)
    assert AttendanceCertificateLayout.objects.filter(event=event).count() == 1


@pytest.mark.django_db
def test_create_allows_name_of_deactivated_event_template(
    logged_in_client, event, layout
):
    _deactivate(layout, event)
    response = logged_in_client.post(
        _event_url("layouts.add", event), {"name": layout.name}
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_same_name_in_different_events_is_allowed(logged_in_client, event, layout):
    other = _other_event(event)
    AttendanceCertificateLayout.objects.create(event=other, name="Second")
    response = logged_in_client.post(
        _event_url("layouts.add", event), {"name": "Second"}
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_rename_event_template_to_activated_organizer_name_is_rejected(
    logged_in_client, event, layout, organizer_layout
):
    organizer_layout.active_events.add(event)
    response = logged_in_client.post(
        _event_url("layouts.update", event, layout=layout.pk),
        {"name": organizer_layout.name},
    )
    assert response.status_code == 200
    assert "name" in _form_errors(response)
    layout.refresh_from_db()
    assert layout.name == "Default"


@pytest.mark.django_db
def test_rename_of_deactivated_event_template_is_not_restricted(
    logged_in_client, event, layout, organizer_layout
):
    organizer_layout.active_events.add(event)
    _deactivate(layout, event)
    response = logged_in_client.post(
        _event_url("layouts.update", event, layout=layout.pk),
        {"name": organizer_layout.name},
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_saving_event_template_with_unchanged_name_is_allowed(
    logged_in_client, event, layout
):
    response = logged_in_client.post(
        _event_url("layouts.update", event, layout=layout.pk), {"name": "Default"}
    )
    assert response.status_code == 302


# --- Activating templates ----------------------------------------------------


@pytest.mark.django_db
def test_organizer_activation_refused_if_active_event_template_has_the_name(
    logged_in_client, event, organizer_layout
):
    AttendanceCertificateLayout.objects.create(
        event=event, name=organizer_layout.name.upper()
    )
    response = _toggle(logged_in_client, event, organizer_layout, follow=True)
    assert response.status_code == 200
    assert not organizer_layout.active_events.filter(pk=event.pk).exists()
    assert "cannot be activated" in response.rendered_content


@pytest.mark.django_db
def test_organizer_activation_allowed_if_same_named_event_template_is_off(
    logged_in_client, event, organizer_layout
):
    twin = AttendanceCertificateLayout.objects.create(
        event=event, name=organizer_layout.name
    )
    _deactivate(twin, event)
    _toggle(logged_in_client, event, organizer_layout)
    assert organizer_layout.active_events.filter(pk=event.pk).exists()


@pytest.mark.django_db
def test_organizer_activation_refused_if_activated_organizer_template_has_the_name(
    logged_in_client, event, organizer_layout
):
    twin = AttendanceCertificateLayout.objects.create(
        organizer=event.organizer, name=organizer_layout.name
    )
    organizer_layout.active_events.add(event)
    _toggle(logged_in_client, event, twin)
    assert not twin.active_events.filter(pk=event.pk).exists()
    assert _names(event) == [organizer_layout.name]


@pytest.mark.django_db
def test_event_template_reactivation_refused_if_name_is_taken(
    logged_in_client, event, layout, organizer_layout
):
    _deactivate(layout, event)
    organizer_layout.name = layout.name
    organizer_layout.save()
    organizer_layout.active_events.add(event)
    response = _toggle(logged_in_client, event, layout, follow=True)
    assert "cannot be activated" in response.rendered_content
    assert not LayoutActivation.objects.get(layout=layout, event=event).active


@pytest.mark.django_db
def test_event_template_reactivation_works_without_clash(
    logged_in_client, event, layout
):
    _deactivate(layout, event)
    _toggle(logged_in_client, event, layout)
    assert LayoutActivation.objects.get(layout=layout, event=event).active


@pytest.mark.django_db
def test_deactivation_is_never_blocked_by_a_name_clash(
    logged_in_client, event, organizer_layout
):
    # Data from before the rule existed may already clash; switching one of
    # the templates off must still work.
    organizer_layout.active_events.add(event)
    AttendanceCertificateLayout.objects.create(event=event, name=organizer_layout.name)
    _toggle(logged_in_client, event, organizer_layout)
    assert not organizer_layout.active_events.filter(pk=event.pk).exists()


@pytest.mark.django_db
def test_toggling_is_logged_on_the_event(logged_in_client, event, organizer_layout):
    _toggle(logged_in_client, event, organizer_layout)
    _toggle(logged_in_client, event, organizer_layout)
    entries = LogEntry.objects.filter(
        event=event,
        action_type__in=[
            "pretix.plugins.pretix_attendance_certificate_neo.layout.enabled",
            "pretix.plugins.pretix_attendance_certificate_neo.layout.disabled",
        ],
    ).order_by("pk")
    assert [e.action_type.rsplit(".", 1)[1] for e in entries] == [
        "enabled",
        "disabled",
    ]
    assert [str(e.display()) for e in entries] == [
        'The certificate template "Organizer-wide" was activated for this event.',
        'The certificate template "Organizer-wide" was deactivated for this event.',
    ]


@pytest.mark.django_db
def test_refused_activation_is_not_logged(logged_in_client, event, organizer_layout):
    AttendanceCertificateLayout.objects.create(event=event, name=organizer_layout.name)
    _toggle(logged_in_client, event, organizer_layout)
    assert not LogEntry.objects.filter(
        action_type="pretix.plugins.pretix_attendance_certificate_neo.layout.enabled"
    ).exists()


# --- Renaming organizer-wide templates -------------------------------------


@pytest.mark.django_db
def test_organizer_rename_rejected_if_it_clashes_in_an_activated_event(
    organizer_client, event, layout, organizer_layout
):
    organizer_layout.active_events.add(event)
    response = organizer_client.post(
        _org_update_url(event, organizer_layout), {"name": layout.name}
    )
    assert response.status_code == 200
    errors = _form_errors(response)["name"]
    assert str(event.name) in errors[0]
    organizer_layout.refresh_from_db()
    assert organizer_layout.name == "Organizer-wide"


@pytest.mark.django_db
def test_organizer_rename_allowed_if_template_inactive_where_name_is_used(
    organizer_client, event, layout, organizer_layout
):
    response = organizer_client.post(
        _org_update_url(event, organizer_layout), {"name": layout.name}
    )
    assert response.status_code == 302
    organizer_layout.refresh_from_db()
    assert organizer_layout.name == layout.name


@pytest.mark.django_db
def test_organizer_rename_allowed_if_same_named_event_template_is_off(
    organizer_client, event, layout, organizer_layout
):
    organizer_layout.active_events.add(event)
    _deactivate(layout, event)
    response = organizer_client.post(
        _org_update_url(event, organizer_layout), {"name": layout.name}
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_organizer_create_is_not_restricted_by_event_names(
    organizer_client, event, layout
):
    # A new organizer-wide template is not active anywhere yet.
    response = organizer_client.post(_org_add_url(event), {"name": layout.name})
    assert response.status_code == 302


# --- Renaming in the layout editor -----------------------------------------


def _editor_save(client, event, layout, name):
    return client.post(
        _event_url("edit", event, layout=layout.pk), {"data": "[]", "name": name}
    ).json()


@pytest.mark.django_db
def test_editor_rename_of_event_template_to_taken_name_is_rejected(
    logged_in_client, event, layout, organizer_layout
):
    organizer_layout.active_events.add(event)
    result = _editor_save(logged_in_client, event, layout, organizer_layout.name)
    # The editor script recognizes this code and lets the user fix the name
    # without reloading the page.
    assert result["status"] == "error"
    assert result["error_code"] == "name_taken"
    layout.refresh_from_db()
    assert layout.name == "Default"
    # Nothing else of the save went through either.
    assert layout.layout != "[]"


@pytest.mark.django_db
def test_editor_rename_of_organizer_template_to_taken_name_is_rejected(
    organizer_client, event, layout, organizer_layout
):
    organizer_layout.active_events.add(event)
    result = _editor_save(organizer_client, event, organizer_layout, " default ")
    assert result["error_code"] == "name_taken"
    organizer_layout.refresh_from_db()
    assert organizer_layout.name == "Organizer-wide"


@pytest.mark.django_db
def test_editor_save_with_unchanged_name_works(logged_in_client, event, layout):
    result = _editor_save(logged_in_client, event, layout, layout.name)
    assert result["status"] == "ok"
    layout.refresh_from_db()
    assert layout.layout == "[]"


def _name_check(response):
    match = re.search(
        r'<script id="attendance-certificate-name-check" '
        r'type="application/json">(.*?)</script>',
        response.rendered_content,
        re.S,
    )
    assert match, "name check data missing from the editor page"
    return json.loads(match.group(1))


@pytest.mark.django_db
def test_editor_page_knows_the_taken_names(
    logged_in_client, event, layout, organizer_layout
):
    organizer_layout.name = "  Teilnahme  "
    organizer_layout.save()
    organizer_layout.active_events.add(event)
    response = logged_in_client.get(_event_url("edit", event, layout=layout.pk))
    assert _name_check(response)["taken"] == ["teilnahme"]
    assert "editor_name_check.js" in response.rendered_content


@pytest.mark.django_db
def test_editor_page_of_deactivated_template_has_no_taken_names(
    logged_in_client, event, layout, organizer_layout
):
    organizer_layout.active_events.add(event)
    _deactivate(layout, event)
    response = logged_in_client.get(_event_url("edit", event, layout=layout.pk))
    assert _name_check(response)["taken"] == []


@pytest.mark.django_db
def test_editor_page_of_organizer_template_lists_names_of_activated_events(
    organizer_client, event, layout, organizer_layout
):
    other = _other_event(event)
    AttendanceCertificateLayout.objects.create(event=other, name="Elsewhere")
    organizer_layout.active_events.add(event)
    response = organizer_client.get(
        _event_url("edit", event, layout=organizer_layout.pk)
    )
    assert _name_check(response)["taken"] == ["default"]


# --- Copying organizer-wide templates to the event -------------------------


@pytest.mark.django_db
def test_copy_starts_deactivated_and_keeps_the_original_active(
    logged_in_client, event, organizer_layout
):
    checkin_list = event.checkin_lists.create(name="Passed")
    LayoutActivation.objects.create(
        event=event, layout=organizer_layout, checkin_list=checkin_list
    )
    response = _copy(logged_in_client, event, organizer_layout, follow=True)
    assert "The copy is deactivated" in response.rendered_content

    copy = AttendanceCertificateLayout.objects.get(event=event)
    activation = LayoutActivation.objects.get(layout=copy, event=event)
    assert not activation.active
    assert activation.checkin_list == checkin_list
    assert organizer_layout.active_events.filter(pk=event.pk).exists()
    with scopes_disabled():
        assert [lay.pk for lay in available_layouts(event)] == [organizer_layout.pk]


@pytest.mark.django_db
def test_copy_of_inactive_organizer_template(logged_in_client, event, organizer_layout):
    _copy(logged_in_client, event, organizer_layout)
    assert not organizer_layout.active_events.filter(pk=event.pk).exists()
    copy = AttendanceCertificateLayout.objects.get(event=event)
    activation = LayoutActivation.objects.get(layout=copy, event=event)
    assert not activation.active
    assert activation.checkin_list is None
    assert _names(event) == []


@pytest.mark.django_db
def test_activating_the_copy_needs_the_original_off_first(
    logged_in_client, event, organizer_layout
):
    organizer_layout.active_events.add(event)
    _copy(logged_in_client, event, organizer_layout)
    copy = AttendanceCertificateLayout.objects.get(event=event)

    _toggle(logged_in_client, event, copy)
    assert _names(event) == [organizer_layout.name]
    assert not LayoutActivation.objects.get(layout=copy).active

    _toggle(logged_in_client, event, organizer_layout)
    _toggle(logged_in_client, event, copy)
    with scopes_disabled():
        assert [lay.pk for lay in available_layouts(event)] == [copy.pk]


@pytest.mark.django_db
def test_copy_without_background(logged_in_client, event, organizer_layout):
    assert not organizer_layout.background
    response = _copy(logged_in_client, event, organizer_layout)
    assert response.status_code == 302
    assert not AttendanceCertificateLayout.objects.get(event=event).background


@pytest.mark.django_db
def test_copying_twice_gives_two_deactivated_copies(
    logged_in_client, event, organizer_layout
):
    _copy(logged_in_client, event, organizer_layout)
    _copy(logged_in_client, event, organizer_layout)
    assert not LayoutActivation.objects.filter(
        event=event, layout__event=event, active=True
    ).exists()
    assert AttendanceCertificateLayout.objects.filter(event=event).count() == 2


@pytest.mark.django_db
def test_copy_rejects_template_of_another_event_of_the_organizer(
    logged_in_client, event
):
    other = _other_event(event)
    foreign = AttendanceCertificateLayout.objects.create(event=other, name="X")
    response = _copy(logged_in_client, event, foreign)
    assert response.status_code == 404
    assert not AttendanceCertificateLayout.objects.filter(event=event).exists()


@pytest.mark.django_db
def test_copy_is_logged(logged_in_client, event, organizer_layout):
    _copy(logged_in_client, event, organizer_layout)
    copy = AttendanceCertificateLayout.objects.get(event=event)
    entry = LogEntry.objects.get(
        action_type="pretix.plugins.pretix_attendance_certificate_neo.layout.copied"
    )
    assert entry.object_id == copy.pk
    assert entry.event_id == event.pk
    assert str(entry.display()) == (
        'The certificate template "Organizer-wide" was created as a copy of the '
        'organizer-wide template "Organizer-wide".'
    )


def _break_background(layout):
    AttendanceCertificateLayout.objects.filter(pk=layout.pk).update(
        background="pub/missing/background.pdf"
    )


@pytest.mark.django_db
def test_copy_with_missing_background_shows_an_error(
    logged_in_client, event, organizer_layout, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    organizer_layout.active_events.add(event)
    _break_background(organizer_layout)
    response = _copy(logged_in_client, event, organizer_layout, follow=True)
    assert response.status_code == 200
    assert "background PDF is missing" in response.rendered_content
    # No copy without its background, and nothing else changed.
    assert not AttendanceCertificateLayout.objects.filter(event=event).exists()
    assert organizer_layout.active_events.filter(pk=event.pk).exists()
    assert not LogEntry.objects.filter(action_type__endswith="layout.copied").exists()


@pytest.mark.django_db
def test_copy_with_background_vanishing_during_the_copy(
    logged_in_client, event, organizer_layout, settings, tmp_path, monkeypatch
):
    settings.MEDIA_ROOT = tmp_path
    _break_background(organizer_layout)
    organizer_layout.refresh_from_db()
    # The existence check passes, the file is gone when it is read.
    monkeypatch.setattr(FileSystemStorage, "exists", lambda self, name: True)
    response = _copy(logged_in_client, event, organizer_layout, follow=True)
    assert "background PDF is missing" in response.rendered_content
    assert not AttendanceCertificateLayout.objects.filter(event=event).exists()
