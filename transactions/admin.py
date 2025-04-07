from django.contrib import admin

from .models import DeliveryAssignment

# Register your models here.


@admin.register(DeliveryAssignment)
class DeliveryAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "transaction",
        "volunteer",
        "status",
        "pickup_window_start",
        "delivered_at",
    )
    list_filter = ("status", "assigned_at", "delivered_at")
    search_fields = ("volunteer__email", "transaction__request__listing__title")
    raw_id_fields = ("transaction", "volunteer")

    fieldsets = (
        (None, {"fields": ("transaction", "volunteer", "status")}),
        (
            "Timing",
            {
                "fields": (
                    "pickup_window_start",
                    "pickup_window_end",
                    "delivery_window_start",
                    "delivery_window_end",
                    "assigned_at",
                    "picked_up_at",
                    "delivered_at",
                )
            },
        ),
        (
            "Details",
            {
                "fields": (
                    "estimated_weight",
                    "distance",
                    "pickup_notes",
                    "delivery_notes",
                )
            },
        ),
    )
