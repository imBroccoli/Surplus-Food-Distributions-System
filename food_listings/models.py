from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class FoodListing(models.Model):
    class ListingStatus(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        PENDING = "PENDING", _("Pending Approval")
        ACTIVE = "ACTIVE", _("Active")
        RESERVED = "RESERVED", _("Reserved")
        COMPLETED = "COMPLETED", _("Completed")
        EXPIRED = "EXPIRED", _("Expired")
        INACTIVE = "INACTIVE", _("Inactive")  # Add new status for deactivated listings

    class DonationType(models.TextChoices):
        COMMERCIAL = "COMMERCIAL", _("Commercial")
        DONATION = "DONATION", _("Direct Donation")

    title = models.CharField(max_length=255)
    description = models.TextField()
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50)
    expiry_date = models.DateTimeField()
    storage_requirements = models.TextField(blank=True, null=True)
    handling_instructions = models.TextField(blank=True, null=True)
    listing_type = models.CharField(
        max_length=20,
        choices=[
            ("COMMERCIAL", "Commercial"),
            ("DONATION", "Donation"),
            ("NONPROFIT_ONLY", "Nonprofit Only"),
        ],
        default="COMMERCIAL",
    )
    minimum_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Minimum quantity per request (for bulk requests)",
    )
    requires_verification = models.BooleanField(
        default=False, help_text="Whether this listing requires nonprofit verification"
    )
    status = models.CharField(
        max_length=10, choices=ListingStatus.choices, default=ListingStatus.DRAFT
    )
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    supplier = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="food_listings"
    )
    address = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )

    @property
    def remaining_quantity(self):
        """Get the remaining quantity after approved requests"""
        from transactions.models import FoodRequest

        approved_requests = FoodRequest.objects.filter(
            listing=self, status=FoodRequest.RequestStatus.APPROVED
        ).aggregate(models.Sum("quantity_requested"))
        approved_quantity = approved_requests["quantity_requested__sum"] or 0
        return max(0, self.quantity - approved_quantity)

    def update_status_based_on_quantity(self):
        """Update listing status based on quantity changes"""
        if self.quantity <= 0 and self.status == self.ListingStatus.ACTIVE:
            # Deactivate if quantity reaches 0
            self.status = self.ListingStatus.INACTIVE
            self.save(update_fields=["status"])

            # Create notification for supplier
            from notifications.services import NotificationService

            NotificationService.create_listing_notification(
                listing=self, notification_type="LISTING_INACTIVE"
            )
        elif self.quantity > 0 and self.status == self.ListingStatus.INACTIVE:
            # Reactivate if quantity becomes positive
            self.status = self.ListingStatus.ACTIVE
            self.save(update_fields=["status"])

            # Create notification for supplier
            from notifications.services import NotificationService

            NotificationService.create_listing_notification(
                listing=self, notification_type="LISTING_UPDATE"
            )

    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"

    def clean(self):
        """Custom model validation"""
        super().clean()

        # Validate quantity is positive
        if self.quantity and self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be positive"})

        # Validate price for commercial listings
        if self.listing_type == "COMMERCIAL" and not self.price:
            raise ValidationError(
                {"price": "Price is required for commercial listings"}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
        self.update_status_based_on_quantity()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "expiry_date"]),
            models.Index(fields=["supplier", "status"]),
            models.Index(fields=["city", "status"]),
            models.Index(fields=["expiry_date", "listing_type"]),
            models.Index(fields=["listing_type", "requires_verification", "status"]),
            models.Index(fields=["listing_type", "status", "expiry_date"]),
        ]


class FoodImage(models.Model):
    listing = models.ForeignKey(
        FoodListing, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(upload_to="food_listings/")
    is_primary = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "-uploaded_at"]


class ComplianceCheck(models.Model):
    listing = models.OneToOneField(
        FoodListing, on_delete=models.CASCADE, related_name="compliance_check"
    )
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="compliance_checks",
    )
    is_compliant = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    checked_at = models.DateTimeField(auto_now=True)
