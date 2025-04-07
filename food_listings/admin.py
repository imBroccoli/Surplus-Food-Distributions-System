from django.contrib import admin

from .models import ComplianceCheck, FoodImage, FoodListing


@admin.register(FoodListing)
class FoodListingAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "supplier",
        "listing_type",
        "status",
        "expiry_date",
        "created_at",
    )
    list_filter = ("status", "listing_type", "created_at")
    search_fields = (
        "title",
        "description",
        "supplier__email",
        "supplier__businessprofile__company_name",
    )
    date_hierarchy = "created_at"

    fieldsets = (
        (None, {"fields": ("title", "description", "supplier")}),
        (
            "Listing Details",
            {"fields": ("quantity", "unit", "expiry_date", "listing_type", "price")},
        ),
        (
            "Storage & Handling",
            {"fields": ("storage_requirements", "handling_instructions")},
        ),
        (
            "Location",
            {"fields": ("address", "city", "postal_code", "latitude", "longitude")},
        ),
        ("Status", {"fields": ("status",)}),
    )


@admin.register(FoodImage)
class FoodImageAdmin(admin.ModelAdmin):
    list_display = ("listing", "is_primary", "uploaded_at")
    list_filter = ("is_primary", "uploaded_at")
    search_fields = ("listing__title",)


@admin.register(ComplianceCheck)
class ComplianceCheckAdmin(admin.ModelAdmin):
    list_display = ("listing", "checked_by", "is_compliant", "checked_at")
    list_filter = ("is_compliant", "checked_at")
    search_fields = ("listing__title", "checked_by__email", "notes")
