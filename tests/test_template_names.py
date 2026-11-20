"""Template names must be unique within an event (its own templates plus the
organizer-wide ones activated for it), ignoring case and surrounding
whitespace - otherwise attendees and admins cannot tell certificates apart."""

import pytest
from django.urls import reverse
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Event

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
def test_create_rejects_name_of_other_event_template(
    logged_in_client, event, layout, name
):
    response = logged_in_client.post(_event_url("layouts.add", event), {"name": name})
    assert response.status_code == 200
    assert "name" in _form_errors(response)
    assert AttendanceCertificateLayout.objects.filter(event=event).count() == 1


@pytest.mark.django_db
def test_create_rejects_name_of_deactivated_event_template(
    logged_in_client, event, layout
):
    # Deactivated templates count too, else reactivating one would clash.
    LayoutActivation.objects.create(event=event, layout=layout, active=False)
    response = logged_in_client.post(
        _event_url("layouts.add", event), {"name": layout.name}
    )
    assert response.status_code == 200
    assert "name" in _form_errors(response)


@pytest.mark.django_db
def test_same_name_in_different_events_is_allowed(logged_in_client, event, layout):
    with scopes_disabled():
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
def test_saving_event_template_with_unchanged_name_is_allowed(
    logged_in_client, event, layout
):
    response = logged_in_client.post(
        _event_url("layouts.update", event, layout=layout.pk), {"name": "Default"}
    )
    assert response.status_code == 302


# --- Activating organizer-wide templates -----------------------------------


@pytest.mark.django_db
def test_activation_is_refused_if_event_template_has_the_name(
    logged_in_client, event, organizer_layout
):
    AttendanceCertificateLayout.objects.create(
        event=event, name=organizer_layout.name.upper()
    )
    response = logged_in_client.post(
        _event_url("layouts.toggle", event, layout=organizer_layout.pk), follow=True
    )
    assert response.status_code == 200
    assert not organizer_layout.active_events.filter(pk=event.pk).exists()
    assert "cannot be activated" in response.rendered_content


@pytest.mark.django_db
def test_activation_is_refused_if_activated_organizer_template_has_the_name(
    logged_in_client, event, organizer_layout
):
    twin = AttendanceCertificateLayout.objects.create(
        organizer=event.organizer, name=organizer_layout.name
    )
    organizer_layout.active_events.add(event)
    logged_in_client.post(_event_url("layouts.toggle", event, layout=twin.pk))
    assert not twin.active_events.filter(pk=event.pk).exists()
    assert _names(event) == [organizer_layout.name]


@pytest.mark.django_db
def test_deactivation_is_never_blocked_by_a_name_clash(
    logged_in_client, event, organizer_layout
):
    # Data from before the rule existed may already clash; switching one of
    # the templates off must still work.
    organizer_layout.active_events.add(event)
    AttendanceCertificateLayout.objects.create(event=event, name=organizer_layout.name)
    logged_in_client.post(
        _event_url("layouts.toggle", event, layout=organizer_layout.pk)
    )
    assert not organizer_layout.active_events.filter(pk=event.pk).exists()


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
    assert result["status"] == "error"
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
    assert result["status"] == "error"
    organizer_layout.refresh_from_db()
    assert organizer_layout.name == "Organizer-wide"


@pytest.mark.django_db
def test_editor_save_with_unchanged_name_works(logged_in_client, event, layout):
    result = _editor_save(logged_in_client, event, layout, layout.name)
    assert result["status"] == "ok"
    layout.refresh_from_db()
    assert layout.layout == "[]"


# --- Copying organizer-wide templates to the event -------------------------


@pytest.mark.django_db
def test_copy_replaces_activated_organizer_template_in_this_event_only(
    logged_in_client, event, organizer_layout
):
    with scopes_disabled():
        other = _other_event(event)
    organizer_layout.active_events.add(event, other)
    logged_in_client.post(_event_url("layouts.copy", event, layout=organizer_layout.pk))

    assert not organizer_layout.active_events.filter(pk=event.pk).exists()
    assert organizer_layout.active_events.filter(pk=other.pk).exists()
    with scopes_disabled():
        available = list(available_layouts(event))
    assert [(lay.name, lay.event_id) for lay in available] == [
        (organizer_layout.name, event.pk)
    ]


@pytest.mark.django_db
def test_copy_of_inactive_organizer_template(logged_in_client, event, organizer_layout):
    logged_in_client.post(_event_url("layouts.copy", event, layout=organizer_layout.pk))
    assert not organizer_layout.active_events.filter(pk=event.pk).exists()
    copy = AttendanceCertificateLayout.objects.get(event=event)
    # Event templates are available without an activation row.
    assert not LayoutActivation.objects.filter(layout=copy).exists()
    assert _names(event) == [organizer_layout.name]


@pytest.mark.django_db
def test_copy_without_background(logged_in_client, event, organizer_layout):
    assert not organizer_layout.background
    response = logged_in_client.post(
        _event_url("layouts.copy", event, layout=organizer_layout.pk)
    )
    assert response.status_code == 302
    assert not AttendanceCertificateLayout.objects.get(event=event).background


@pytest.mark.django_db
def test_copying_twice_is_refused(logged_in_client, event, organizer_layout):
    url = _event_url("layouts.copy", event, layout=organizer_layout.pk)
    logged_in_client.post(url)
    response = logged_in_client.post(url, follow=True)
    assert "cannot be copied" in response.rendered_content
    assert AttendanceCertificateLayout.objects.filter(event=event).count() == 1


@pytest.mark.django_db
def test_copy_refused_if_event_template_has_the_name(
    logged_in_client, event, organizer_layout
):
    AttendanceCertificateLayout.objects.create(
        event=event, name=f" {organizer_layout.name.lower()} "
    )
    organizer_layout.active_events.add(event)
    logged_in_client.post(_event_url("layouts.copy", event, layout=organizer_layout.pk))
    assert AttendanceCertificateLayout.objects.filter(event=event).count() == 1
    # A refused copy leaves the organizer-wide template active.
    assert organizer_layout.active_events.filter(pk=event.pk).exists()


@pytest.mark.django_db
def test_copy_rejects_template_of_another_event_of_the_organizer(
    logged_in_client, event
):
    with scopes_disabled():
        other = _other_event(event)
        foreign = AttendanceCertificateLayout.objects.create(event=other, name="X")
    response = logged_in_client.post(
        _event_url("layouts.copy", event, layout=foreign.pk)
    )
    assert response.status_code == 404
    assert not AttendanceCertificateLayout.objects.filter(event=event).exists()


@pytest.mark.django_db
def test_failed_copy_changes_nothing(
    logged_in_client, event, organizer_layout, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    organizer_layout.active_events.add(event)
    AttendanceCertificateLayout.objects.filter(pk=organizer_layout.pk).update(
        background="pub/missing/background.pdf"
    )
    with pytest.raises(FileNotFoundError):
        logged_in_client.post(
            _event_url("layouts.copy", event, layout=organizer_layout.pk)
        )
    assert not AttendanceCertificateLayout.objects.filter(event=event).exists()
    assert organizer_layout.active_events.filter(pk=event.pk).exists()
