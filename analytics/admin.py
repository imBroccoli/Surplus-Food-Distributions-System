from django.contrib import admin

from .models import (
    DailyAnalytics,
    ImpactMetrics,
    Report,
    SystemMetrics,
    UserActivityLog,
)


@admin.register(ImpactMetrics)
class ImpactMetricsAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "food_redistributed_kg",
        "co2_emissions_saved",
        "meals_provided",
        "monetary_value_saved",
    )
    list_filter = ("date",)
    date_hierarchy = "date"
    readonly_fields = (
        "food_redistributed_kg",
        "co2_emissions_saved",
        "meals_provided",
        "monetary_value_saved",
    )


@admin.register(DailyAnalytics)
class DailyAnalyticsAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "user",
        "listing",
        "requests_received",
        "requests_fulfilled",
        "food_saved_kg",
    )
    list_filter = ("date", "user")
    search_fields = ("user__email", "listing__title")
    date_hierarchy = "date"


@admin.register(SystemMetrics)
class SystemMetricsAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "active_users",
        "new_listings_count",
        "request_count",
        "transaction_completion_rate",
        "avg_rating",
    )
    list_filter = ("date",)
    date_hierarchy = "date"
    fieldsets = (
        (
            "User Activity",
            {
                "fields": (
                    "active_users",
                    "new_users",
                    "business_users_active",
                    "nonprofit_users_active",
                    "volunteer_users_active",
                    "consumer_users_active",
                )
            },
        ),
        (
            "Platform Performance",
            {
                "fields": (
                    "new_listings_count",
                    "request_count",
                    "delivery_count",
                    "avg_response_time",
                    "avg_transaction_value",
                )
            },
        ),
        (
            "Transaction Completion",
            {
                "fields": (
                    "request_approval_rate",
                    "transaction_completion_rate",
                    "delivery_completion_rate",
                    "avg_rating",
                )
            },
        ),
    )
    readonly_fields = (
        "active_users",
        "new_users",
        "business_users_active",
        "nonprofit_users_active",
        "volunteer_users_active",
        "consumer_users_active",
        "new_listings_count",
        "request_count",
        "delivery_count",
        "avg_response_time",
        "avg_transaction_value",
        "request_approval_rate",
        "transaction_completion_rate",
        "delivery_completion_rate",
        "avg_rating",
    )


@admin.register(UserActivityLog)
class UserActivityLogAdmin(admin.ModelAdmin):
    list_display = ("user", "timestamp", "activity_type", "ip_address")
    list_filter = ("activity_type", "timestamp")
    search_fields = ("user__email", "activity_type", "details")
    date_hierarchy = "timestamp"
    readonly_fields = ("user", "timestamp", "activity_type", "details", "ip_address")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "report_type",
        "date_generated",
        "date_range_start",
        "date_range_end",
        "generated_by",
        "is_scheduled",
        "schedule_frequency",
    )
    list_filter = (
        "report_type",
        "date_generated",
        "is_scheduled",
        "schedule_frequency",
    )
    search_fields = ("title", "description", "summary", "generated_by__email")
    date_hierarchy = "date_generated"
    readonly_fields = ("date_generated",)
    fieldsets = (
        (
            "Report Information",
            {
                "fields": (
                    "title",
                    "description",
                    "report_type",
                    "date_generated",
                    "date_range_start",
                    "date_range_end",
                    "generated_by",
                    "summary",
                )
            },
        ),
        (
            "Scheduling",
            {
                "fields": ("is_scheduled", "schedule_frequency"),
                "classes": ("collapse",),
            },
        ),
        (
            "Report Data",
            {
                "fields": ("data",),
                "classes": ("collapse",),
            },
        ),
    )
