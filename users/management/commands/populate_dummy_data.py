import random
from datetime import timedelta
from decimal import Decimal
import datetime

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

        # Guarantee daily activity for analytics
        self.create_daily_analytics_baseline()

        # Recalculate impact metrics for the past 30 days
        self.recalculate_impact_metrics()

        self.stdout.write(self.style.SUCCESS("Successfully created dummy data"))

    def random_date_in_last_n_days(self, n=180):
        today = timezone.now()
        days_ago = random.randint(0, n-1)
        random_time = timedelta(
            days=days_ago,
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
            seconds=random.randint(0, 59),
        )
        return today - random_time

    def create_users(self):
        User = get_user_model()

        # Create business users
        for i in range(5):
            join_date = self.random_date_in_last_n_days(n=180)
            last_login = join_date + timedelta(days=random.randint(0, 30))
            user = User.objects.create_user(
                email=f"business{i}@example.com",
                password="testpass123",
                first_name=f"Business{i}",
                last_name="User",
                user_type="BUSINESS",
                date_joined=join_date,
            )
            user.last_login = last_login
            user.save(update_fields=["last_login"])
            BusinessProfile.objects.create(
                user=user,
                company_name=f"Business Company {i}",
            )

        # Create nonprofit users
        for i in range(3):
            join_date = self.random_date_in_last_n_days(n=180)
            last_login = join_date + timedelta(days=random.randint(0, 30))
            user = User.objects.create_user(
                email=f"nonprofit{i}@example.com",
                password="testpass123",
                first_name=f"Nonprofit{i}",
                last_name="User",
                user_type="NONPROFIT",
                date_joined=join_date,
            )
            user.last_login = last_login
            user.save(update_fields=["last_login"])
            NonprofitProfile.objects.create(
                user=user,
                organization_name=f"Nonprofit Org {i}",
                organization_type="CHARITY",
                verified_nonprofit=True,
            )

        # Create volunteer users
        for i in range(4):
            join_date = self.random_date_in_last_n_days(n=180)
            last_login = join_date + timedelta(days=random.randint(0, 30))
            user = User.objects.create_user(
                email=f"volunteer{i}@example.com",
                password="testpass123",
                first_name=f"Volunteer{i}",
                last_name="User",
                user_type="VOLUNTEER",
                date_joined=join_date,
            )
            user.last_login = last_login
            user.save(update_fields=["last_login"])
            VolunteerProfile.objects.create(
                user=user,
                availability="FLEXIBLE",
                transportation_method="CAR",
                service_area="Local Area",
                has_valid_license=True,
            )

        # Create consumer users
        for i in range(5):
            join_date = self.random_date_in_last_n_days(n=180)
            last_login = join_date + timedelta(days=random.randint(0, 30))
            user = User.objects.create_user(
                email=f"consumer{i}@example.com",
                password="testpass123",
                first_name=f"Consumer{i}",
                last_name="User",
                user_type="CONSUMER",
                date_joined=join_date,
            )
            user.last_login = last_login
            user.save(update_fields=["last_login"])
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
            created_at = self.random_date_in_last_n_days(n=180)
            expiry_date = timezone.now() + timedelta(days=random.randint(7, 30))
            if timezone.is_naive(expiry_date):
                expiry_date = timezone.make_aware(expiry_date)
            listing = FoodListing.objects.create(
                supplier=business,
                title="Guaranteed Active Listing",
                description="This is a guaranteed active listing for analytics.",
                quantity=Decimal(str(random.randint(10, 100))),
                unit=random.choice(units),
                expiry_date=expiry_date,
                storage_requirements=random.choice(storage_requirements),
                handling_instructions=random.choice(handling_instructions),
                listing_type="COMMERCIAL",
                minimum_quantity=Decimal(str(random.randint(1, 5))),
                requires_verification=False,
                status="ACTIVE",
                price=Decimal(str(random.randint(10, 50))),
                address=f"{random.randint(1, 100)} Main St",
                city=random.choice(irish_cities),
                postal_code=f"D{random.randint(1, 24)}",
                latitude=Decimal(str(random.uniform(51.4, 55.3))),
                longitude=Decimal(str(random.uniform(-10.5, -6.2))),
            )
            listing.created_at = created_at
            listing.save(update_fields=["created_at"])
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

                # Randomly choose expiry date: past (expired) or future (active)
                days_offset = random.randint(-180, 14)  # -180 days (6 months ago) to +14 days
                expiry_date = timezone.now() + timedelta(days=days_offset)
                if timezone.is_naive(expiry_date):
                    expiry_date = timezone.make_aware(expiry_date)
                status = "EXPIRED" if expiry_date < timezone.now() else "ACTIVE"

                created_at = self.random_date_in_last_n_days(n=180)

                listing = FoodListing.objects.create(
                    supplier=business,
                    title=random.choice(sample_listings),
                    description=f"Quality food items available for {listing_type.lower()}.",
                    quantity=Decimal(str(random.randint(10, 100))),
                    unit=random.choice(units),
                    expiry_date=expiry_date,
                    storage_requirements=random.choice(storage_requirements),
                    handling_instructions=random.choice(handling_instructions),
                    listing_type=listing_type,
                    minimum_quantity=Decimal(str(random.randint(1, 5))),
                    requires_verification=listing_type == "NONPROFIT_ONLY",
                    status=status,
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
                listing.created_at = created_at
                listing.save(update_fields=["created_at"])

        # Ensure at least two listings for today for analytics
        today = timezone.now().date()
        business_users = list(business_users)
        for i in range(2):
            business = random.choice(business_users)
            expiry_date = timezone.now() + timedelta(days=random.randint(7, 30))
            if timezone.is_naive(expiry_date):
                expiry_date = timezone.make_aware(expiry_date)
            listing = FoodListing.objects.create(
                supplier=business,
                title=f"Today's Listing {i+1}",
                description="Guaranteed listing for today's analytics.",
                quantity=Decimal(str(random.randint(10, 100))),
                unit=random.choice(units),
                expiry_date=expiry_date,
                storage_requirements=random.choice(storage_requirements),
                handling_instructions=random.choice(handling_instructions),
                listing_type="COMMERCIAL",
                minimum_quantity=Decimal(str(random.randint(1, 5))),
                requires_verification=False,
                status="ACTIVE",
                price=Decimal(str(random.randint(10, 50))),
                address=f"{random.randint(1, 100)} Main St",
                city=random.choice(irish_cities),
                postal_code=f"D{random.randint(1, 24)}",
                latitude=Decimal(str(random.uniform(51.4, 55.3))),
                longitude=Decimal(str(random.uniform(-10.5, -6.2))),
            )
            # Set created_at to today at midnight
            listing.created_at = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
            listing.save(update_fields=["created_at"])

            # --- Guarantee at least one approved request, transaction, and delivery for today ---
            from users.models import CustomUser
            from transactions.models import FoodRequest, Transaction, DeliveryAssignment

            requester = random.choice(
                list(CustomUser.objects.filter(user_type__in=["CONSUMER", "NONPROFIT"]))
            )
            # Set times for today
            created_at = timezone.make_aware(datetime.datetime.combine(today, datetime.time(hour=9)))
            updated_at = created_at + timedelta(hours=2)
            pickup_date = updated_at + timedelta(hours=1)

            # Create approved request (for response time and approval rate)
            request = FoodRequest.objects.create(
                listing=listing,
                requester=requester,
                quantity_requested=Decimal("5"),
                pickup_date=pickup_date,
                status="APPROVED",
                created_at=created_at,
                updated_at=updated_at,
            )

            # Create a rejected request for approval rate diversity
            rejected_request = FoodRequest.objects.create(
                listing=listing,
                requester=requester,
                quantity_requested=Decimal("3"),
                pickup_date=pickup_date,
                status="REJECTED",
                created_at=created_at + timedelta(hours=1),
                updated_at=updated_at + timedelta(hours=1),
            )

            # Create completed transaction for the approved request
            completion_date = updated_at + timedelta(hours=2)
            transaction = Transaction.objects.create(
                request=request,
                status="COMPLETED",
                completion_date=completion_date,
                transaction_date=completion_date,
                notes="Guaranteed analytics transaction for today"
            )

            # Create delivery assignment with status DELIVERED for today
            pickup_start = completion_date - timedelta(hours=2)
            pickup_end = pickup_start + timedelta(minutes=30)
            delivery_start = pickup_end + timedelta(minutes=15)
            delivery_end = delivery_start + timedelta(hours=1)
            delivery = DeliveryAssignment.objects.create(
                transaction=transaction,
                volunteer=random.choice(list(CustomUser.objects.filter(user_type="VOLUNTEER"))),
                status="DELIVERED",
                pickup_window_start=pickup_start,
                pickup_window_end=pickup_end,
                delivery_window_start=delivery_start,
                delivery_window_end=delivery_end,
                estimated_weight=request.quantity_requested,
                assigned_at=pickup_start,
                picked_up_at=pickup_start + timedelta(minutes=15),
                delivered_at=timezone.make_aware(datetime.datetime.combine(today, datetime.time(hour=15))),
            )
            delivery.created_at = pickup_start
            delivery.save(update_fields=["created_at"])

    def create_transactions(self):
        # Use both active and expired listings
        active_listings = FoodListing.objects.filter(status="ACTIVE")
        expired_listings = FoodListing.objects.filter(status="EXPIRED")
        listings = list(active_listings) + list(expired_listings)
        consumers = get_user_model().objects.filter(user_type="CONSUMER")
        nonprofits = get_user_model().objects.filter(user_type="NONPROFIT")
        volunteers = get_user_model().objects.filter(user_type="VOLUNTEER")

        # Generate transactions for the past 6 months (180 days)
        for listing in listings:
            for _ in range(random.randint(2, 4)):
                try:
                    requester = random.choice(list(consumers) + list(nonprofits))
                    status = random.choices(
                        ["PENDING", "APPROVED", "COMPLETED", "CANCELLED", "EXPIRED"],
                        weights=[2, 2, 3, 1, 1],
                        k=1
                    )[0]

                    # Simulate realistic request creation and approval times
                    today = timezone.now().date()
                    if random.random() < 0.1:  # 10% of requests are for today
                        created_at = timezone.make_aware(datetime.datetime.combine(today, datetime.time(hour=random.randint(8, 16))))
                        approval_delay_hours = random.randint(1, 3)
                        approved_at = created_at + timedelta(hours=approval_delay_hours)
                    else:
                        created_at = self.random_date_in_last_n_days(n=180)
                        approval_delay_hours = random.randint(2, 24)
                        approved_at = created_at + timedelta(hours=approval_delay_hours)
                        # --- FIX: If updated_at is today, created_at must also be today and only a few hours earlier ---
                        if approved_at.date() == today and created_at.date() != today:
                            created_at = timezone.make_aware(datetime.datetime.combine(today, datetime.time(hour=random.randint(8, 16))))
                            approval_delay_hours = random.randint(1, 3)
                            approved_at = created_at + timedelta(hours=approval_delay_hours)

                    completion_date = None
                    transaction_date = created_at

                    if status == "COMPLETED":
                        completion_date = approved_at + timedelta(hours=random.randint(1, 24))
                        transaction_date = completion_date
                    elif status == "EXPIRED":
                        completion_date = approved_at + timedelta(hours=random.randint(1, 24))
                        transaction_date = completion_date
                    elif status == "CANCELLED":
                        completion_date = None
                        transaction_date = approved_at + timedelta(hours=random.randint(1, 24))

                    if listing.listing_type == "COMMERCIAL":
                        price = listing.price or Decimal(str(random.randint(10, 50)))
                        listing.price = price
                        listing.save(update_fields=["price"])
                    else:
                        price = None

                    request = FoodRequest.objects.create(
                        listing=listing,
                        requester=requester,
                        quantity_requested=Decimal(
                            str(random.randint(1, int(listing.quantity)))
                        ),
                        pickup_date=approved_at + timedelta(hours=random.randint(1, 24)),
                        status=status,
                        created_at=created_at,
                        updated_at=approved_at if status in ["APPROVED", "COMPLETED"] else created_at,
                    )

                    if request.status in ["APPROVED", "COMPLETED"]:
                        transaction = Transaction.objects.create(
                            request=request,
                            status=status,
                            completion_date=completion_date,
                            transaction_date=transaction_date,
                            notes="Generated by populate_dummy_data command"
                        )

                        # For a larger portion of completed transactions, create a DeliveryAssignment with status DELIVERED
                        if status == "COMPLETED" and completion_date and random.random() < 0.95 and volunteers:
                            volunteer = random.choice(volunteers)
                            delivered_at = completion_date + timedelta(hours=random.randint(1, 6))
                            pickup_start = completion_date - timedelta(hours=2)
                            pickup_end = pickup_start + timedelta(minutes=30)
                            delivery_start = pickup_end + timedelta(minutes=15)
                            delivery_end = delivery_start + timedelta(hours=1)
                            from transactions.models import DeliveryAssignment
                            delivery = DeliveryAssignment.objects.create(
                                transaction=transaction,
                                volunteer=volunteer,
                                status="DELIVERED",
                                pickup_window_start=pickup_start,
                                pickup_window_end=pickup_end,
                                delivery_window_start=delivery_start,
                                delivery_window_end=delivery_end,
                                estimated_weight=request.quantity_requested,
                                assigned_at=pickup_start,
                                picked_up_at=pickup_start + timedelta(minutes=15),
                                delivered_at=delivered_at,
                            )
                            # Randomize delivery created_at
                            delivery.created_at = pickup_start
                            delivery.save(update_fields=["created_at"])

                        if status == "COMPLETED" and completion_date:
                            try:
                                analytics_date = completion_date.date()
                                analytics = DailyAnalytics.get_or_create_for_listing(
                                    listing=listing, date=analytics_date
                                )
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

    def create_daily_analytics_baseline(self):
        """
        For each of the last 180 days, guarantee:
        - 2+ completed deliveries
        - 2+ requests with approval delays
        - 2+ completed commercial transactions with a price
        """
        User = get_user_model()
        business_users = list(User.objects.filter(user_type="BUSINESS"))
        consumer_users = list(User.objects.filter(user_type="CONSUMER"))
        nonprofit_users = list(User.objects.filter(user_type="NONPROFIT"))
        volunteer_users = list(User.objects.filter(user_type="VOLUNTEER"))
        today = timezone.now().date()
        for days_ago in range(0, 180):
            day = today - timedelta(days=days_ago)
            print(f"[DEBUG] Creating baseline data for day: {day}")
            # Pick random business, consumer, nonprofit, volunteer
            business = random.choice(business_users)
            consumer = random.choice(consumer_users)
            nonprofit = random.choice(nonprofit_users)
            volunteer = random.choice(volunteer_users)
            # Create 2 commercial listings for this day
            for i in range(2):
                expiry_date = day + timedelta(days=7)
                if isinstance(expiry_date, datetime.date) and not isinstance(expiry_date, datetime.datetime):
                    expiry_date = timezone.make_aware(datetime.datetime.combine(expiry_date, datetime.time()))
                elif timezone.is_naive(expiry_date):
                    expiry_date = timezone.make_aware(expiry_date)
                listing = FoodListing.objects.create(
                    supplier=business,
                    title=f"Analytics Listing {i} {day}",
                    description="Guaranteed listing for analytics.",
                    quantity=Decimal(str(random.randint(10, 100))),
                    unit="kg",
                    expiry_date=expiry_date,
                    storage_requirements="Room temperature storage",
                    handling_instructions="Handle with care",
                    listing_type="COMMERCIAL",
                    minimum_quantity=Decimal("1"),
                    requires_verification=False,
                    status="ACTIVE",
                    price=Decimal(str(random.randint(10, 50))),
                    address=f"{random.randint(1, 100)} Main St",
                    city="Dublin",
                    postal_code="D1",
                    latitude=Decimal("53.35"),
                    longitude=Decimal("-6.26"),
                )
                listing.created_at = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))
                listing.save(update_fields=["created_at"])
                print(f"[DEBUG]  Listing expiry_date: {expiry_date}, created_at: {listing.created_at}")
                # Create 2 requests with approval delays
                for j in range(2):
                    requester = consumer if j == 0 else nonprofit
                    # Always use midnight as the base time for every day, including today
                    base_time = timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour=0, minute=0)))
                    approval_delay = random.randint(2, 8)
                    updated_at = base_time + timedelta(hours=approval_delay)
                    # Ensure updated_at does not cross to the next day
                    if updated_at.date() != day:
                        updated_at = base_time.replace(hour=23, minute=59)
                    request = FoodRequest.objects.create(
                        listing=listing,
                        requester=requester,
                        quantity_requested=Decimal(str(random.randint(1, 10))),
                        pickup_date=updated_at + timedelta(hours=2),
                        status="APPROVED",
                    )
                    request.created_at = base_time
                    request.updated_at = updated_at
                    request.save(update_fields=["created_at", "updated_at"])
                    print(f"[DEBUG]   Request: {request.id}, status: {request.status}, created_at: {request.created_at}, updated_at: {request.updated_at}, diff_hours: {(request.updated_at - request.created_at).total_seconds() / 3600:.2f}")
                    # Create completed transaction with price
                    completion_date = updated_at + timedelta(hours=2)
                    transaction = Transaction.objects.create(
                        request=request,
                        status="COMPLETED",
                        completion_date=completion_date,
                        transaction_date=completion_date,
                        notes="Guaranteed analytics transaction"
                    )
                    # Create delivery assignment with status DELIVERED
                    pickup_start = completion_date - timedelta(hours=2)
                    pickup_end = pickup_start + timedelta(minutes=30)
                    delivery_start = pickup_end + timedelta(minutes=15)
                    delivery_end = delivery_start + timedelta(hours=1)
                    delivery = DeliveryAssignment.objects.create(
                        transaction=transaction,
                        volunteer=volunteer,
                        status="DELIVERED",
                        pickup_window_start=pickup_start,
                        pickup_window_end=pickup_end,
                        delivery_window_start=delivery_start,
                        delivery_window_end=delivery_end,
                        estimated_weight=request.quantity_requested,
                        assigned_at=pickup_start,
                        picked_up_at=pickup_start + timedelta(minutes=15),
                        delivered_at=completion_date + timedelta(hours=1),
                    )
                    delivery.created_at = pickup_start
                    delivery.save(update_fields=["created_at"])

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
