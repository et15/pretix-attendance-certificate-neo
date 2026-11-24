from datetime import timedelta

import pytest
from django.contrib.messages import get_messages
from django.core import mail as djmail
from django.urls import reverse
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Checkin, CheckinList, Event, Order, OrderPosition
from pretix.base.signals import event_copy_data
from pretix.multidomain.urlreverse import eventreverse

from pretix_attendance_certificate_neo.models import (
    LayoutActivation,
    certificate_options,
)
from pretix_attendance_certificate_neo.signals import presale_order_info
from pretix_attendance_certificate_neo.views.presale import SELF_SERVICE_SETTING


def _new_event(organizer, slug="copy"):
    return Event.objects.create(
        organizer=organizer,
        name="Copy",
        slug=slug,
        date_from=now(),
        live=True,
        plugins="pretix_attendance_certificate_neo",
    )


@pytest.fixture
def passed_list(event):
    return CheckinList.objects.create(event=event, name="Passed the course")


@pytest.fixture
def passed_layout(event, organizer_layout, passed_list):
    """Organizer-wide "Passed" template, activated and tied to passed_list."""
    organizer_layout.active_events.add(event)
    LayoutActivation.objects.filter(layout=organizer_layout, event=event).update(
        checkin_list=passed_list
    )
    return organizer_layout


def _check_in(pos, checkin_list, successful=True):
    Checkin.objects.create(
        position=pos, list=checkin_list, datetime=now(), successful=successful
    )


def _kwargs(event, position):
    return {
        "organizer": event.organizer.slug,
        "event": event.slug,
        "position": position.pk,
    }


def _download(event, pos):
    return reverse(
        "plugins:pretix_attendance_certificate_neo:position.download",
        kwargs=_kwargs(event, pos),
    )


def _send(event, pos):
    return reverse(
        "plugins:pretix_attendance_certificate_neo:position.send",
        kwargs=_kwargs(event, pos),
    )


def _order_url(event, order):
    return f"/control/event/{event.organizer.slug}/{event.slug}/orders/{order.code}/"


