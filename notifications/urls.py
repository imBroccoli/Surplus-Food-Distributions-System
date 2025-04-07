from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="notification_list"),
    path("mark-read/<int:notification_id>/", views.mark_as_read, name="mark_as_read"),
    path("mark-all-read/", views.mark_all_as_read, name="mark_all_as_read"),
    path("unread-count/", views.get_unread_count, name="unread_count"),
    path("recent/", views.get_recent_notifications, name="recent_notifications"),
    path(
        "settings/", views.notification_settings, name="settings"
    ),  # Added settings URL
    path("clear-messages/", views.clear_messages, name="clear_messages"),
]
