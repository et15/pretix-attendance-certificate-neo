from django.urls import re_path

from .views.editor import EditorView
from .views.emails import SendCertificateEmailView
from .views.event_templates import (
    EventLayoutAssignView,
    EventLayoutCopyView,
    EventLayoutCreateView,
    EventLayoutDeleteView,
    EventLayoutListView,
    EventLayoutToggleView,
    EventLayoutUpdateView,
)
from .views.organizer import (
    OrganizerLayoutCreateView,
    OrganizerLayoutDeleteView,
    OrganizerLayoutListView,
    OrganizerLayoutUpdateView,
)
from .views.positions import DownloadCertificateView, SendCertificateView
from .views.presale import SelfServiceDownloadView
from .views.signing import SigningCertificateDownloadView, SigningView

urlpatterns = [
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/editor/layout/(?P<layout>\d+)/?$",
        EditorView.as_view(),
        name="edit",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/$",
        EventLayoutListView.as_view(),
        name="layouts",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/templates/add$",
        EventLayoutCreateView.as_view(),
        name="layouts.add",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/templates/(?P<layout>\d+)/delete$",
        EventLayoutDeleteView.as_view(),
        name="layouts.delete",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/templates/(?P<layout>\d+)/edit$",
        EventLayoutUpdateView.as_view(),
        name="layouts.update",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/templates/(?P<layout>\d+)/toggle$",
        EventLayoutToggleView.as_view(),
        name="layouts.toggle",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/templates/(?P<layout>\d+)/copy$",
        EventLayoutCopyView.as_view(),
        name="layouts.copy",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/templates/assign$",
        EventLayoutAssignView.as_view(),
        name="layouts.assign",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/attendance-certificate/templates/$",
        OrganizerLayoutListView.as_view(),
        name="organizer.layouts",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/attendance-certificate/templates/add$",
        OrganizerLayoutCreateView.as_view(),
        name="organizer.layouts.add",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/attendance-certificate/templates/(?P<layout>\d+)/edit$",
        OrganizerLayoutUpdateView.as_view(),
        name="organizer.layouts.update",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/attendance-certificate/templates/(?P<layout>\d+)/delete$",
        OrganizerLayoutDeleteView.as_view(),
        name="organizer.layouts.delete",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/attendance-certificate/signing/$",
        SigningView.as_view(),
        name="organizer.signing",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/attendance-certificate/signing/certificate\.pem$",
        SigningCertificateDownloadView.as_view(),
        name="organizer.signing.certificate",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/sendmail/attendance-certificates/$",
        SendCertificateEmailView.as_view(),
        name="send",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/position/(?P<position>\d+)/download$",
        DownloadCertificateView.as_view(),
        name="position.download",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/position/(?P<position>\d+)/send$",
        SendCertificateView.as_view(),
        name="position.send",
    ),
]

# Customer-facing (presale) URLs.
event_patterns = [
    re_path(
        r"^attendance-certificate/(?P<order>[^/]+)/(?P<secret>[A-Za-z0-9]+)/(?P<position>\d+)/(?P<layout>\d+)/download$",
        SelfServiceDownloadView.as_view(),
        name="presale.download",
    ),
]