def _messages(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


# --- eligibility -----------------------------------------------------------


@pytest.mark.django_db
def test_eligibility_follows_successful_checkins(
    event, order, pos, layout, passed_layout, passed_list
):
    with scopes_disabled():

        def eligible():
            return {o.layout.name: o.applicable for o in certificate_options(pos)}

        assert eligible() == {"Default": True, "Organizer-wide": False}
        _check_in(pos, passed_list, successful=False)
        assert eligible()["Organizer-wide"] is False
        _check_in(pos, passed_list)
        assert eligible() == {"Default": True, "Organizer-wide": True}


# --- control: order view buttons and enforcement ---------------------------


@pytest.mark.django_db
def test_order_view_disables_buttons_for_ineligible_templates(
    logged_in_client, event, order, pos, layout, passed_layout
):
    content = logged_in_client.get(_order_url(event, order)).content.decode()
    # Eligible: normal link; ineligible: no link, disabled send button.
    assert f"?layout={layout.pk}" in content
    assert f"?layout={passed_layout.pk}" not in content
    assert 'Not checked in on "Passed the course"' in content
    assert content.count("disabled") >= 2


@pytest.mark.django_db
def test_order_view_enables_buttons_once_checked_in(
    logged_in_client, event, order, pos, layout, passed_layout, passed_list
):
    with scopes_disabled():
        _check_in(pos, passed_list)
    content = logged_in_client.get(_order_url(event, order)).content.decode()
    assert f"?layout={passed_layout.pk}" in content
    assert 'Not checked in on "Passed the course"' not in content


@pytest.mark.django_db
def test_download_and_send_blocked_for_ineligible_template(
    logged_in_client, event, order, pos, layout, passed_layout
):
    djmail.outbox = []
    response = logged_in_client.get(_download(event, pos), {"layout": passed_layout.pk})
    assert response.status_code == 302
    assert any("not eligible" in m for m in _messages(response))

    response = logged_in_client.post(_send(event, pos), {"layout": passed_layout.pk})
    assert response.status_code == 302
    assert any("not eligible" in m for m in _messages(response))
    assert len(djmail.outbox) == 0


@pytest.mark.django_db
def test_download_and_send_work_for_eligible_template(
    logged_in_client, event, order, pos, layout, passed_layout, passed_list
):
    with scopes_disabled():
        _check_in(pos, passed_list)
    response = logged_in_client.get(_download(event, pos), {"layout": passed_layout.pk})
    assert response.status_code == 200
    djmail.outbox = []
    logged_in_client.post(_send(event, pos), {"layout": passed_layout.pk})
    assert len(djmail.outbox) == 1


@pytest.mark.django_db
def test_without_layout_param_the_only_eligible_template_is_used(
    logged_in_client, event, order, pos, layout, passed_layout
):
    # "Passed" is not eligible, so "Default" is the only candidate.
    response = logged_in_client.get(_download(event, pos))
    assert response.status_code == 200


@pytest.mark.django_db
def test_without_layout_param_several_eligible_asks_for_a_choice(
    logged_in_client, event, order, pos, layout, passed_layout, passed_list
):
    with scopes_disabled():
        _check_in(pos, passed_list)
    response = logged_in_client.get(_download(event, pos))
    assert response.status_code == 302
    assert any("pick" in m for m in _messages(response))


@pytest.mark.django_db
def test_not_eligible_for_any_template(
    logged_in_client, event, order, pos, passed_layout
):
    response = logged_in_client.get(_download(event, pos))
    assert response.status_code == 302
    assert any("not eligible for any" in m for m in _messages(response))


# --- control: assigning templates to check-in lists ------------------------


def _assign_url(event):
    return reverse(
        "plugins:pretix_attendance_certificate_neo:layouts.assign",
        kwargs={"organizer": event.organizer.slug, "event": event.slug},
    )


@pytest.mark.django_db
def test_assign_checkin_list_and_toggle_self_service(
    logged_in_client, event, layout, organizer_layout, passed_list
):
    with scopes_disabled():
        organizer_layout.active_events.add(event)
    response = logged_in_client.post(
        _assign_url(event),
        {
            f"list_{organizer_layout.pk}": passed_list.pk,
            f"list_{layout.pk}": "",
            "self_service": "on",
        },
    )
    assert response.status_code == 302
    with scopes_disabled():
        assert (
            LayoutActivation.objects.get(
                layout=organizer_layout, event=event
            ).checkin_list
            == passed_list
        )
        assert (
            LayoutActivation.objects.get(layout=layout, event=event).checkin_list
            is None
        )
    assert event.settings.get(SELF_SERVICE_SETTING, as_type=bool)

    # Untick -> switched off again and the assignment can be cleared.
    logged_in_client.post(_assign_url(event), {f"list_{organizer_layout.pk}": ""})
    with scopes_disabled():
        assert (
            LayoutActivation.objects.get(
                layout=organizer_layout, event=event
            ).checkin_list
            is None
        )
    event.settings.flush()
    assert not event.settings.get(SELF_SERVICE_SETTING, as_type=bool)


@pytest.mark.django_db
def test_assign_rejects_checkin_list_of_another_event(
    logged_in_client, event, layout, passed_list
):
    with scopes_disabled():
        other = _new_event(event.organizer, slug="other-ev")
        foreign = CheckinList.objects.create(event=other, name="Foreign")
    response = logged_in_client.post(
        _assign_url(event), {f"list_{layout.pk}": foreign.pk}
    )
    assert response.status_code == 302
    with scopes_disabled():
        assert not LayoutActivation.objects.filter(
            layout=layout, checkin_list=foreign
        ).exists()


@pytest.mark.django_db
def test_assign_requires_change_permission(client, event, layout):
    from pretix.base.models import Team, User

    with scopes_disabled():
        user = User.objects.create_user("viewer@dummy.dummy", "viewer")
        team = Team.objects.create(organizer=event.organizer, can_view_orders=True)
        team.members.add(user)
        team.limit_events.add(event)
    client.force_login(user)
    response = client.post(_assign_url(event), {f"list_{layout.pk}": ""})
    assert response.status_code == 403


@pytest.mark.django_db
def test_template_page_lists_assignment_form(
    logged_in_client, event, layout, passed_list
):
    url = reverse(
        "plugins:pretix_attendance_certificate_neo:layouts",
        kwargs={"organizer": event.organizer.slug, "event": event.slug},
    )
    content = logged_in_client.get(url).content.decode()
    assert "Passed the course" in content
    assert "Priority" not in content


# --- control: bulk send ----------------------------------------------------


def _bulk_url(event):
    return reverse(
        "plugins:pretix_attendance_certificate_neo:send",
        kwargs={"organizer": event.organizer.slug, "event": event.slug},
    )


@pytest.fixture
def pos_absent(order, item):
    return OrderPosition.objects.create(
        order=order,
        item=item,
        positionid=2,
        price=13,
        attendee_name_parts={"_legacy": "Absent Person"},
        attendee_email="absent@dummy.test",
    )


@pytest.fixture
def pos2(order, item):
    return OrderPosition.objects.create(
        order=order,
        item=item,
        price=13,
        attendee_name_parts={"_legacy": "Other Person"},
        attendee_email="other@dummy.test",
    )


@pytest.mark.django_db
def test_bulk_send_of_tied_template_only_goes_to_checked_in(
    logged_in_client, event, order, pos, pos2, layout, passed_layout, passed_list
):
    with scopes_disabled():
        _check_in(pos2, passed_list)
    djmail.outbox = []
    response = logged_in_client.post(
        _bulk_url(event),
        {
            "subject_0": "S",
            "message_0": "M",
            "action": "send",
            "layout": passed_layout.pk,
        },
    )
    assert response.status_code == 302
    assert [m.to for m in djmail.outbox] == [["other@dummy.test"]]


@pytest.mark.django_db
def test_bulk_send_of_untied_template_goes_to_everyone(
    logged_in_client, event, order, pos, pos2, layout, passed_layout, passed_list
):
    with scopes_disabled():
        _check_in(pos2, passed_list)
    djmail.outbox = []
    logged_in_client.post(
        _bulk_url(event),
        {"subject_0": "S", "message_0": "M", "action": "send", "layout": layout.pk},
    )
    assert len(djmail.outbox) == 2


@pytest.mark.django_db
def test_bulk_send_single_tied_template_is_restricted(
    logged_in_client, event, order, pos, pos2, layout, passed_list
):
    # Only one template available, but it is tied to a list -> still restricted.
    with scopes_disabled():
        LayoutActivation.objects.create(
            layout=layout, event=event, checkin_list=passed_list
        )
        _check_in(pos, passed_list)
    djmail.outbox = []
    logged_in_client.post(
        _bulk_url(event), {"subject_0": "S", "message_0": "M", "action": "send"}
    )
    assert [m.to for m in djmail.outbox] == [["attendee@dummy.test"]]


# --- customer self-service -------------------------------------------------


def _self_service_url(event, order, pos, layout, secret=None):
    return eventreverse(
        event,
        "plugins:pretix_attendance_certificate_neo:presale.download",
        kwargs={
            "order": order.code,
            "secret": secret or order.secret,
            "position": pos.positionid,
            "layout": layout.pk,
        },
    )


def _order_page(event, order):
    return eventreverse(
        event,
        "presale:event.order",
        kwargs={"order": order.code, "secret": order.secret},
    )


@pytest.fixture
def self_service(event, pos):
    """Self-service on, the event over and the attendee checked in somewhere:
    the baseline in which a download is allowed."""
    event.settings.set(SELF_SERVICE_SETTING, True)
    event.date_from = now() - timedelta(days=3)
    event.date_to = now() - timedelta(days=2)
    event.save()
    attendance = CheckinList.objects.create(event=event, name="Attendance")
    _check_in(pos, attendance)
    return attendance


@pytest.mark.django_db
def test_self_service_off_by_default(client, event, order, pos, layout):
    with scopes_disabled():
        attendance = CheckinList.objects.create(event=event, name="Attendance")
        _check_in(pos, attendance)
    event.date_from = now() - timedelta(days=3)
    event.date_to = now() - timedelta(days=2)
    event.save()
    assert client.get(_self_service_url(event, order, pos, layout)).status_code == 404
    assert (
        "Download certificate of attendance"
        not in client.get(_order_page(event, order)).content.decode()
    )


@pytest.mark.django_db
def test_self_service_download(client, event, order, pos, layout, self_service):
    response = client.get(_self_service_url(event, order, pos, layout))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert b"".join(response.streaming_content).startswith(b"%PDF")


@pytest.mark.django_db
def test_self_service_link_on_order_page(
    client, event, order, pos, layout, self_service
):
    content = client.get(_order_page(event, order)).content.decode()
    assert "Download certificate of attendance" in content
    assert _self_service_url(event, order, pos, layout) in content


@pytest.mark.django_db
def test_self_service_link_on_ticket_page_uses_position_secret(
    client, event, order, pos, layout, self_service
):
    url = eventreverse(
        event,
        "presale:event.order.position",
        kwargs={
            "order": order.code,
            "position": pos.positionid,
            "secret": pos.web_secret,
        },
    )
    content = client.get(url).content.decode()
    link = _self_service_url(event, order, pos, layout, secret=pos.web_secret)
    assert link in content
    assert client.get(link).status_code == 200


@pytest.mark.django_db
def test_self_service_wrong_secret(client, event, order, pos, layout, self_service):
    response = client.get(
        _self_service_url(event, order, pos, layout, secret="wrongsecret")
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_self_service_requires_paid_order(
    client, event, order, pos, layout, self_service
):
    with scopes_disabled():
        order.status = Order.STATUS_PENDING
        order.save()
    assert client.get(_self_service_url(event, order, pos, layout)).status_code == 404


@pytest.mark.django_db
def test_self_service_only_for_eligible_templates(
    client, event, order, pos, layout, passed_layout, passed_list, self_service
):
    blocked = _self_service_url(event, order, pos, passed_layout)
    assert client.get(blocked).status_code == 404
    content = client.get(_order_page(event, order)).content.decode()
    assert blocked not in content
    assert _self_service_url(event, order, pos, layout) in content

    with scopes_disabled():
        _check_in(pos, passed_list)
    assert client.get(blocked).status_code == 200
    assert blocked in client.get(_order_page(event, order)).content.decode()


@pytest.mark.django_db
def test_self_service_requires_the_event_to_be_over(
    client, event, order, pos, layout, self_service
):
    event.date_to = now() + timedelta(days=1)
    event.save()
    assert client.get(_self_service_url(event, order, pos, layout)).status_code == 404
    assert (
        "Download certificate"
        not in client.get(_order_page(event, order)).content.decode()
    )
    event.date_to = now() - timedelta(hours=1)
    event.save()
    assert client.get(_self_service_url(event, order, pos, layout)).status_code == 200


@pytest.mark.django_db
def test_self_service_without_end_date_unlocks_after_the_start_day(
    client, event, order, pos, layout, self_service
):
    event.date_to = None
    event.date_from = now()  # starts today: not over until the day is
    event.save()
    assert client.get(_self_service_url(event, order, pos, layout)).status_code == 404
    event.date_from = now() - timedelta(days=2)
    event.save()
    assert client.get(_self_service_url(event, order, pos, layout)).status_code == 200


@pytest.mark.django_db
def test_self_service_requires_the_attendee_to_have_been_checked_in(
    client, event, order, pos, pos_absent, layout, self_service
):
    # pos was checked in by the fixture, pos_absent was not.
    assert client.get(_self_service_url(event, order, pos, layout)).status_code == 200
    assert (
        client.get(_self_service_url(event, order, pos_absent, layout)).status_code
        == 404
    )
    content = client.get(_order_page(event, order)).content.decode()
    assert _self_service_url(event, order, pos_absent, layout) not in content


def _self_service_box(event, order, rf):
    """The plugin's "Certificate of attendance" box on the order page."""
    with scopes_disabled():
        return presale_order_info(sender=event, order=order, request=rf.get("/"))


@pytest.mark.django_db
def test_self_service_names_the_attendee_if_the_order_has_several_tickets(
    rf, event, order, pos, pos_absent, layout, self_service
):
    # Only pos has a certificate, but the order has two tickets: the box must
    # say whose certificate it is.
    box = _self_service_box(event, order, rf)
    assert _self_service_url(event, order, pos, layout) in box
    assert "Marco Acierno" in box
    assert "Absent Person" not in box


@pytest.mark.django_db
def test_self_service_omits_the_name_for_a_single_ticket(
    rf, event, order, pos, layout, self_service
):
    box = _self_service_box(event, order, rf)
    assert _self_service_url(event, order, pos, layout) in box
    assert "Marco Acierno" not in box


@pytest.mark.django_db
def test_self_service_ignores_failed_checkins(
    client, event, order, pos_absent, layout, self_service
):
    with scopes_disabled():
        _check_in(pos_absent, self_service, successful=False)
    assert (
        client.get(_self_service_url(event, order, pos_absent, layout)).status_code
        == 404
    )


@pytest.mark.django_db
def test_self_service_has_no_effect_on_admin_download(
    logged_in_client, event, order, pos_absent, layout
):
    # Admins can always issue a certificate; the presence rule is for customers.
    assert logged_in_client.get(_download(event, pos_absent)).status_code == 200


@pytest.mark.django_db
def test_self_service_hidden_when_not_eligible_for_anything(
    client, event, order, pos, passed_layout, self_service
):
    content = client.get(_order_page(event, order)).content.decode()
    assert "Certificate of attendance" not in content


# --- event copy ------------------------------------------------------------


@pytest.mark.django_db
def test_event_copy_keeps_checkin_list_assignment_and_self_service(
    event, passed_layout, passed_list, self_service
):
    with scopes_disabled():
        new_event = _new_event(event.organizer)
        # pretix copies the check-in lists itself before this signal fires.
        CheckinList.objects.create(event=new_event, name="Passed the course")
        event_copy_data.send(sender=new_event, other=event)

        copied = LayoutActivation.objects.get(layout=passed_layout, event=new_event)
        assert copied.checkin_list.event == new_event
        assert copied.checkin_list.name == "Passed the course"
    assert new_event.settings.get(SELF_SERVICE_SETTING, as_type=bool)


# --- deleting a tied check-in list deactivates the template ----------------


def _delete_list(client, event, checkin_list):
    # The real control view, so pretix' own deletion path is covered.
    return client.post(
        f"/control/event/{event.organizer.slug}/{event.slug}/checkinlists/{checkin_list.pk}/delete"
    )


def _available_names(event):
    from pretix_attendance_certificate_neo.models import available_layouts

    with scopes_disabled():
        return [layout.name for layout in available_layouts(event)]


@pytest.mark.django_db
def test_deleting_list_deactivates_event_owned_template(
    logged_in_client, event, layout, passed_list
):
    with scopes_disabled():
        LayoutActivation.objects.create(
            layout=layout, event=event, checkin_list=passed_list
        )
    assert _available_names(event) == ["Default"]

    assert _delete_list(logged_in_client, event, passed_list).status_code == 302

    # Not silently open to everyone: gone until someone reactivates it.
    assert _available_names(event) == []
    with scopes_disabled():
        activation = LayoutActivation.objects.get(layout=layout, event=event)
        assert activation.active is False
        assert activation.checkin_list is None
        assert event.logentry_set.filter(
            action_type="pretix.plugins.pretix_attendance_certificate_neo.layout.deactivated"
        ).exists()


@pytest.mark.django_db
def test_deleting_list_deactivates_organizer_template(
    logged_in_client, event, layout, passed_layout, passed_list
):
    assert _available_names(event) == ["Default", "Organizer-wide"]
    _delete_list(logged_in_client, event, passed_list)
    assert _available_names(event) == ["Default"]
    with scopes_disabled():
        assert not passed_layout.active_events.filter(pk=event.pk).exists()


@pytest.mark.django_db
def test_deleting_other_lists_changes_nothing(
    logged_in_client, event, layout, passed_layout, passed_list
):
    with scopes_disabled():
        unrelated = CheckinList.objects.create(event=event, name="Unrelated")
    _delete_list(logged_in_client, event, unrelated)
    assert _available_names(event) == ["Default", "Organizer-wide"]
    with scopes_disabled():
        assert (
            LayoutActivation.objects.get(layout=passed_layout, event=event).checkin_list
            == passed_list
        )


@pytest.mark.django_db
def test_deactivated_template_is_blocked_everywhere(
    logged_in_client, client, event, order, pos, layout, passed_list, self_service
):
    with scopes_disabled():
        LayoutActivation.objects.create(
            layout=layout, event=event, checkin_list=passed_list
        )
    _delete_list(logged_in_client, event, passed_list)

    response = logged_in_client.get(_download(event, pos), {"layout": layout.pk})
    assert response.status_code == 302 and any(
        "not available" in m for m in _messages(response)
    )
    assert client.get(_self_service_url(event, order, pos, layout)).status_code == 404


@pytest.mark.django_db
def test_deactivated_template_can_be_reactivated(
    logged_in_client, event, layout, passed_list
):
    with scopes_disabled():
        LayoutActivation.objects.create(
            layout=layout, event=event, checkin_list=passed_list
        )
    _delete_list(logged_in_client, event, passed_list)

    toggle = reverse(
        "plugins:pretix_attendance_certificate_neo:layouts.toggle",
        kwargs={
            "organizer": event.organizer.slug,
            "event": event.slug,
            "layout": layout.pk,
        },
    )
    page = reverse(
        "plugins:pretix_attendance_certificate_neo:layouts",
        kwargs={"organizer": event.organizer.slug, "event": event.slug},
    )
    assert "Deactivated" in logged_in_client.get(page).content.decode()
    assert logged_in_client.post(toggle).status_code == 302
    assert _available_names(event) == ["Default"]
    assert "Deactivated" not in logged_in_client.get(page).content.decode()
    # ... and it can be switched off by hand too.
    logged_in_client.post(toggle)
    assert _available_names(event) == []


@pytest.mark.django_db
def test_event_copy_deactivates_template_whose_list_is_missing(
    event, layout, passed_layout, passed_list
):
    with scopes_disabled():
        LayoutActivation.objects.update_or_create(
            layout=layout, event=event, defaults={"checkin_list": passed_list}
        )
        new_event = _new_event(event.organizer)
        # No "Passed the course" list in the new event.
        event_copy_data.send(sender=new_event, other=event)

        assert not passed_layout.active_events.filter(pk=new_event.pk).exists()
        copied = new_event.attendance_certificate_layouts.get()
        assert (
            LayoutActivation.objects.get(layout=copied, event=new_event).active is False
        )
