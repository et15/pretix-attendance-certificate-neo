from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, TemplateView, UpdateView, View
from pretix.control.permissions import EventPermissionRequiredMixin
from pretix.helpers.compat import CompatDeleteView

from pretix_attendance_certificate_neo.forms import OrganizerLayoutForm
from pretix_attendance_certificate_neo.models import (
    AttendanceCertificateLayout,
    LayoutActivation,
    available_layouts,
)
from pretix_attendance_certificate_neo.views.presale import SELF_SERVICE_SETTING


class EventLayoutFormMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["locales"] = self.request.event.settings.get("locales")
        kwargs["event"] = self.request.event
        return kwargs


class EventLayoutListView(EventPermissionRequiredMixin, TemplateView):
    template_name = "pretix_attendance_certificate_neo/event_layout_list.html"
    permission = ("can_change_event_settings", "can_view_orders")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event = self.request.event
        inactive = set(
            LayoutActivation.objects.filter(event=event, active=False).values_list(
                "layout_id", flat=True
            )
        )
        ctx["event_layouts"] = [
            {"layout": layout, "active": layout.pk not in inactive}
            for layout in event.attendance_certificate_layouts.all()
        ]
        ctx["organizer_layouts"] = [
            {
                "layout": layout,
                "active": layout.active_events.filter(pk=event.pk).exists(),
            }
            for layout in AttendanceCertificateLayout.objects.filter(
                organizer=event.organizer
            ).order_by("name")
        ]
        activations = {
            a.layout_id: a for a in LayoutActivation.objects.filter(event=event)
        }
        # Available templates (own + activated organizer-wide) with their
        # check-in list - edited together in one form.
        ctx["assignments"] = [
            {
                "layout": layout,
                "checkin_list_id": getattr(
                    activations.get(layout.pk), "checkin_list_id", None
                ),
            }
            for layout in available_layouts(event)
        ]
        ctx["checkin_lists"] = event.checkin_lists.all()
        ctx["self_service"] = event.settings.get(
            SELF_SERVICE_SETTING, as_type=bool, default=False
        )
        ctx["can_edit_organizer_layouts"] = self.request.user.has_organizer_permission(
            event.organizer, "can_change_organizer_settings", request=self.request
        )
        return ctx


def _require_change_permission(request):
    if not request.user.has_event_permission(
        request.organizer, request.event, "can_change_event_settings", request=request
    ):
        raise PermissionDenied(_("You do not have permission to view this content."))


class EventLayoutToggleView(EventPermissionRequiredMixin, TemplateView):
    permission = ("can_change_event_settings", "can_view_orders")

    def post(self, request, *args, **kwargs):
        _require_change_permission(request)
        layout = get_object_or_404(
            AttendanceCertificateLayout.visible_to(request.event),
            pk=kwargs["layout"],
        )
        if layout.organizer_id:
            now_active = not layout.active_events.filter(pk=request.event.pk).exists()
            if now_active:
                layout.active_events.add(request.event)
            else:
                layout.active_events.remove(request.event)
        else:
            # Event-owned templates are always available unless flagged off.
            activation, _created = LayoutActivation.objects.get_or_create(
                layout=layout, event=request.event
            )
            now_active = not activation.active
            activation.active = now_active
            activation.save(update_fields=["active"])
        if now_active:
            messages.success(
                request,
                _('The template "{name}" is now available for this event.').format(
                    name=layout.name
                ),
            )
        else:
            messages.success(
                request,
                _(
                    'The template "{name}" is no longer available for this event.'
                ).format(name=layout.name),
            )
        return redirect(
            reverse(
                "plugins:pretix_attendance_certificate_neo:layouts",
                kwargs={
                    "organizer": request.event.organizer.slug,
                    "event": request.event.slug,
                },
            )
        )


class EventLayoutCopyView(EventPermissionRequiredMixin, View):
    permission = "can_change_event_settings"

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        event = request.event
        source = get_object_or_404(
            AttendanceCertificateLayout, organizer=event.organizer, pk=kwargs["layout"]
        )
        name_format = gettext("{name} (copy)")
        max_length = AttendanceCertificateLayout._meta.get_field("name").max_length
        name = name_format.format(
            name=source.name[: max_length - len(name_format.format(name=""))]
        )
        layout = source.copy_to_event(event, name=name)

        activation = LayoutActivation.objects.filter(event=event, layout=source).first()
        if activation is not None:
            LayoutActivation.objects.create(
                event=event,
                layout=layout,
                checkin_list_id=activation.checkin_list_id,
                active=activation.active,
            )
        layout.log_action(
            "pretix.plugins.pretix_attendance_certificate_neo.layout.changed",
            user=request.user,
            data={"name": layout.name, "copied_from": source.pk},
        )
        messages.success(request, _("The template has been copied to this event."))
        return redirect(
            "plugins:pretix_attendance_certificate_neo:layouts",
            organizer=event.organizer.slug,
            event=event.slug,
        )


