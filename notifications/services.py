import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from django.urls import reverse
from django.utils import timezone

from transactions.models import DeliveryAssignment, FoodRequest

from .models import Notification

logger = logging.getLogger(__name__)


class NotificationService:
    @staticmethod
    def create_notification(
        recipient,
        notification_type,
        title,
        message,
        data=None,
        priority="MEDIUM",
        link=None,
    ):
        """Create a new notification with proper error handling and data validation"""
        try:
            # Check if user has push notifications enabled
            if hasattr(recipient, "get_profile"):
                profile = recipient.get_profile()
                if not profile.push_notifications:
                    # Skip creating notification if push notifications are disabled
                    logger.info(
                        f"Skipping notification for user {recipient.email} - push notifications disabled"
                    )
                    return None

            if data is None:
                data = {}

            notification = Notification.objects.create(
                recipient=recipient,
                notification_type=notification_type,
                title=title,
                message=message,
                data=data,
                priority=priority,
                link=link,
            )
            logger.info(
                f"Created notification {notification.id} of type {notification_type} for user {recipient.email}"
            )
            return notification
        except Exception as e:
            logger.error(
                f"Error creating notification for user {recipient.email}: {str(e)}"
            )
            raise

    @classmethod
    def create_compliance_notification(cls, listing, is_compliant):
        """Create a notification for a compliance check result"""
        message = f"Compliance check completed for listing '{listing.title}'. Status: {'Compliant' if is_compliant else 'Non-Compliant'}"
        title = f"Compliance Check: {listing.title}"

        link = reverse("listings:detail", args=[listing.pk])

        cls.create_notification(
            recipient=listing.supplier,
            notification_type="VERIFICATION_UPDATE",
            title=title,
            message=message,
            priority="HIGH" if not is_compliant else "MEDIUM",
            link=link,
        )

    @staticmethod
    def create_listing_notification(listing, notification_type="LISTING_NEW"):
        """Create notification for new/updated listing"""
        # Notify relevant nonprofits and consumers
        from users.models import CustomUser

        potential_recipients = CustomUser.objects.filter(
            user_type__in=["NONPROFIT", "CONSUMER"], is_active=True
        )

        title = (
            "New Food Listing Available"
            if notification_type == "LISTING_NEW"
            else "Listing Updated"
        )
        message = f"{listing.title} - {listing.quantity} {listing.unit} available"
        link = reverse("listings:detail", args=[listing.id])

        notifications = []
        for recipient in potential_recipients:
            notifications.append(
                Notification(
                    recipient=recipient,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    link=link,
                    data={
                        "sweetalert": {
                            "icon": "info",
                            "toast": True,
                            "position": "top-end",
                            "timer": 3000,
                            "timerProgressBar": True,
                        }
                    },
                )
            )
        Notification.objects.bulk_create(notifications)

    @classmethod
    def create_request_notification(
        cls, food_request: FoodRequest, old_status: str
    ) -> Optional[Notification]:
        """Create a notification for a food request status change"""
        try:
            notification_data = {
                "request_id": food_request.id,
                "old_status": old_status,
                "new_status": food_request.status,
                "listing_title": food_request.listing.title,
                "quantity": str(food_request.quantity_requested),
                "unit": food_request.listing.unit,
            }

            # Different messages based on status change
            if food_request.status == "APPROVED":
                title = "Food Request Approved"
                message = f"Your request for {food_request.quantity_requested} {food_request.listing.unit} of {food_request.listing.title} has been approved."
                recipient = food_request.requester
            elif food_request.status == "REJECTED":
                title = "Food Request Rejected"
                message = f"Your request for {food_request.quantity_requested} {food_request.listing.unit} of {food_request.listing.title} has been rejected."
                recipient = food_request.requester
            elif food_request.status == "CANCELLED":
                # Create two notifications - one for requester and one for supplier
                requester_notif = cls.create_notification(
                    recipient=food_request.requester,
                    notification_type="REQUEST_STATUS",
                    title="Request Cancelled",
                    message=f"You cancelled your request for {food_request.quantity_requested} {food_request.listing.unit} of {food_request.listing.title}",
                    data=notification_data,
                    priority="MEDIUM",
                    link=reverse("transactions:requests"),
                )

                # Notification for the business
                supplier_notif = cls.create_notification(
                    recipient=food_request.listing.supplier,
                    notification_type="REQUEST_STATUS",
                    title="Request Cancelled",
                    message=f"A request for {food_request.quantity_requested} {food_request.listing.unit} of {food_request.listing.title} has been cancelled by {food_request.requester.get_full_name()}",
                    data=notification_data,
                    priority="MEDIUM",
                    link=reverse("transactions:manage_requests"),
                )

                return requester_notif  # Return the requester notification for backward compatibility
            else:
                title = "Food Request Update"
                message = f"Status updated to {food_request.get_status_display()}"
                recipient = food_request.requester

            link = reverse("transactions:requests")

            return cls.create_notification(
                recipient=recipient,
                notification_type="REQUEST_STATUS",
                title=title,
                message=message,
                data=notification_data,
                priority="HIGH"
                if food_request.status in ["APPROVED", "REJECTED"]
                else "MEDIUM",
                link=link,
            )
        except Exception as e:
            logger.error(f"Error creating request notification: {str(e)}")
            raise

    @classmethod
    def create_delivery_notification(
        cls, delivery: DeliveryAssignment, old_status: str
    ) -> Optional[Notification]:
        """Create a notification for delivery status updates"""
        try:
            notification_data = {
                "delivery_id": delivery.id,
                "old_status": old_status,
                "new_status": delivery.status,
                "listing_title": delivery.transaction.request.listing.title,
            }

            notifications = []
            link = reverse(
                "transactions:transaction_detail", args=[delivery.transaction.id]
            )

            if delivery.status == "IN_TRANSIT":
                # Notify requester
                notifications.append(
                    {
                        "recipient": delivery.transaction.request.requester,
                        "title": "Delivery Started",
                        "message": "Your food is now being picked up for delivery.",
                    }
                )
                # Notify supplier
                notifications.append(
                    {
                        "recipient": delivery.transaction.request.listing.supplier,
                        "title": "Delivery In Progress",
                        "message": f"Your food listing '{delivery.transaction.request.listing.title}' is being picked up for delivery.",
                    }
                )

            elif delivery.status == "DELIVERED":
                # Notify requester
                notifications.append(
                    {
                        "recipient": delivery.transaction.request.requester,
                        "title": "Delivery Completed",
                        "message": "Your food has been successfully delivered.",
                    }
                )
                # Notify supplier
                notifications.append(
                    {
                        "recipient": delivery.transaction.request.listing.supplier,
                        "title": "Delivery Completed",
                        "message": f"Your food listing '{delivery.transaction.request.listing.title}' has been successfully delivered.",
                    }
                )
                # Notify volunteer of their impact
                notifications.append(
                    {
                        "recipient": delivery.volunteer,
                        "title": "Delivery Success",
                        "message": f"Thank you! You've successfully delivered {delivery.estimated_weight}kg of food and helped reduce food waste.",
                    }
                )

            # Create all notifications
            for notif in notifications:
                cls.create_notification(
                    recipient=notif["recipient"],
                    notification_type="DELIVERY_UPDATE",
                    title=notif["title"],
                    message=notif["message"],
                    data=notification_data,
                    priority="HIGH",
                    link=link,
                )

            # Return the first notification for backward compatibility
            return notifications[0] if notifications else None

        except Exception as e:
            logger.error(f"Error creating delivery notification: {str(e)}")
            raise

    @staticmethod
    def create_verification_notification(profile, verified):
        """Create notification for profile verification updates"""
        title = "Profile Verification Update"
        status = "verified" if verified else "rejected"
        message = f"Your organization profile has been {status}"
        if (
            not verified
            and hasattr(profile, "rejection_reason")
            and profile.rejection_reason
        ):
            message += f"\nReason: {profile.rejection_reason}"

        # Set up SweetAlert2 configuration
        sweetalert_config = {
            "icon": "success" if verified else "error",
            "toast": True,
            "position": "top-end",
            "timer": 3000,
            "timerProgressBar": True,
        }

        link = reverse("users:profile")

        NotificationService.create_notification(
            recipient=profile.user,
            notification_type="VERIFICATION_UPDATE",
            title=title,
            message=message,
            priority="HIGH",
            data={"sweetalert": sweetalert_config},
            link=link,
        )

    @staticmethod
    def create_pickup_reminder():
        """Create pickup reminders for upcoming deliveries"""
        tomorrow = timezone.now() + timedelta(days=1)
        upcoming_deliveries = DeliveryAssignment.objects.filter(
            status__in=["ASSIGNED", "PENDING"],
            pickup_window_start__date=tomorrow.date(),
        ).select_related("volunteer", "transaction__request__listing")

        # Set up SweetAlert2 configuration
        sweetalert_config = {
            "icon": "info",
            "toast": True,
            "position": "top-end",
            "timer": 3000,
            "timerProgressBar": True,
        }

        for delivery in upcoming_deliveries:
            if delivery.volunteer:
                title = "Pickup Reminder"
                message = f"Reminder: You have a pickup scheduled tomorrow for {delivery.transaction.request.listing.title}"
                link = reverse("transactions:my_deliveries")

                NotificationService.create_notification(
                    recipient=delivery.volunteer,
                    notification_type="PICKUP_REMINDER",
                    title=title,
                    message=message,
                    priority="HIGH",
                    link=link,
                    data={"sweetalert": sweetalert_config},
                )

    @classmethod
    def create_rating_notification(
        cls, rating_data: Dict[str, Any]
    ) -> Optional[Notification]:
        """Create a notification for new ratings"""
        try:
            notification_data = {
                "rating": rating_data["rating"],
                "transaction_id": rating_data["transaction_id"],
            }

            link = reverse(
                "transactions:transaction_detail", args=[rating_data["transaction_id"]]
            )

            return cls.create_notification(
                recipient=rating_data["rated_user"],
                notification_type="RATING_RECEIVED",
                title="New Rating Received",
                message=f"You've received a {rating_data['rating']}-star rating.",
                data=notification_data,
                priority="MEDIUM",
                link=link,
            )
        except Exception as e:
            logger.error(f"Error creating rating notification: {str(e)}")
            raise

    @staticmethod
    def get_unread_count(user):
        """Get count of unread notifications for a user"""
        return Notification.objects.filter(recipient=user, is_read=False).count()

    @staticmethod
    def create_report_notification(report, notification_type, user, extra_context=None):
        """Create a report-related notification with SweetAlert2 support"""
        notification_data = {
            "report_id": report.id,
            "report_type": report.report_type,
            "notification_type": notification_type,
        }

        if extra_context:
            notification_data.update(extra_context)

        # Set notification priority based on type
        if notification_type == "REPORT_ERROR":
            priority = "HIGH"
            icon = "error"
            title = "Report Generation Error"
        elif notification_type == "REPORT_GENERATED":
            priority = "MEDIUM"
            icon = "success"
            title = "Report Generated Successfully"
        else:
            priority = "LOW"
            icon = "info"
            title = "Report Update"

        notification_data.update(
            {
                "sweetalert": {
                    "icon": icon,
                    "title": title,
                    "toast": True,
                    "position": "top-end",
                    "showConfirmButton": False,
                    "timer": 3000,
                    "timerProgressBar": True,
                }
            }
        )

        link = reverse("analytics:report_detail", args=[report.id])

        return Notification.objects.create(
            recipient=user,
            notification_type=notification_type,
            title=title,
            message=f"Report {report.id} - {notification_type}",
            data=notification_data,
            priority=priority,
            link=link,
            is_read=False,
        )

    @classmethod
    def create_new_request_notification(cls, food_request) -> Optional[Notification]:
        """Create a notification for a new food request"""
        try:
            notification_data = {
                "request_id": food_request.id,
                "listing_id": food_request.listing.id,
                "quantity": str(food_request.quantity_requested),
                "unit": food_request.listing.unit,
                "requester_type": food_request.requester.user_type,
                "sweetalert": {
                    "icon": "info",
                    "toast": True,
                    "position": "top-end",
                    "timer": 3000,
                    "timerProgressBar": True,
                },
            }

            title = "New Food Request"
            message = f"{food_request.requester.get_full_name()} ({food_request.requester.user_type.lower()}) requested {food_request.quantity_requested} {food_request.listing.unit} of {food_request.listing.title}"
            link = reverse("transactions:manage_requests")

            return cls.create_notification(
                recipient=food_request.listing.supplier,
                notification_type="REQUEST_NEW",
                title=title,
                message=message,
                data=notification_data,
                priority="HIGH",
                link=link,
            )
        except Exception as e:
            logger.error(f"Error creating new request notification: {str(e)}")
            raise

    @staticmethod
    def create_available_delivery_notification(delivery: DeliveryAssignment):
        """Create notification for new available deliveries"""
        from users.models import CustomUser

        # Get all active volunteers
        volunteers = CustomUser.objects.filter(
            user_type="VOLUNTEER",
            is_active=True,
            volunteer_profile__active=True,
            volunteer_profile__push_notifications=True,
        )

        link = reverse("transactions:available_deliveries")
        title = "New Delivery Available"
        message = (
            f"New delivery task available: {delivery.transaction.request.listing.title}"
        )

        notifications = []
        for volunteer in volunteers:
            notifications.append(
                Notification(
                    recipient=volunteer,
                    notification_type="DELIVERY_UPDATE",
                    title=title,
                    message=message,
                    priority="MEDIUM",
                    link=link,
                    data={
                        "sweetalert": {
                            "icon": "info",
                            "toast": True,
                            "position": "top-end",
                            "timer": 3000,
                            "timerProgressBar": True,
                        }
                    },
                )
            )
        Notification.objects.bulk_create(notifications)
