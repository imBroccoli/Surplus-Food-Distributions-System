from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        LISTING_NEW = "LISTING_NEW", _("New Listing Available")
        LISTING_UPDATE = "LISTING_UPDATE", _("Listing Updated")
        LISTING_INACTIVE = "LISTING_INACTIVE", _("Listing Deactivated")
        REQUEST_STATUS = "REQUEST_STATUS", _("Request Status Changed")
        PICKUP_REMINDER = "PICKUP_REMINDER", _("Pickup Reminder")
        EXPIRY_WARNING = "EXPIRY_WARNING", _("Expiry Warning")
        VERIFICATION_UPDATE = "VERIFICATION_UPDATE", _("Profile Verification Update")
        DELIVERY_UPDATE = "DELIVERY_UPDATE", _("Delivery Status Update")
        RATING_RECEIVED = "RATING_RECEIVED", _("New Rating Received")

    class Priority(models.TextChoices):
        LOW = "LOW", _("Low")
        MEDIUM = "MEDIUM", _("Medium")
        HIGH = "HIGH", _("High")

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    notification_type = models.CharField(
        max_length=50, choices=NotificationType.choices
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    priority = models.CharField(
        max_length=20, choices=Priority.choices, default=Priority.MEDIUM
    )
    link = models.CharField(max_length=255, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)  # Add this field

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["notification_type"]),
            models.Index(fields=["is_read", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.notification_type} - {self.recipient.email}"

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    def to_sweetalert_config(self):
        """Convert notification to SweetAlert2 configuration"""
        # Get SweetAlert2 config from data if it exists
        sweetalert_config = (
            self.data.get("sweetalert", {}) if isinstance(self.data, dict) else {}
        )

        # Set default configuration based on notification type and priority
        default_config = {
            "toast": True,
            "position": "top-end",
            "showConfirmButton": False,
            "timer": 3000,
            "timerProgressBar": True,
        }

        # Set icon and title based on notification type if not in data
        if "icon" not in sweetalert_config:
            if self.notification_type.startswith("ERROR"):
                sweetalert_config["icon"] = "error"
            elif self.notification_type.startswith("SUCCESS"):
                sweetalert_config["icon"] = "success"
            elif self.notification_type.startswith("WARNING"):
                sweetalert_config["icon"] = "warning"
            else:
                sweetalert_config["icon"] = "info"

        # Set title if not in data
        if "title" not in sweetalert_config:
            sweetalert_config["title"] = (
                self.title or self.get_notification_type_display()
            )

        # Merge with default config, preferring values from sweetalert_config
        return {**default_config, **sweetalert_config}

    @property
    def should_persist(self):
        """Determine if notification should persist in database"""
        # Don't persist temporary notifications (like report scheduling updates)
        if isinstance(self.data, dict) and self.data.get("temporary", False):
            return False

        # Don't persist notifications that are meant for immediate display only
        if self.notification_type in ["REPORT_SCHEDULE", "REPORT_UNSCHEDULE"]:
            return False

        return True

    def save(self, *args, **kwargs):
        """Override save to handle non-persistent notifications"""
        if self.should_persist:
            super().save(*args, **kwargs)
