from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _

from notifications.services import NotificationService

from .models import (
    AdminProfile,
    BusinessProfile,
    ConsumerProfile,
    CustomUser,
    NonprofitProfile,
    VolunteerProfile,
)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = (
        "email",
        "first_name",
        "last_name",
        "user_type",
        "is_active",
        "is_staff",
    )
    list_filter = ("user_type", "is_active", "is_staff", "country")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "phone_number")}),
        (_("Address"), {"fields": ("address", "country")}),
        (_("User Type"), {"fields": ("user_type",)}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "user_type"),
            },
        ),
    )


@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    list_display = ("company_name", "user")
    search_fields = ("company_name", "user__email")
    raw_id_fields = ("user",)

    fieldsets = ((_("Business Information"), {"fields": ("user", "company_name")}),)


@admin.register(NonprofitProfile)
class NonprofitProfileAdmin(admin.ModelAdmin):
    list_display = (
        "organization_name",
        "user",
        "organization_type",
        "verified_nonprofit",
    )
    list_filter = ("verified_nonprofit", "organization_type")
    search_fields = (
        "organization_name",
        "user__email",
        "registration_number",
        "charity_number",
    )
    raw_id_fields = ("user",)

    fieldsets = (
        (
            _("Organization Information"),
            {
                "fields": (
                    "user",
                    "organization_name",
                    "registration_number",
                    "charity_number",
                )
            },
        ),
        (
            _("Additional Details"),
            {
                "fields": (
                    "organization_type",
                    "focus_area",
                    "service_area",
                    "primary_contact",
                )
            },
        ),
        (
            _("Verification"),
            {
                "fields": (
                    "verified_nonprofit",
                    "rejection_reason",
                    "verification_documents",
                )
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if change and "verified_nonprofit" in form.changed_data:
            # Create notification for verification status change
            NotificationService.create_verification_notification(
                obj, obj.verified_nonprofit
            )
        super().save_model(request, obj, form, change)


@admin.register(VolunteerProfile)
class VolunteerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "availability",
        "transportation_method",
        "has_valid_license",
        "completed_deliveries",
        "active",
    )
    list_filter = (
        "availability",
        "transportation_method",
        "has_valid_license",
        "active",
    )
    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "service_area",
    )
    raw_id_fields = ("user",)

    fieldsets = (
        (_("Basic Information"), {"fields": ("user", "availability", "service_area")}),
        (
            _("Transportation Details"),
            {
                "fields": (
                    "transportation_method",
                    "has_valid_license",
                    "vehicle_type",
                    "max_delivery_weight",
                )
            },
        ),
        (
            _("Statistics"),
            {"fields": ("completed_deliveries", "total_impact", "active")},
        ),
    )


@admin.register(AdminProfile)
class AdminProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "get_department_display", "last_login_ip", "created_at")
    list_filter = ("department", "created_at")
    search_fields = ("user__email", "user__first_name", "user__last_name", "notes")
    readonly_fields = ("last_login_ip", "created_at", "updated_at")

    fieldsets = (
        (_("User Information"), {"fields": ("user", "department")}),
        (_("Access Information"), {"fields": ("last_login_ip", "modules_accessed")}),
        (
            _("Additional Information"),
            {"fields": ("notes", "created_at", "updated_at")},
        ),
    )

    def get_department_display(self, obj):
        return obj.get_department_display()
    get_department_display.short_description = 'Department'


@admin.register(ConsumerProfile)
class ConsumerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "preferred_radius",
        "created_at",
    )
    search_fields = ("user__email", "user__first_name", "user__last_name")
    raw_id_fields = ("user",)

    fieldsets = (
        (_("User Information"), {"fields": ("user", "dietary_preferences")}),
        (_("Preferences"), {"fields": ("preferred_radius",)}),
        (
            _("Notifications"),
            {
                "fields": (
                    "push_notifications",
                    "notification_frequency",
                )
            },
        ),
    )