class EventLayoutAssignView(EventPermissionRequiredMixin, TemplateView):
    """Saves, for every available template, the check-in list it is tied to,
    plus the self-service switch."""

    permission = ("can_change_event_settings", "can_view_orders")

    def post(self, request, *args, **kwargs):
        _require_change_permission(request)
        event = request.event
        lists = {str(c.pk): c for c in event.checkin_lists.all()}
        for layout in available_layouts(event):
            raw_list = request.POST.get(f"list_{layout.pk}", "")
            if raw_list and raw_list not in lists:
                messages.error(request, _("Your changes could not be saved."))
                return redirect(self._back())
            LayoutActivation.objects.update_or_create(
                layout=layout,
                event=event,
                defaults={"checkin_list": lists.get(raw_list)},
            )
        event.settings.set(SELF_SERVICE_SETTING, bool(request.POST.get("self_service")))
        messages.success(request, _("Your changes have been saved."))
        return redirect(self._back())

    def _back(self):
        return reverse(
            "plugins:pretix_attendance_certificate_neo:layouts",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )


class EventLayoutCreateView(
    EventLayoutFormMixin, EventPermissionRequiredMixin, CreateView
):
    model = AttendanceCertificateLayout
    template_name = "pretix_attendance_certificate_neo/event_layout_edit.html"
    permission = "can_change_event_settings"
    form_class = OrganizerLayoutForm

    def get_success_url(self):
        return reverse(
            "plugins:pretix_attendance_certificate_neo:layouts",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )

    def form_valid(self, form):
        form.instance.event = self.request.event
        messages.success(self.request, _("The template has been created."))
        ret = super().form_valid(form)
        form.instance.log_action(
            "pretix.plugins.pretix_attendance_certificate_neo.layout.changed",
            user=self.request.user,
            data={"name": form.instance.name},
        )
        return ret

    def form_invalid(self, form):
        messages.error(self.request, _("Your changes could not be saved."))
        return super().form_invalid(form)


class EventLayoutUpdateView(
    EventLayoutFormMixin, EventPermissionRequiredMixin, UpdateView
):
    model = AttendanceCertificateLayout
    template_name = "pretix_attendance_certificate_neo/event_layout_edit.html"
    permission = "can_change_event_settings"
    form_class = OrganizerLayoutForm
    context_object_name = "layout"

    def get_object(self, queryset=None):
        return get_object_or_404(
            AttendanceCertificateLayout,
            event=self.request.event,
            pk=self.kwargs.get("layout"),
        )

    def get_success_url(self):
        return reverse(
            "plugins:pretix_attendance_certificate_neo:layouts",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )

    def form_valid(self, form):
        messages.success(self.request, _("Your changes have been saved."))
        ret = super().form_valid(form)
        if form.has_changed():
            form.instance.log_action(
                "pretix.plugins.pretix_attendance_certificate_neo.layout.changed",
                user=self.request.user,
                data={k: str(form.cleaned_data.get(k)) for k in form.changed_data},
            )
        return ret

    def form_invalid(self, form):
        messages.error(self.request, _("Your changes could not be saved."))
        return super().form_invalid(form)


class EventLayoutDeleteView(EventPermissionRequiredMixin, CompatDeleteView):
    model = AttendanceCertificateLayout
    template_name = "pretix_attendance_certificate_neo/event_layout_delete.html"
    permission = "can_change_event_settings"
    context_object_name = "layout"

    def get_object(self, queryset=None):
        return get_object_or_404(
            AttendanceCertificateLayout,
            event=self.request.event,
            pk=self.kwargs.get("layout"),
        )

    def get_success_url(self):
        return reverse(
            "plugins:pretix_attendance_certificate_neo:layouts",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.log_action(
            "pretix.plugins.pretix_attendance_certificate_neo.layout.deleted",
            user=self.request.user,
        )
        self.object.delete()
        messages.success(request, _("The template has been deleted."))
        return redirect(self.get_success_url())
