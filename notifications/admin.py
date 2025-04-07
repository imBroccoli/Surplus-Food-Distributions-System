from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "notification_type",
        "recipient",
        "title",
        "priority",
        "is_read",
        "created_at",
    )
    list_filter = ("notification_type", "priority", "is_read", "created_at")
    search_fields = ("recipient__email", "title", "message")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "read_at")

    fieldsets = (
        (None, {"fields": ("recipient", "notification_type", "title", "message")}),
        ("Status", {"fields": ("priority", "is_read", "created_at", "read_at")}),
        ("Link", {"fields": ("link",)}),
    )
