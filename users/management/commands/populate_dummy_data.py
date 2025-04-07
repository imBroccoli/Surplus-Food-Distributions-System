import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from analytics.models import DailyAnalytics, ImpactMetrics
from food_listings.models import FoodListing
from transactions.models import FoodRequest, Transaction, DeliveryAssignment
from users.models import (
    BusinessProfile,
    ConsumerProfile,
    NonprofitProfile,
    VolunteerProfile,
)


class Command(BaseCommand):
    help = "Populates the database with dummy data for testing"

    def handle(self, *args, **options):
        self.stdout.write("Creating dummy data...")

        # Create users of different types
        self.create_users()

        # Create food listings
        self.create_food_listings()

        # Create food requests and transactions
        self.create_transactions()

        # Create delivery assignments
        self.create_delivery_assignments()

        # Recalculate impact metrics for the past 30 days
        self.recalculate_impact_metrics()

        self.stdout.write(self.style.SUCCESS("Successfully created dummy data"))

    def create_users(self):
        User = get_user_model()

        # Create business users
        for i in range(5):
            user = User.objects.create_user(
                email=f"business{i}@example.com",
                password="testpass123",
                first_name=f"Business{i}",
                last_name="User",
                user_type="BUSINESS",
            )
            BusinessProfile.objects.create(
                user=user,
                company_name=f"Business Company {i}",
            )

        # Create nonprofit users
        for i in range(3):
            user = User.objects.create_user(
                email=f"nonprofit{i}@example.com",
                password="testpass123",
                first_name=f"Nonprofit{i}",
                last_name="User",
                user_type="NONPROFIT",
            )
            NonprofitProfile.objects.create(
                user=user,
                organization_name=f"Nonprofit Org {i}",
                organization_type="CHARITY",
                verified_nonprofit=True,
            )

        # Create volunteer users
        for i in range(4):
            user = User.objects.create_user(
                email=f"volunteer{i}@example.com",
                password="testpass123",
                first_name=f"Volunteer{i}",
                last_name="User",
                user_type="VOLUNTEER",
            )
            VolunteerProfile.objects.create(
                user=user,
                availability="FLEXIBLE",
                transportation_method="CAR",
                service_area="Local Area",
                has_valid_license=True,
            )

        # Create consumer users
        for i in range(5):
            user = User.objects.create_user(
                email=f"consumer{i}@example.com",
                password="testpass123",
                first_name=f"Consumer{i}",
                last_name="User",
                user_type="CONSUMER",
            )
            ConsumerProfile.objects.create(user=user, preferred_radius=Decimal("10.00"))

    def create_food_listings(self):
        business_users = get_user_model().objects.filter(user_type="BUSINESS")

        # Data matching your model's requirements
        sample_listings = [
            "Surplus Restaurant Meals",
            "Fresh Bakery Items",
            "Grocery Store Excess",
            "Fresh Produce Bundle",
            "Dairy Products Package",
            "Bulk Food Items",
        ]

        storage_requirements = [
            "Refrigeration required",
            "Room temperature storage",
            "Keep frozen",
            "Store in a cool, dry place",
        ]

        handling_instructions = [
            "Handle with care, temperature sensitive",
            "Keep refrigerated after opening",
            "Use within 24 hours of thawing",
            "Transport in temperature-controlled vehicle",
        ]

        units = ["kg", "boxes", "packages", "portions", "units", "pallets"]
        irish_cities = ["Dublin", "Cork", "Galway", "Limerick", "Waterford"]

        for business in business_users:
            for _ in range(random.randint(3, 7)):
                # Determine listing type and price
                listing_type = random.choice(
                    ["COMMERCIAL", "DONATION", "NONPROFIT_ONLY"]
                )
                price = (
                    Decimal(str(random.randint(5, 50)))
                    if listing_type == "COMMERCIAL"
                    else None
                )

                # Create listing with all required fields
                FoodListing.objects.create(
                    supplier=business,
                    title=random.choice(sample_listings),
                    description=f"Quality food items available for {listing_type.lower()}.",
                    quantity=Decimal(str(random.randint(10, 100))),
                    unit=random.choice(units),
                    expiry_date=timezone.now() + timedelta(days=random.randint(1, 14)),
                    storage_requirements=random.choice(storage_requirements),
                    handling_instructions=random.choice(handling_instructions),
                    listing_type=listing_type,
                    minimum_quantity=Decimal(str(random.randint(1, 5))),
                    requires_verification=listing_type == "NONPROFIT_ONLY",
                    status="ACTIVE",
                    price=price,
                    address=f"{random.randint(1, 100)} {random.choice(['Main St', 'O\'Connell St', 'Church St'])}",
                    city=random.choice(irish_cities),
                    postal_code=f"D{random.randint(1, 24)}",
                    latitude=Decimal(
                        str(random.uniform(51.4, 55.3))
                    ),  # Ireland latitude range
                    longitude=Decimal(
                        str(random.uniform(-10.5, -6.2))
                    ),  # Ireland longitude range
                )

    def create_transactions(self):
        active_listings = FoodListing.objects.filter(status="ACTIVE")
        consumers = get_user_model().objects.filter(user_type="CONSUMER")
        nonprofits = get_user_model().objects.filter(user_type="NONPROFIT")

        # Generate some transactions for past dates to populate historical data
        past_dates = [(timezone.now() - timedelta(days=x)).date() for x in range(30)]

        for listing in active_listings:
            for _ in range(random.randint(1, 3)):  # Create 1-3 transactions per listing
                try:
                    requester = random.choice(list(consumers) + list(nonprofits))
                    status = random.choice(["PENDING", "APPROVED", "COMPLETED"])

                    # Randomly select a date from past_dates for completed transactions
                    completion_date = None
                    transaction_date = timezone.now()

                    if status == "COMPLETED":
                        completion_date = timezone.now() - timedelta(
                            days=random.randint(0, 29)
                        )
                        transaction_date = completion_date

                    request = FoodRequest.objects.create(
                        listing=listing,
                        requester=requester,
                        quantity_requested=Decimal(
                            str(random.randint(1, int(listing.quantity)))
                        ),
                        pickup_date=timezone.now() + timedelta(days=random.randint(1, 5)),
                        status=status,
                    )

                    if request.status in ["APPROVED", "COMPLETED"]:
                        transaction = Transaction.objects.create(
                            request=request,
                            status=status,
                            completion_date=completion_date,
                            transaction_date=transaction_date,
                            notes="Generated by populate_dummy_data command"
                        )

                        # Update DailyAnalytics for completed transactions
                        if status == "COMPLETED" and completion_date:
                            try:
                                # Get the specific date we're recording for
                                analytics_date = completion_date.date()
                                
                                # Get or create the analytics record for this listing on this date
                                analytics = DailyAnalytics.get_or_create_for_listing(
                                    listing=listing, date=analytics_date
                                )
                                
                                # Increment the metrics with the quantity requested
                                analytics.increment_metrics(request.quantity_requested)
                                
                                self.stdout.write(
                                    f"Updated analytics for {analytics_date}: +{request.quantity_requested}kg"
                                )
                            except Exception as e:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"Could not update analytics for transaction: {e}"
                                    )
                                )
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Error creating transaction for listing {listing.id}: {e}"
                        )
                    )

    def create_delivery_assignments(self):
        """Create delivery assignments for volunteers"""
        from django.utils import timezone

        # Get completed transactions that don't have deliveries yet
        completed_transactions = Transaction.objects.filter(status="COMPLETED").exclude(
            delivery__isnull=False
        )

        volunteers = get_user_model().objects.filter(user_type="VOLUNTEER")

        for transaction in completed_transactions:
            # Randomly assign some transactions to volunteers
            if random.choice([True, False]):  # 50% chance
                volunteer = random.choice(volunteers)
                completion_date = transaction.completion_date or timezone.now()

                # Create delivery windows around the completion date
                pickup_start = completion_date - timedelta(hours=2)
                pickup_end = pickup_start + timedelta(minutes=30)
                delivery_start = pickup_end + timedelta(minutes=15)
                delivery_end = delivery_start + timedelta(hours=1)

                DeliveryAssignment.objects.create(
                    transaction=transaction,
                    volunteer=volunteer,
                    status="DELIVERED",
                    pickup_window_start=pickup_start,
                    pickup_window_end=pickup_end,
                    delivery_window_start=delivery_start,
                    delivery_window_end=delivery_end,
                    estimated_weight=transaction.request.quantity_requested,
                    assigned_at=pickup_start,
                    picked_up_at=pickup_start + timedelta(minutes=15),
                    delivered_at=completion_date,
                )

    def recalculate_impact_metrics(self):
        """Recalculate impact metrics for all dates with transactions"""
        self.stdout.write("Recalculating impact metrics...")
        try:
            # Get all unique dates from completed transactions
            transactions = Transaction.objects.filter(status="COMPLETED")
            dates = set()
            
            for transaction in transactions:
                if transaction.completion_date:
                    dates.add(transaction.completion_date.date())
            
            # Calculate metrics for each date
            for date in dates:
                metrics = ImpactMetrics.calculate_for_date(date)
                self.stdout.write(
                    f"Updated impact metrics for {date}: {metrics.food_redistributed_kg}kg food redistributed"
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"Error recalculating impact metrics: {e}")
            )
