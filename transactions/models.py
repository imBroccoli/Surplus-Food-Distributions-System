from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from food_listings.models import FoodListing


class FoodRequest(models.Model):
    class RequestStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        APPROVED = "APPROVED", _("Approved")
        REJECTED = "REJECTED", _("Rejected")
        COMPLETED = "COMPLETED", _("Completed")
        CANCELLED = "CANCELLED", _("Cancelled")

    # State transition validation
    VALID_TRANSITIONS = {
        "PENDING": ["APPROVED", "REJECTED", "CANCELLED"],
        "APPROVED": [
            "COMPLETED",
            "CANCELLED",
            "PENDING",
        ],  # Allow reverting to pending for edge cases
        "REJECTED": ["CANCELLED", "PENDING"],  # Allow retrying rejected requests
        "COMPLETED": [],  # No transitions allowed from completed
        "CANCELLED": ["PENDING"],  # Allow reactivating cancelled requests
    }

    listing = models.ForeignKey(
        FoodListing, on_delete=models.CASCADE, related_name="requests"
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="food_requests"
    )
    status = models.CharField(
        max_length=10, choices=RequestStatus.choices, default=RequestStatus.PENDING
    )
    quantity_requested = models.DecimalField(max_digits=10, decimal_places=2)
    pickup_date = models.DateTimeField()
    notes = models.TextField(blank=True)
    is_bulk_request = models.BooleanField(
        default=False, help_text="Whether this is a bulk request from a nonprofit"
    )
    intended_use = models.TextField(
        blank=True,
        help_text="Description of how the food will be used (required for nonprofit requests)",
    )
    beneficiary_count = models.PositiveIntegerField(
        null=True, blank=True, help_text="Estimated number of beneficiaries"
    )
    preferred_time = models.CharField(
        max_length=20,
        choices=[
            ('morning', 'Morning: 8:00 AM - 11:00 AM'),
            ('afternoon', 'Afternoon: 12:00 PM - 4:00 PM'),
            ('evening', 'Evening: 5:00 PM - 8:00 PM'),
            ('night', 'Night: 9:00 PM - 11:00 PM'),
        ],
        null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def update_listing_quantity(self):
        """Update the listing quantity when request is approved"""
        if self.status == self.RequestStatus.APPROVED:
            if self.listing.quantity >= self.quantity_requested:
                self.listing.quantity -= self.quantity_requested
                self.listing.save(update_fields=["quantity"])
                # Force update status check after quantity change
                self.listing.update_status_based_on_quantity()
                return True
        return False

    def save(self, *args, **kwargs):
        if self.requester and self.requester.user_type == "NONPROFIT":
            self.is_bulk_request = True
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "pickup_date"]),
            models.Index(fields=["requester", "status"]),
            models.Index(fields=["listing", "status"]),
        ]

    def __str__(self):
        return f"Request for {self.listing.title} by {self.requester.email}"


class Transaction(models.Model):
    class TransactionStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        IN_PROGRESS = "IN_PROGRESS", _("In Progress")
        COMPLETED = "COMPLETED", _("Completed")
        CANCELLED = "CANCELLED", _("Cancelled")
        FAILED = "FAILED", _("Failed")

    request = models.OneToOneField(
        FoodRequest, on_delete=models.CASCADE, related_name="transaction"
    )
    status = models.CharField(
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING,
    )
    transaction_date = models.DateTimeField(auto_now_add=True)
    completion_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def get_user_rating_for_user(self, user):
        """Get the rating given by a specific user for this transaction"""
        try:
            return self.ratings.get(rater=user)
        except Rating.DoesNotExist:
            return None

    def __str__(self):
        return f"Transaction for {self.request}"


class Rating(models.Model):
    transaction = models.ForeignKey(
        Transaction, on_delete=models.CASCADE, related_name="ratings"
    )
    rater = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ratings_given"
    )
    rated_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ratings_received",
    )
    rating = models.IntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["transaction", "rater"]

    def __str__(self):
        return f"{self.rater} rated {self.rated_user} ({self.rating} stars)"


class DeliveryAssignment(models.Model):
    class DeliveryStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending Assignment")
        ASSIGNED = "ASSIGNED", _("Assigned")
        IN_TRANSIT = "IN_TRANSIT", _("In Transit")
        DELIVERED = "DELIVERED", _("Delivered")
        CANCELLED = "CANCELLED", _("Cancelled")
        FAILED = "FAILED", _("Failed")

    transaction = models.OneToOneField(
        Transaction, on_delete=models.CASCADE, related_name="delivery"
    )
    volunteer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )
    status = models.CharField(
        max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    pickup_window_start = models.DateTimeField()
    pickup_window_end = models.DateTimeField()
    delivery_window_start = models.DateTimeField()
    delivery_window_end = models.DateTimeField()
    pickup_notes = models.TextField(blank=True)
    delivery_notes = models.TextField(blank=True)
    estimated_weight = models.DecimalField(
        max_digits=5, decimal_places=2, help_text="Estimated weight in kg"
    )
    distance = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Estimated distance in km",
        null=True,
        blank=True,
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Delivery #{self.id} - {self.get_status_display()}"

    def clean(self):
        if self.pickup_window_end <= self.pickup_window_start:
            raise ValidationError("Pickup window end must be after start")
        if self.delivery_window_end <= self.delivery_window_start:
            raise ValidationError("Delivery window end must be after start")
        if self.delivery_window_start <= self.pickup_window_end:
            raise ValidationError("Delivery window must be after pickup window")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "pickup_window_start"]),
            models.Index(fields=["volunteer", "status"]),
        ]
