from django.core.management.base import BaseCommand
from django.utils import timezone

from food_listings.models import FoodListing
from notifications.services import NotificationService


class Command(BaseCommand):
    help = "Send scheduled notifications for expiring listings and upcoming pickups"

    def handle(self, *args, **options):
        today = timezone.now()
        tomorrow = today + timezone.timedelta(days=1)

        # Send expiry warnings for listings expiring tomorrow
        expiring_listings = FoodListing.objects.filter(
            status="ACTIVE", expiry_date__date=tomorrow.date()
        ).select_related("supplier")

        for listing in expiring_listings:
            NotificationService.create_notification(
                recipient=listing.supplier,
                notification_type="EXPIRY_WARNING",
                title="Listing Expiring Tomorrow",
                message=f'Your listing "{listing.title}" will expire tomorrow',
                priority="HIGH",
                link=f"/listings/{listing.id}/",
            )
            self.stdout.write(f"Sent expiry warning for listing {listing.id}")

        # Send pickup reminders for tomorrow's deliveries
        NotificationService.create_pickup_reminder()
        self.stdout.write("Sent pickup reminders for tomorrow's deliveries")
