from datetime import datetime, timedelta, time
from decimal import Decimal
from io import BytesIO
from typing import Dict, Optional, Union

import xlsxwriter
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.db.models import (
    Avg,
    Count,
    ExpressionWrapper,
    F,
    Manager,
    Sum,
    Case,
    When,
    Value,
    Q,
)
from django.db.models.functions import Concat, TruncDay, Coalesce, ExtractWeekDay, ExtractHour
from django.db.utils import Error as DBError
from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from food_listings.models import ComplianceCheck, FoodListing
from transactions.models import DeliveryAssignment, FoodRequest, Transaction, Rating


class BaseModel(models.Model):
    """Abstract base model with objects manager explicitly defined"""

    objects: Manager = Manager()

    class Meta:
        abstract = True


class ImpactMetrics(BaseModel):
    date = models.DateField(default=timezone.now)
    food_redistributed_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total weight of food redistributed in kilograms",
    )
    co2_emissions_saved = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Estimated CO2 emissions saved in kilograms",
    )
    meals_provided = models.IntegerField(
        default=0, help_text="Estimated number of meals provided"
    )
    monetary_value_saved = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Estimated monetary value saved in dollars",
    )

    class Meta:
        verbose_name = "Impact Metrics"
        verbose_name_plural = "Impact Metrics"
        ordering = ["-date"]
        indexes = [models.Index(fields=["date"])]

    def __str__(self):
        return f"Impact Metrics for {self.date}"

    @classmethod
    def calculate_for_date(cls, date):
        """Calculate impact metrics for a specific date"""
        # Get completed transactions for the date
        transactions = Transaction.objects.filter(
            status="COMPLETED", completion_date__date=date
        ).select_related("request__listing")

        # Calculate food redistributed
        food_redistributed = transactions.aggregate(
            total=Sum("request__quantity_requested")
        )["total"] or Decimal("0")

        # For zero quantity, all metrics should be zero
        if food_redistributed == Decimal("0"):
            metrics, _ = cls.objects.update_or_create(
                date=date,
                defaults={
                    "food_redistributed_kg": Decimal("0"),
                    "co2_emissions_saved": Decimal("0"),
                    "meals_provided": 0,
                    "monetary_value_saved": Decimal("0"),
                },
            )
            return metrics

        # Calculate other metrics
        co2_saved = food_redistributed * Decimal("2.5")
        meals = int(food_redistributed * Decimal("2"))

        # Calculate monetary value based on transaction quantity and listing price per unit
        monetary_value = Decimal("0")
        for transaction in transactions:
            if transaction.request and transaction.request.listing:
                quantity = transaction.request.quantity_requested
                # Use listing price if available, otherwise use default value of $1 per kg
                price = transaction.request.listing.price or Decimal("1.00")
                if quantity > 0:
                    monetary_value += (
                        quantity * price
                    )  # Calculate total value based on quantity and price

        # Create or update metrics
        metrics, _ = cls.objects.update_or_create(
            date=date,
            defaults={
                "food_redistributed_kg": food_redistributed,
                "co2_emissions_saved": co2_saved,
                "meals_provided": meals,
                "monetary_value_saved": monetary_value,
            },
        )
        return metrics


class DailyAnalytics(BaseModel):
    """Tracks daily analytics per user/listing"""

    date = models.DateField(default=timezone.now)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    listing = models.ForeignKey(FoodListing, on_delete=models.CASCADE)
    requests_received = models.IntegerField(default=0)
    requests_fulfilled = models.IntegerField(default=0)
    food_saved_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Daily Analytics"
        verbose_name_plural = "Daily Analytics"
        ordering = ["-date"]
        unique_together = ["date", "user", "listing"]
        indexes = [
            models.Index(fields=["date", "user"]),
            models.Index(fields=["date", "listing"]),
        ]

    def __str__(self):
        return f"Analytics for {self.listing.title} on {self.date}"

    def clean(self):
        if self.requests_received < 0:
            raise ValidationError({"requests_received": "Cannot be negative"})
        if self.requests_fulfilled < 0:
            raise ValidationError({"requests_fulfilled": "Cannot be negative"})
        if self.food_saved_kg < 0:
            raise ValidationError({"food_saved_kg": "Cannot be negative"})
        if self.requests_fulfilled > self.requests_received:
            raise ValidationError(
                {"requests_fulfilled": "Cannot exceed requests received"}
            )

    @classmethod
    def get_or_create_for_listing(cls, listing, date=None):
        """Get or create analytics entry for a listing on a specific date"""
        if date is None:
            date = timezone.now().date()

        analytics, created = cls.objects.get_or_create(
            date=date,
            user=listing.supplier,
            listing=listing,
            defaults={
                "requests_received": 0,
                "requests_fulfilled": 0,
                "food_saved_kg": Decimal("0.00"),
            },
        )
        return analytics

    def increment_metrics(self, food_quantity):
        """Increment metrics with validation"""
        self.requests_received += 1
        self.requests_fulfilled += 1
        self.food_saved_kg += Decimal(str(food_quantity))
        self.full_clean()
        self.save()


class SystemMetrics(BaseModel):
    """Tracks system-wide metrics for platform performance"""

    date = models.DateField(default=timezone.now)

    # User activity
    active_users = models.IntegerField(default=0, help_text="Number of active users")
    new_users = models.IntegerField(
        default=0, help_text="Number of new user registrations"
    )
    business_users_active = models.IntegerField(
        default=0, help_text="Active business users"
    )
    nonprofit_users_active = models.IntegerField(
        default=0, help_text="Active nonprofit users"
    )
    volunteer_users_active = models.IntegerField(
        default=0, help_text="Active volunteer users"
    )
    consumer_users_active = models.IntegerField(
        default=0, help_text="Active consumer users"
    )

    # Platform performance
    new_listings_count = models.IntegerField(
        default=0, help_text="Number of new food listings"
    )
    request_count = models.IntegerField(
        default=0, help_text="Number of food requests created"
    )
    delivery_count = models.IntegerField(
        default=0, help_text="Number of deliveries created"
    )
    avg_response_time = models.FloatField(
        null=True, blank=True, help_text="Average time to respond to requests (hours)"
    )
    avg_transaction_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Average transaction value",
    )

    # Transaction completion
    request_approval_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, help_text="% of requests approved"
    )
    transaction_completion_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="% of transactions completed",
    )
    delivery_completion_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, help_text="% of deliveries completed"
    )
    avg_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0,
        help_text="Average rating of transactions",
    )

    class Meta:
        verbose_name = "System Metrics"
        verbose_name_plural = "System Metrics"
        ordering = ["-date"]
        unique_together = ["date"]  # Only one record per date
        indexes = [models.Index(fields=["date"])]

    def __str__(self):
        return f"System Metrics for {self.date}"

    def clean(self):
        # Validate percentage fields
        for field in [
            "request_approval_rate",
            "transaction_completion_rate",
            "delivery_completion_rate",
        ]:
            value = getattr(self, field)
            if value < 0 or value > 100:
                raise ValidationError({field: "Percentage must be between 0 and 100"})
        # Validate counts are non-negative
        for field in [
            "active_users",
            "new_users",
            "business_users_active",
            "nonprofit_users_active",
            "volunteer_users_active",
            "consumer_users_active",
            "new_listings_count",
            "request_count",
            "delivery_count",
        ]:
            value = getattr(self, field)
            if value < 0:
                raise ValidationError({field: "Count cannot be negative"})

    @classmethod
    def calculate_for_date(cls, date):
        """Calculate system metrics for a specific date"""
        User = get_user_model()

        # Consider a user active if they've logged in within the last 30 days OR if they have any activity today
        active_date_range = {
            "last_login__date__gte": date - timezone.timedelta(days=30),
            "last_login__date__lte": date,
        }

        # Include users who have any activity today (requests, listings, etc.)
        today_active_users = set(
            User.objects.filter(**active_date_range).values_list("id", flat=True)
        )

        # Add users who created listings today
        today_active_users.update(
            FoodListing.objects.filter(created_at__date=date).values_list(
                "supplier_id", flat=True
            )
        )

        # Add users who made requests today
        today_active_users.update(
            FoodRequest.objects.filter(created_at__date=date).values_list(
                "requester_id", flat=True
            )
        )

        # Add users who completed transactions today
        today_active_users.update(
            Transaction.objects.filter(completion_date__date=date).values_list(
                "request__requester_id", flat=True
            )
        )
        today_active_users.update(
            Transaction.objects.filter(completion_date__date=date).values_list(
                "request__listing__supplier_id", flat=True
            )
        )

        # Add users with delivery activity today
        today_active_users.update(
            DeliveryAssignment.objects.filter(
                models.Q(created_at__date=date)  # New delivery assignments
                | models.Q(picked_up_at__date=date)  # Picked up deliveries
                | models.Q(delivered_at__date=date)  # Completed deliveries
            ).values_list("volunteer_id", flat=True)
        )

        # Count active users by type
        active_users = len(today_active_users)

        # Get users who registered today
        new_users = User.objects.filter(date_joined__date=date).count()

        # Count active users by type within today's active users
        business_users_active = User.objects.filter(
            id__in=today_active_users, user_type="BUSINESS"
        ).count()
        nonprofit_users_active = User.objects.filter(
            id__in=today_active_users, user_type="NONPROFIT"
        ).count()
        volunteer_users_active = User.objects.filter(
            id__in=today_active_users, user_type="VOLUNTEER"
        ).count()
        consumer_users_active = User.objects.filter(
            id__in=today_active_users, user_type="CONSUMER"
        ).count()

        # Platform performance metrics
        new_listings = FoodListing.objects.filter(created_at__date=date).count()
        requests_created = FoodRequest.objects.filter(created_at__date=date).count()
        deliveries_created = DeliveryAssignment.objects.filter(
            created_at__date=date
        ).count()

        # Calculate average response time (in hours, float)
        response_times_qs = (
            FoodRequest.objects.filter(
                status__in=["APPROVED", "REJECTED"], updated_at__date=date
            )
            .annotate(
                response_time=ExpressionWrapper(
                    F("updated_at") - F("created_at"),
                    output_field=models.DurationField(),
                )
            )
            .filter(response_time__lte=timedelta(hours=48))  # Ignore outliers > 48 hours
        )
        response_times = response_times_qs.aggregate(avg_time=Avg("response_time"), count=Count("id"))
        avg_response_time = None
        if response_times["count"] > 0 and response_times["avg_time"]:
            # Convert timedelta to hours as float
            total_seconds = response_times["avg_time"].total_seconds()
            avg_response_time = round(total_seconds / 3600, 2)

        # Calculate average transaction value including both commercial and donation listings
        transaction_values = (
            Transaction.objects.filter(completion_date__date=date, status="COMPLETED")
            .annotate(
                value=Case(
                    When(
                        request__listing__listing_type="COMMERCIAL",
                        then=F("request__listing__price")
                        * F("request__quantity_requested"),
                    ),
                    When(
                        request__listing__listing_type="DONATION",
                        then=F("request__quantity_requested")
                        * Value(Decimal("1.00")),  # Base value for donations
                    ),
                    default=Value(Decimal("0.00")),
                    output_field=models.DecimalField(max_digits=10, decimal_places=2),
                )
            )
            .aggregate(avg_value=Avg("value"), count=Count("id"))
        )

        # Calculate request approval rate
        total_requests_processed = FoodRequest.objects.filter(
            updated_at__date=date, status__in=["APPROVED", "REJECTED"]
        ).count()

        approved_requests = FoodRequest.objects.filter(
            updated_at__date=date, status="APPROVED"
        ).count()

        request_approval_rate = Decimal("0.00")
        if total_requests_processed > 0:
            request_approval_rate = (
                Decimal(approved_requests) / Decimal(total_requests_processed) * 100
            )

        # Calculate transaction completion rate
        total_transactions = Transaction.objects.filter(
            transaction_date__date=date
        ).count()

        completed_transactions = Transaction.objects.filter(
            completion_date__date=date, status="COMPLETED"
        ).count()

        transaction_completion_rate = Decimal("0.00")
        if total_transactions > 0:
            transaction_completion_rate = (
                Decimal(completed_transactions) / Decimal(total_transactions) * 100
            )

        # Calculate delivery completion rate
        total_deliveries = DeliveryAssignment.objects.filter(
            created_at__date=date
        ).count()

        completed_deliveries = DeliveryAssignment.objects.filter(
            delivered_at__date=date, status="DELIVERED"
        ).count()

        delivery_completion_rate = Decimal("0.00")
        if total_deliveries > 0:
            delivery_completion_rate = (
                Decimal(completed_deliveries) / Decimal(total_deliveries) * 100
            )

        # Calculate average rating for completed transactions
        completed_transactions_today = Transaction.objects.filter(
            completion_date__date=date, status="COMPLETED"
        )

        avg_rating = Decimal("0.00")
        if completed_transactions_today.exists():
            ratings = Rating.objects.filter(
                transaction__completion_date__date__range=[date, date]
            ).aggregate(avg=Avg("rating"))
            avg_rating = (
                Decimal(str(ratings["avg"])) if ratings["avg"] else Decimal("0.00")
            )

        # Create or update metrics
        metrics, _ = cls.objects.update_or_create(
            date=date,
            defaults={
                "active_users": active_users,
                "new_users": new_users,
                "business_users_active": business_users_active,
                "nonprofit_users_active": nonprofit_users_active,
                "volunteer_users_active": volunteer_users_active,
                "consumer_users_active": consumer_users_active,
                "new_listings_count": new_listings,
                "request_count": requests_created,
                "delivery_count": deliveries_created,
                "avg_response_time": avg_response_time,
                "avg_transaction_value": transaction_values["avg_value"]
                or Decimal("0.00"),
                "request_approval_rate": request_approval_rate,
                "transaction_completion_rate": transaction_completion_rate,
                "delivery_completion_rate": delivery_completion_rate,
                "avg_rating": avg_rating,
            },
        )
        return metrics


class UserActivityLog(BaseModel):
    """Tracks individual user activity on the platform"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(default=timezone.now)
    activity_type = models.CharField(
        max_length=50, help_text="Type of activity performed"
    )
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "-timestamp"]),
            models.Index(fields=["activity_type"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.activity_type} at {self.timestamp}"


class Report(BaseModel):
    """Base model for all types of reports"""

    REPORT_TYPES = [
        ("IMPACT", "Impact Report"),
        ("TRANSACTION", "Transaction Report"),
        ("USER_ACTIVITY", "User Activity Report"),
        ("COMPLIANCE", "Compliance Report"),
        ("SYSTEM", "System Performance Report"),
        ("SUPPLIER", "Supplier Performance Report"),
        ("WASTE_REDUCTION", "Food Waste Reduction Report"),
        ("BENEFICIARY", "Beneficiary Impact Report"),
        ("VOLUNTEER", "Volunteer Performance Report"),
        ("EXPIRY_WASTE", "Listing Expiry & Food Waste Report"),
        ("USER_RETENTION", "User Retention & Churn Report"),
    ]

    SCHEDULE_CHOICES = [
        ("DAILY", "Daily"),
        ("WEEKLY", "Weekly"),
        ("MONTHLY", "Monthly"),
        ("QUARTERLY", "Quarterly"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    report_type = models.CharField(max_length=20, choices=REPORT_TYPES)
    date_generated = models.DateTimeField(default=timezone.now)
    date_range_start = models.DateField()
    date_range_end = models.DateField()
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="generated_reports",
    )
    data = models.JSONField(help_text="Report data in JSON format")
    summary = models.TextField(blank=True)
    is_scheduled = models.BooleanField(default=False)
    schedule_frequency = models.CharField(
        max_length=20, choices=SCHEDULE_CHOICES, null=True, blank=True
    )
    schedule_time = models.TimeField(
        null=True, blank=True
    )  # New field for scheduling time

    class Meta:
        ordering = ["-date_generated"]
        indexes = [
            models.Index(fields=["-date_generated"]),
            models.Index(fields=["report_type"]),
            models.Index(fields=["is_scheduled"]),  # Add index for scheduled reports
            models.Index(fields=["generated_by"]),  # Add index for generated_by lookups
        ]

    def __str__(self):
        return f"{self.get_report_type_display()} - {self.title}"

    def clean(self):
        """Validate report data"""
        super().clean()
        # Validate date range
        if self.date_range_end and self.date_range_start:
            if self.date_range_end < self.date_range_start:
                raise ValidationError("End date cannot be before start date")

        # Validate report data structure
        if not isinstance(self.data, dict):
            raise ValidationError("Report data must be a dictionary")

        required_keys = {
            "IMPACT": ["summary", "daily_trends"],
            "TRANSACTION": ["metrics", "status_breakdown"],
            "USER_ACTIVITY": [
                "total_activities",
                "unique_users",
                "activity_types",
                "user_type_breakdown",
            ],
            "COMPLIANCE": [
                "total_listings",
                "total_checks",
                "passed",
                "failed",
                "compliance_rate",
            ],
            "SYSTEM": ["summary", "daily_trends"],
        }

        if self.report_type in required_keys:
            missing_keys = [
                key for key in required_keys[self.report_type] if key not in self.data
            ]
            if missing_keys:
                raise ValidationError(
                    f"Missing required data fields for {self.get_report_type_display()}: {', '.join(missing_keys)}"
                )

        # Validate scheduled report settings
        if self.is_scheduled and not self.schedule_frequency:
            raise ValidationError(
                "Schedule frequency is required for scheduled reports"
            )
        if self.is_scheduled:
            if not self.schedule_frequency:
                raise ValidationError(
                    "Schedule frequency is required for scheduled reports"
                )
            if self.schedule_frequency == "DAILY" and not self.schedule_time:
                raise ValidationError("Schedule time is required for daily reports")

    def schedule_report(self, frequency, schedule_time=None):
        """Schedule a report with validation and error handling"""
        try:
            self.is_scheduled = True
            self.schedule_frequency = frequency

            # Handle schedule_time for all frequency types, not just DAILY
            if schedule_time:
                try:
                    # Parse the time string into a time object
                    if isinstance(schedule_time, str):
                        # Handle different time formats (HH:MM or HH:MM:SS)
                        time_parts = schedule_time.split(':')
                        if len(time_parts) == 2:
                            hour, minute = map(int, time_parts)
                            self.schedule_time = time(hour, minute)
                        elif len(time_parts) == 3:
                            hour, minute, second = map(int, time_parts)
                            self.schedule_time = time(hour, minute, second)
                        else:
                            raise ValueError(f"Invalid time format: {schedule_time}")
                    elif isinstance(schedule_time, time):
                        self.schedule_time = schedule_time
                    else:
                        raise TypeError("Schedule time must be a string or time object")
                except (ValueError, TypeError) as e:
                    return {
                        "status": "error", 
                        "message": f"Invalid schedule time format: {str(e)}"
                    }
            elif frequency == "DAILY":
                # For daily reports, default to 9 AM if no time provided
                self.schedule_time = time(9, 0)

            self.full_clean()
            self.save()

            return {
                "status": "success",
                "message": f"Report scheduled successfully for {self.get_schedule_frequency_display().lower()} generation",
            }

        except ValidationError as e:
            errors = []
            for field, messages in e.message_dict.items():
                errors.extend(messages)
            return {"status": "error", "message": " ".join(errors)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def unschedule_report(self):
        """Unschedule a report with validation"""
        try:
            if not self.is_scheduled:
                return {"status": "info", "message": "Report was not scheduled"}

            self.is_scheduled = False
            self.schedule_frequency = None
            self.schedule_time = None
            self.save()

            return {"status": "success", "message": "Report unscheduled successfully"}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_next_run_time(self):
        """Calculate the next scheduled run time for this report"""
        if not self.is_scheduled or not self.schedule_frequency:
            return None

        now = timezone.now()
        if self.schedule_frequency == "DAILY":
            next_run = timezone.make_aware(
                datetime.combine(now.date(), self.schedule_time or time(0, 0))
            )
            if next_run <= now:
                next_run += timedelta(days=1)
        elif self.schedule_frequency == "WEEKLY":
            next_run = timezone.make_aware(
                datetime.combine(now.date(), self.schedule_time or time(0, 0))
            )
            while next_run <= now or next_run.weekday() != 0:  # Schedule for Mondays
                next_run += timedelta(days=1)
        elif self.schedule_frequency == "MONTHLY":
            next_run = timezone.make_aware(
                datetime.combine(now.date(), self.schedule_time or time(0, 0))
            )
            while next_run <= now or next_run.day != 1:  # Schedule for 1st of month
                next_run += timedelta(days=1)
        return next_run

    def generate_report(self):
        """Generate the report based on its type and parameters"""
        if not self.report_type:
            raise ValidationError("Report type is required")

        try:
            # Map to appropriate generator methods
            report_generators = {
                "IMPACT": self.__class__.generate_impact_report,
                "TRANSACTION": self.__class__.generate_transaction_report,
                "USER_ACTIVITY": self.__class__.generate_user_activity_report,
                "COMPLIANCE": self.__class__.generate_compliance_report,
                "SYSTEM": self.__class__.generate_system_performance_report,
                "SUPPLIER": self.__class__.generate_supplier_performance_report,
                "WASTE_REDUCTION": self.__class__.generate_waste_reduction_report,
                "BENEFICIARY": self.__class__.generate_beneficiary_impact_report,
                "VOLUNTEER": self.__class__.generate_volunteer_performance_report,
                "EXPIRY_WASTE": self.__class__.generate_expiry_waste_report,
                "USER_RETENTION": self.__class__.generate_user_retention_churn_report,
            }
            
            if self.report_type not in report_generators:
                raise ValueError(f"Unsupported report type: {self.report_type}")

            # Generate a new report using the appropriate class method
            generator_method = report_generators[self.report_type]
            new_report = generator_method(
                start_date=self.date_range_start,
                end_date=self.date_range_end,
                user=self.generated_by,
                title=self.title
            )

            # Copy data from the new report to this report
            self.data = new_report.data
            self.summary = new_report.summary
            self.date_generated = timezone.now()
            
            # Delete the temporary report since we've copied its data
            new_report.delete()
            
            # Save the updated report
            self.save()
            
            return True
        except Exception as e:
            # Log the error but don't raise to allow for user-friendly error messages
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error generating report: {str(e)}")
            raise

    def save(self, *args, **kwargs):
        """Ensure data is valid before saving"""
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def get_recent_reports(cls, limit=10):
        """Get recent reports with optimized querying"""
        return (
            cls.objects.select_related("generated_by")
            .defer("data")  # Defer loading large JSON data field
            .order_by("-date_generated")[:limit]
        )

    @classmethod
    def get_scheduled_reports(cls, active_only=True):
        """Get scheduled reports with optimized querying"""
        qs = cls.objects.select_related("generated_by").filter(is_scheduled=True)
        if active_only:
            qs = qs.filter(date_generated__gte=timezone.now() - timedelta(days=90))
        return qs.defer("data").order_by("-date_generated")

    def export_as_pdf(self) -> HttpResponse:
        """Export report as PDF using reportlab"""
        buffer = BytesIO()
        # Use landscape orientation for wide tables
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),
            rightMargin=50,
            leftMargin=50,
            topMargin=50,
            bottomMargin=50,
            title=self.title,
        )

        elements = []
        styles = getSampleStyleSheet()

        # Enhanced title style
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Heading1"],
            fontSize=24,
            spaceAfter=30,
            textColor=colors.HexColor("#2c3e50"),
            alignment=1,  # Center alignment
        )
        elements.append(Paragraph(str(self.title), title_style))

        # Enhanced info section style
        info_style = ParagraphStyle(
            "InfoStyle",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#34495e"),
            spaceAfter=5,
            bulletIndent=20,
            leftIndent=20,
        )

        try:
            # Format dates
            date_generated = timezone.localtime(self.date_generated)
            date_range_start = timezone.localtime(
                timezone.make_aware(
                    datetime.combine(self.date_range_start, datetime.min.time())
                )
            )
            date_range_end = timezone.localtime(
                timezone.make_aware(
                    datetime.combine(self.date_range_end, datetime.min.time())
                )
            )

            # Add report info
            info_data = [
                f"Report Type: {dict(self.REPORT_TYPES).get(self.report_type, 'Unknown')}",
                f"Generated: {date_generated.strftime('%B %d, %Y at %I:%M %p')}",
                f"Date Range: {date_range_start.strftime('%B %d, %Y')} to {date_range_end.strftime('%B %d, %Y')}",
                f"Generated By: {self.generated_by.get_full_name() if hasattr(self.generated_by, 'get_full_name') else self.generated_by.email}",
            ]

            for info in info_data:
                elements.append(Paragraph(f"• {info}", info_style))

            elements.append(Spacer(1, 20))

            # Add summary with enhanced styling and proper spacing
            if self.summary:
                summary_style = ParagraphStyle(
                    "SummaryStyle",
                    parent=styles["Normal"],
                    fontSize=12,
                    textColor=colors.HexColor("#2c3e50"),
                    backColor=colors.HexColor("#ecf0f1"),
                    borderPadding=15,  # Increased padding
                    borderRadius=5,
                    spaceAfter=20,  # Add space after summary
                    spaceBefore=10,  # Add space before summary
                )
                elements.append(Paragraph("Summary", styles["Heading2"]))
                elements.append(Spacer(1, 10))  # Add space between heading and content
                elements.append(Paragraph(str(self.summary), summary_style))
                elements.append(Spacer(1, 20))

            # Add data sections
            report_data = self.data if isinstance(self.data, dict) else {}

            # Annotations, Aggregate metrics
            if report_data.get("metrics") and isinstance(report_data["metrics"], dict):
                elements.append(Paragraph("Key Metrics", styles["Heading2"]))
                elements.append(Spacer(1, 10))  # Add space after heading

                metrics_data = [
                    [
                        Paragraph("Metric", styles["Normal"]),
                        Paragraph("Value", styles["Normal"]),
                    ]
                ]

                # Format metrics data - exclude nested structures
                formatted_metrics = {}
                for key, value in report_data["metrics"].items():
                    # Skip nested data structures that will be shown in separate tables
                    skip_keys = ['top_suppliers', 'food_categories', 'rescued_by_category', 'peak_rescue_times']
                    # Add expiry waste report keys to skip
                    if self.report_type == 'EXPIRY_WASTE':
                        skip_keys += ['suppliers_with_most_expired', 'expired_by_food_type']
                    if self.report_type == 'BENEFICIARY':
                        skip_keys += ['nutritional_value', 'satisfaction_metrics', 'food_by_beneficiary_type']
                    if self.report_type == 'VOLUNTEER':
                        skip_keys += ['top_volunteers', 'activity_by_day', 'volunteer_reliability']
                    if key in skip_keys:
                        continue
                    
                    # Format metric name to be clearer
                    formatted_key = key.replace("_", " ").title()
                    
                    # Format numeric values with proper decimal places
                    if isinstance(value, (int, float)):
                        if float(value) == int(float(value)):  # whole number
                            formatted_value = "{:,}".format(int(value))
                        else:
                            formatted_value = "{:,.1f}".format(float(value))
                    else:
                        formatted_value = str(value)
                        
                    formatted_metrics[formatted_key] = formatted_value

                # Add formatted metrics to table
                for key, value in formatted_metrics.items():
                    metrics_data.append([key, value])

                if len(metrics_data) > 1:  # if we have data beyond just the header
                    table = Table(metrics_data, colWidths=[250, 250])
                    table.setStyle(
                        TableStyle(
                            [
                                (
                                    "BACKGROUND",
                                    (0, 0),
                                    (-1, 0),
                                    colors.HexColor("#3498db"),
                                ),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, 0), 12),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                                (
                                    "TEXTCOLOR",
                                    (0, 1),
                                    (-1, -1),
                                    colors.HexColor("#2c3e50"),
                                ),
                                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                                ("FONTSIZE", (0, 1), (-1, -1), 10),
                                (
                                    "GRID",
                                    (0, 0),
                                    (-1, -1),
                                    1,
                                    colors.HexColor("#bdc3c7"),
                                ),
                                (
                                    "ROWBACKGROUNDS",
                                    (0, 1),
                                    (-1, -1),
                                    [colors.white, colors.HexColor("#f9f9f9")],
                                ),
                                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 15),
                            ]
                        )
                    )
                    elements.append(table)
                    elements.append(Spacer(1, 20))
                    
                # Add top suppliers table if available
                if 'top_suppliers' in report_data["metrics"] and isinstance(report_data["metrics"]['top_suppliers'], list):
                    elements.append(Paragraph("Top Suppliers", styles["Heading2"]))
                    elements.append(Spacer(1, 10))
                    
                    supplier_data = [
                        ["Supplier", "Transaction Count", "Total Food (kg)"]
                    ]
                    
                    for supplier in report_data["metrics"]['top_suppliers']:
                        if isinstance(supplier, dict):
                            supplier_name = supplier.get('supplier_name', 'Unknown')
                            transaction_count = str(supplier.get('transaction_count', 0))
                            total_food = "{:.1f}".format(float(supplier.get('total_food_kg', 0)))
                            supplier_data.append([supplier_name, transaction_count, total_food])
                    
                    if len(supplier_data) > 1:  # if we have data beyond just the header
                        supplier_table = Table(supplier_data, colWidths=[200, 150, 150])
                        supplier_table.setStyle(
                            TableStyle([
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, 0), 11),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
                                ("ALIGN", (1, 1), (1, -1), "RIGHT"),  # Right align transaction count
                                ("ALIGN", (2, 1), (2, -1), "RIGHT"),  # Right align total food
                            ])
                        )
                        elements.append(supplier_table)
                        elements.append(Spacer(1, 20))
                
                # Add food categories table if available
                if 'food_categories' in report_data["metrics"] and isinstance(report_data["metrics"]['food_categories'], list):
                    elements.append(Paragraph("Food Categories", styles["Heading2"]))
                    elements.append(Spacer(1, 10))
                    
                    category_data = [
                        ["Category", "Count", "Total (kg)"]
                    ]
                    
                    for category in report_data["metrics"]['food_categories']:
                        if isinstance(category, dict):
                            category_type = category.get('listing_type', 'Unknown')
                            count = str(category.get('count', 0))
                            total_kg = "{:.1f}".format(float(category.get('total_kg', 0)))
                            category_data.append([category_type, count, total_kg])
                    
                    if len(category_data) > 1:  # if we have data beyond just the header
                        category_table = Table(category_data, colWidths=[200, 150, 150])
                        category_table.setStyle(
                            TableStyle([
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, 0), 11),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
                                ("ALIGN", (1, 1), (1, -1), "RIGHT"),  # Right align count
                                ("ALIGN", (2, 1), (2, -1), "RIGHT"),  # Right align total kg
                            ])
                        )
                        elements.append(category_table)
                        elements.append(Spacer(1, 20))
                        
                # Add rescued by category table if available (for waste reduction reports)
                if 'rescued_by_category' in report_data["metrics"] and isinstance(report_data["metrics"]['rescued_by_category'], list):
                    elements.append(Paragraph("Rescued By Category", styles["Heading2"]))
                    elements.append(Spacer(1, 10))
                    
                    category_data = [
                        ["Category", "Count", "Total (kg)"]
                    ]
                    
                    for category in report_data["metrics"]['rescued_by_category']:
                        if isinstance(category, dict):
                            category_type = category.get('category', 'Unknown')
                            count = str(category.get('count', 0))
                            total_kg = "{:.1f}".format(float(category.get('total_kg', 0)))
                            category_data.append([category_type, count, total_kg])
                    
                    if len(category_data) > 1:  # if we have data beyond just the header
                        category_table = Table(category_data, colWidths=[200, 150, 150])
                        category_table.setStyle(
                            TableStyle([
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, 0), 11),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
                                ("ALIGN", (1, 1), (1, -1), "RIGHT"),  # Right align count
                                ("ALIGN", (2, 1), (2, -1), "RIGHT"),  # Right align total kg
                            ])
                        )
                        elements.append(category_table)
                        elements.append(Spacer(1, 20))
                
                # Add peak rescue times if available (for waste reduction reports)
                if 'peak_rescue_times' in report_data["metrics"] and isinstance(report_data["metrics"]['peak_rescue_times'], dict):
                    peak_data = report_data["metrics"]['peak_rescue_times']
                    elements.append(Paragraph("Peak Rescue Times", styles["Heading2"]))
                    elements.append(Spacer(1, 10))
                    
                    # Create peak summary text
                    peak_day = peak_data.get('peak_day', {})
                    peak_hour = peak_data.get('peak_hour', {})
                    
                    if peak_day and peak_hour:
                        peak_text = (
                            f"Peak rescue day is {peak_day.get('day_name')} with {peak_day.get('count')} rescues. "
                            f"Peak rescue hour is {peak_hour.get('formatted_hour')} with {peak_hour.get('count')} rescues."
                        )
                        elements.append(Paragraph(peak_text, styles["Normal"]))
                        elements.append(Spacer(1, 15))
                    
                    # Create rescue activity by day table
                    if 'days' in peak_data and peak_data['days']:
                        elements.append(Paragraph("Rescue Activity by Day", styles["Heading3"]))
                        elements.append(Spacer(1, 5))
                        
                        day_data = [["Day", "Rescues"]]
                        for day in peak_data['days']:
                            day_data.append([day.get('day_name', ''), str(day.get('count', 0))])
                            
                        day_table = Table(day_data, colWidths=[150, 100])
                        day_table.setStyle(
                            TableStyle([
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                                ("ALIGN", (0, 0), (-1, 0), "LEFT"),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, 0), 10),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                                ("TOPPADDING", (0, 0), (-1, 0), 8),
                                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
                                ("ALIGN", (1, 1), (1, -1), "RIGHT"),  # Right align count
                            ])
                        )
                        elements.append(day_table)
                        elements.append(Spacer(1, 15))
                        
                    # Create rescue activity by hour table
                    if 'hours' in peak_data and peak_data['hours']:
                        elements.append(Paragraph("Rescue Activity by Hour", styles["Heading3"]))
                        elements.append(Spacer(1, 5))
                        
                        hour_data = [["Hour", "Rescues"]]
                        for hour in peak_data['hours']:
                            hour_data.append([hour.get('formatted_hour', ''), str(hour.get('count', 0))])
                            
                        hour_table = Table(hour_data, colWidths=[150, 100])
                        hour_table.setStyle(
                            TableStyle([
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                                ("ALIGN", (0, 0), (-1, 0), "LEFT"),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, 0), 10),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                                ("TOPPADDING", (0, 0), (-1, 0), 8),
                                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
                                ("ALIGN", (1, 1), (1, -1), "RIGHT"),  # Right align count
                            ])
                        )
                        elements.append(hour_table)
                        elements.append(Spacer(1, 20))
                
                # Add expiry waste report tables
                if self.report_type == 'EXPIRY_WASTE':
                    # Suppliers With Most Expired
                    if 'suppliers_with_most_expired' in report_data["metrics"] and isinstance(report_data["metrics"]['suppliers_with_most_expired'], list):
                        elements.append(Paragraph("Suppliers With Most Expired Listings", styles["Heading2"]))
                        elements.append(Spacer(1, 10))
                        supplier_data = [["Supplier", "Expired Count", "Food Wasted (kg)"]]
                        for supplier in report_data["metrics"]['suppliers_with_most_expired']:
                            supplier_data.append([
                                supplier.get('supplier_name', ''),
                                supplier.get('expired_count', 0),
                                "{:.1f}".format(float(supplier.get('wasted_kg', 0)))
                            ])
                        if len(supplier_data) > 1:
                            supplier_table = Table(supplier_data, colWidths=[200, 120, 120])
                            supplier_table.setStyle(TableStyle([
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e74c3c")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, 0), 11),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
                                ("ALIGN", (1, 1), (2, -1), "RIGHT"),
                            ]))
                            elements.append(supplier_table)
                            elements.append(Spacer(1, 20))
                    # Expired By Food Type
                    if 'expired_by_food_type' in report_data["metrics"] and isinstance(report_data["metrics"]['expired_by_food_type'], list):
                        elements.append(Paragraph("Expired Food By Type", styles["Heading2"]))
                        elements.append(Spacer(1, 10))
                        type_data = [["Food Type", "Count", "Wasted (kg)"]]
                        for food_type in report_data["metrics"]['expired_by_food_type']:
                            type_data.append([
                                food_type.get('type', ''),
                                food_type.get('count', 0),
                                "{:.1f}".format(float(food_type.get('wasted_kg', 0)))
                            ])
                        if len(type_data) > 1:
                            type_table = Table(type_data, colWidths=[200, 120, 120])
                            type_table.setStyle(TableStyle([
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e67e22")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, 0), 11),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
                                ("ALIGN", (1, 1), (2, -1), "RIGHT"),
                            ]))
                            elements.append(type_table)
                            elements.append(Spacer(1, 20))

            # Format the daily trends table
            if (
                report_data.get("daily_trends")
                and isinstance(report_data["daily_trends"], list)
                and report_data["daily_trends"]
            ):
                elements.append(Paragraph("Daily Trends", styles["Heading2"]))
                elements.append(Spacer(1, 10))  # Add space after heading

                first_day = report_data["daily_trends"][0]
                # Format the column headers to be clearer
                headers = ["Date"] + [
                    k.replace("_", " ").title() for k in first_day.keys() if k != "date"
                ]
                table_data = [headers]

                for day in report_data["daily_trends"]:
                    try:
                        date_str = day.get("date", "")
                        if isinstance(date_str, str):
                            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                            formatted_date = date_obj.strftime("%b %d, %Y")
                        else:
                            formatted_date = str(date_str)

                    except (ValueError, TypeError):
                        formatted_date = str(date_str)

                    row = [formatted_date]
                    for key in first_day.keys():
                        if key != "date":
                            value = day.get(key, "")
                            if isinstance(value, (int, float)):
                                formatted_value = (
                                    "{:,.2f}".format(value)
                                    if isinstance(value, float)
                                    else "{:,}".format(value)
                                )
                            else:
                                formatted_value = str(value)
                            row.append(formatted_value)
                    table_data.append(row)

                if table_data:
                    # Dynamically fit columns to landscape page width (letter landscape ~720pt width, minus margins)
                    max_table_width = 700  # points, adjust as needed for margins
                    n_cols = len(headers)
                    min_col_width = 40
                    max_col_width = 120
                    base_width = max_table_width // n_cols
                    col_widths = [max(min_col_width, min(base_width, max_col_width))] * n_cols
                    # Shrink font size if too many columns
                    font_size = 9 if n_cols <= 10 else 7 if n_cols <= 16 else 6
                    table = Table(table_data, colWidths=col_widths, repeatRows=1)
                    table.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, 0), font_size+1),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
                                ("TOPPADDING", (0, 0), (-1, 0), 10),
                                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                                ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#2c3e50")),
                                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                                ("FONTSIZE", (0, 1), (-1, -1), font_size),
                                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
                                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                                ("ALIGN", (0, 1), (0, -1), "LEFT"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                            ]
                        )
                    )
                    elements.append(table)

            # Build the PDF
            doc.build(elements)
            pdf = buffer.getvalue()
            buffer.close()

            # Create response
            response = HttpResponse(content_type="application/pdf")
            response["Content-Disposition"] = (
                f'attachment; filename="{str(self.title).replace(" ", "_")}.pdf"'
            )
            response.write(pdf)
            return response

        except Exception as e:
            print(f"Error generating PDF: {str(e)}")
            raise

    def export_as_csv(self) -> HttpResponse:
        """Export report as CSV"""
        import csv
        from io import StringIO

        # Create the CSV file
        output = StringIO()
        writer = csv.writer(output)

        # Write title
        writer.writerow([self.title])
        writer.writerow([])  # Empty row for spacing

        # Format dates
        date_generated = timezone.localtime(self.date_generated)
        date_range_start = timezone.localtime(
            timezone.make_aware(
                datetime.combine(self.date_range_start, datetime.min.time())
            )
        )
        date_range_end = timezone.localtime(
            timezone.make_aware(
                datetime.combine(self.date_range_end, datetime.min.time())
            )
        )

        # Write report metadata with better formatting
        writer.writerow(["Report Information"])
        writer.writerow(
            ["Report Type", dict(self.REPORT_TYPES).get(self.report_type, "Unknown")]
        )
        writer.writerow(
            ["Generated Date", date_generated.strftime("%B %d, %Y at %I:%M %p")]
        )
        writer.writerow(
            [
                "Date Range",
                f"{date_range_start.strftime('%B %d, %Y')} to {date_range_end.strftime('%B %d, %Y')}",
            ]
        )
        writer.writerow(
            [
                "Generated By",
                self.generated_by.get_full_name()
                if hasattr(self.generated_by, "get_full_name")
                else self.generated_by.email,
            ]
        )
        writer.writerow([])  # Empty row for spacing

        # Write summary if available
        if self.summary:
            writer.writerow(["Summary"])
            writer.writerow([self.summary])
            writer.writerow([])

        # Write data sections
        report_data = self.data if isinstance(self.data, dict) else {}

        # Process metrics dictionary
        metrics_to_write = {}
        if report_data.get("metrics") and isinstance(report_data["metrics"], dict):
            writer.writerow(["Key Metrics"])
            writer.writerow(["Metric", "Value"])  # Column Headers
            
            # Handle all simple metrics (exclude nested structures)
            for key, value in report_data["metrics"].items():
                skip_keys = ['top_suppliers', 'food_categories', 'rescued_by_category', 'peak_rescue_times']
                # Add expiry waste report keys to skip
                if self.report_type == 'EXPIRY_WASTE':
                    skip_keys += ['suppliers_with_most_expired', 'expired_by_food_type']
                if self.report_type == 'BENEFICIARY':
                    skip_keys += ['nutritional_value', 'satisfaction_metrics', 'food_by_beneficiary_type']
                if self.report_type == 'VOLUNTEER':
                    skip_keys += ['top_volunteers', 'activity_by_day', 'volunteer_reliability']
                if key in skip_keys:
                    continue
                
                # Format numbers with commas for thousands and limit decimal places
                if isinstance(value, (int, float)):
                    if value == int(value):
                        formatted_value = f"{int(value):,}"
                    else:
                        formatted_value = f"{value:.1f}"
                else:
                    formatted_value = str(value)
                
                # Format key to be more readable
                formatted_key = key.replace("_", " ").title()
                writer.writerow([formatted_key, formatted_value])

            writer.writerow([])  # Empty row for spacing
            
            # Format Top Suppliers table if available
            if 'top_suppliers' in report_data["metrics"] and isinstance(report_data["metrics"]['top_suppliers'], list):
                writer.writerow(["Top Suppliers"])
                writer.writerow(["Supplier", "Transaction Count", "Total Food (kg)"])
                
                for supplier in report_data["metrics"]['top_suppliers']:
                    if isinstance(supplier, dict):
                        supplier_name = supplier.get('supplier_name', 'Unknown')
                        transaction_count = supplier.get('transaction_count', 0)
                        total_food_kg = f"{float(supplier.get('total_food_kg', 0)):.1f}"
                        writer.writerow([supplier_name, transaction_count, total_food_kg])
                
                writer.writerow([])  # Empty row for spacing
            
            # Format Food Categories table if available
            if 'food_categories' in report_data["metrics"] and isinstance(report_data["metrics"]['food_categories'], list):
                writer.writerow(["Food Categories"])
                writer.writerow(["Category", "Count", "Total (kg)"])
                
                for category in report_data["metrics"]['food_categories']:
                    if isinstance(category, dict):
                        listing_type = category.get('listing_type', 'Unknown')
                        count = category.get('count', 0)
                        total_kg = f"{float(category.get('total_kg', 0)):.1f}"
                        writer.writerow([listing_type, count, total_kg])
                
                writer.writerow([])  # Empty row for spacing
                
            # Format Rescued By Category table if available
            if 'rescued_by_category' in report_data["metrics"] and isinstance(report_data["metrics"]['rescued_by_category'], list):
                writer.writerow(["Rescued By Category"])
                writer.writerow(["Category", "Count", "Total (kg)"])
                
                for category in report_data["metrics"]['rescued_by_category']:
                    if isinstance(category, dict):
                        category_type = category.get('category', 'Unknown')
                        count = category.get('count', 0)
                        total_kg = f"{float(category.get('total_kg', 0)):.1f}"
                        writer.writerow([category_type, count, total_kg])
                
                writer.writerow([])  # Empty row for spacing
                
            # Format Peak Rescue Times if available
            if 'peak_rescue_times' in report_data["metrics"] and isinstance(report_data["metrics"]['peak_rescue_times'], dict):
                peak_data = report_data["metrics"]['peak_rescue_times']
                writer.writerow(["Peak Rescue Times"])
                
                # Write peak summary
                peak_day = peak_data.get('peak_day', {})
                peak_hour = peak_data.get('peak_hour', {})
                
                if peak_day and peak_hour:
                    writer.writerow(["Peak Day", f"{peak_day.get('day_name', 'Unknown')} ({peak_day.get('count', 0)} rescues)"])
                    writer.writerow(["Peak Hour", f"{peak_hour.get('formatted_hour', 'Unknown')} ({peak_hour.get('count', 0)} rescues)"])
                    writer.writerow([])  # Empty row for spacing
                
                # Write activity by day
                if 'days' in peak_data and peak_data['days']:
                    writer.writerow(["Rescue Activity by Day"])
                    writer.writerow(["Day", "Rescues"])
                    
                    for day in peak_data['days']:
                        writer.writerow([day.get('day_name', 'Unknown'), day.get('count', 0)])
                    
                    writer.writerow([])  # Empty row for spacing
                
                # Write activity by hour
                if 'hours' in peak_data and peak_data['hours']:
                    writer.writerow(["Rescue Activity by Hour"])
                    writer.writerow(["Hour", "Rescues"])
                    
                    for hour in peak_data['hours']:
                        writer.writerow([hour.get('formatted_hour', 'Unknown'), hour.get('count', 0)])
                    
                    writer.writerow([])  # Empty row for spacing
            
            # Add expiry waste report tables
            if self.report_type == 'EXPIRY_WASTE':
                # Suppliers With Most Expired
                if 'suppliers_with_most_expired' in report_data["metrics"] and isinstance(report_data["metrics"]['suppliers_with_most_expired'], list):
                    writer.writerow(["Suppliers With Most Expired Listings"])
                    writer.writerow(["Supplier", "Expired Count", "Food Wasted (kg)"])
                    for supplier in report_data["metrics"]['suppliers_with_most_expired']:
                        writer.writerow([
                            supplier.get('supplier_name', ''),
                            supplier.get('expired_count', 0),
                            "{:.1f}".format(float(supplier.get('wasted_kg', 0)))
                        ])
                    writer.writerow([])
                # Expired By Food Type
                if 'expired_by_food_type' in report_data["metrics"] and isinstance(report_data["metrics"]['expired_by_food_type'], list):
                    writer.writerow(["Expired Food By Type"])
                    writer.writerow(["Food Type", "Count", "Wasted (kg)"])
                    for food_type in report_data["metrics"]['expired_by_food_type']:
                        writer.writerow([
                            food_type.get('type', ''),
                            food_type.get('count', 0),
                            "{:.1f}".format(float(food_type.get('wasted_kg', 0)))
                        ])
                    writer.writerow([])

        if (
            report_data.get("daily_trends")
            and isinstance(report_data["daily_trends"], list)
            and report_data["daily_trends"]
        ):
            writer.writerow(["Daily Trends"])

            # Write headers for trends
            first_day = report_data["daily_trends"][0]
            headers = ["Date"] + [key.replace('_', ' ').title() for key in first_day.keys() if key != "date"]
            writer.writerow(headers)

            # Write data rows
            for day in report_data["daily_trends"]:
                # Format dates correctly
                date_str = day.get("date", "")
                try:
                    if isinstance(date_str, str):
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                        formatted_date = date_obj.strftime("%B %d, %Y")
                    else:
                        formatted_date = date_str
                except ValueError:
                    formatted_date = date_str

                row = [formatted_date]
                for key in first_day.keys():
                    if key != "date":
                        value = day.get(key, "")
                        if isinstance(value, float):
                            # Format floating point numbers with 1 decimal place
                            formatted_value = f"{value:.1f}"
                        elif isinstance(value, int):
                            formatted_value = f"{value:,}"
                        else:
                            formatted_value = value
                        row.append(formatted_value)

                writer.writerow(row)

        # Create response
        response = HttpResponse(content_type="text/csv")
        sanitized_title = "".join(
            str(c) for c in str(self.title) if c.isalnum() or c in (" ", "-", "_")
        ).rstrip()
        response["Content-Disposition"] = (
            f'attachment; filename="{sanitized_title}.csv"'
        )
        response.write(output.getvalue())
        return response

    def export_as_excel(self) -> HttpResponse:
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet()

        # Add enhanced formats
        title_format = workbook.add_format(
            {
                "bold": True,
                "font_size": 16,
                "font_color": "#2c3e50",
                "align": "center",
                "valign": "vcenter",
                "border": 0,
            }
        )

        header_format = workbook.add_format(
            {
                "bold": True,
                "font_size": 11,
                "bg_color": "#3498db",
                "font_color": "white",
                "align": "center",
                "valign": "vcenter",
                "border": 1,
                "border_color": "#2980b9",
            }
        )

        subheader_format = workbook.add_format(
            {
                "bold": True,
                "font_size": 11,
                "font_color": "#2c3e50",
                "align": "left",
                "valign": "vcenter",
            }
        )

        cell_format = workbook.add_format(
            {
                "font_size": 10,
                "align": "left",
                "valign": "vcenter",
                "border": 1,
                "border_color": "#bdc3c7",
            }
        )

        number_format = workbook.add_format(
            {
                "font_size": 10,
                "align": "right",
                "valign": "vcenter",
                "border": 1,
                "border_color": "#bdc3c7",
                "num_format": "#,##0.00",
            }
        )

        date_format = workbook.add_format(
            {
                "font_size": 10,
                "align": "left",
                "valign": "vcenter",
                "border": 1,
                "border_color": "#bdc3c7",
                "num_format": "mmm d yyyy",
            }
        )

        # Set column widths
        worksheet.set_column("A:A", 25)  # Date/Label column
        worksheet.set_column("B:Z", 15)  # Data columns

        current_row = 0

        # Write title
        worksheet.merge_range(current_row, 0, current_row, 4, self.title, title_format)
        current_row += 2

        # Write report metadata
        metadata = [
            ["Report Type:", self.get_report_type_display()],
            ["Generated:", self.date_generated.strftime("%B %d, %Y at %I:%M %p")],
            [
                "Date Range:",
                f"{self.date_range_start.strftime('%B %d, %Y')} to {self.date_range_end.strftime('%B %d, %Y')}",
            ],
            [
                "Generated By:",
                self.generated_by.get_full_name() or self.generated_by.email,
            ],
        ]

        for label, value in metadata:
            worksheet.write(current_row, 0, label, subheader_format)
            worksheet.write(current_row, 1, value, cell_format)
            current_row += 1

        current_row += 1

        # Get report data
        report_data = self.data if isinstance(self.data, dict) else {}

        # Write summary if available
        if self.summary:
            worksheet.merge_range(
                current_row, 0, current_row, 4, "Summary", header_format
            )
            current_row += 1
            worksheet.merge_range(
                current_row, 0, current_row, 4, self.summary, cell_format
            )
            current_row += 2

        # Handle report type specific data
        if self.report_type == "IMPACT":
            if report_data.get("summary"):
                worksheet.merge_range(
                    current_row, 0, current_row, 4, "Impact Metrics", header_format
                )
                current_row += 1
                for key, value in report_data["summary"].items():
                    worksheet.write(
                        current_row, 0, key.replace("_", " ").title(), cell_format
                    )
                    if isinstance(value, (int, float)):
                        worksheet.write(current_row, 1, float(value), number_format)
                    else:
                        worksheet.write(current_row, 1, str(value), cell_format)
                    current_row += 1
                current_row += 1

        elif self.report_type == "TRANSACTION":
            if report_data.get("metrics"):
                worksheet.merge_range(
                    current_row, 0, current_row, 4, "Transaction Metrics", header_format
                )
                current_row += 1
                for key, value in report_data["metrics"].items():
                    worksheet.write(
                        current_row, 0, key.replace("_", " ").title(), cell_format
                    )
                    if isinstance(value, (int, float)):
                        worksheet.write(current_row, 1, float(value), number_format)
                    else:
                        worksheet.write(current_row, 1, str(value), cell_format)
                    current_row += 1
                current_row += 1

            if report_data.get("status_breakdown"):
                worksheet.merge_range(
                    current_row, 0, current_row, 4, "Status Breakdown", header_format
                )
                current_row += 1
                for status, count in report_data["status_breakdown"].items():
                    worksheet.write(
                        current_row, 0, status.replace("_", " ").title(), cell_format
                    )
                    worksheet.write(current_row, 1, int(count), number_format)
                    current_row += 1
                current_row += 1

        elif self.report_type == "USER_ACTIVITY":
            metrics_map = {
                "total_activities": "Total Activities",
                "unique_users": "Unique Users",
                "activity_types": "Activity Types",
                "user_type_breakdown": "User Type Distribution",
            }

            worksheet.merge_range(
                current_row, 0, current_row, 4, "User Activity Metrics", header_format
            )
            current_row += 1

            for key, label in metrics_map.items():
                value = report_data.get(key)
                if isinstance(value, (list, dict)):
                    worksheet.write(current_row, 0, label, header_format)
                    current_row += 1
                    if key == "activity_types":
                        for activity in value:
                            worksheet.write(
                                current_row, 0, activity["activity_type"], cell_format
                            )
                            worksheet.write(
                                current_row, 1, activity["count"], number_format
                            )
                            current_row += 1
                    elif key == "user_type_breakdown":
                        for breakdown in value:
                            worksheet.write(
                                current_row, 0, breakdown["user_type"], cell_format
                            )
                            worksheet.write(
                                current_row, 1, breakdown["count"], number_format
                            )
                            current_row += 1
                else:
                    worksheet.write(current_row, 0, label, cell_format)
                    worksheet.write(
                        current_row, 1, value if value is not None else 0, number_format
                    )
                    current_row += 1
                current_row += 1

        elif self.report_type == "COMPLIANCE":
            worksheet.merge_range(
                current_row, 0, current_row, 4, "Compliance Metrics", header_format
            )
            current_row += 1

            for key, value in report_data.items():
                if key != "daily_trends":
                    worksheet.write(
                        current_row, 0, key.replace("_", " ").title(), cell_format
                    )
                    if isinstance(value, (int, float)):
                        worksheet.write(current_row, 1, float(value), number_format)
                    else:
                        worksheet.write(current_row, 1, str(value), cell_format)
                    current_row += 1
            current_row += 1

        elif self.report_type == "SYSTEM":
            # System metrics section
            if report_data.get("system_metrics"):
                worksheet.merge_range(
                    current_row, 0, current_row, 4, "System Metrics", header_format
                )
                current_row += 1
                for key, value in report_data["system_metrics"].items():
                    worksheet.write(
                        current_row, 0, key.replace("_", " ").title(), cell_format
                    )
                    if isinstance(value, (int, float)):
                        worksheet.write(current_row, 1, float(value), number_format)
                    else:
                        worksheet.write(current_row, 1, str(value), cell_format)
                    current_row += 1
                current_row += 1

            # Resource metrics section
            if report_data.get("resource_metrics"):
                worksheet.merge_range(
                    current_row, 0, current_row, 4, "Resource Metrics", header_format
                )
                current_row += 1
                for key, value in report_data["resource_metrics"].items():
                    worksheet.write(
                        current_row, 0, key.replace("_", " ").title(), cell_format
                    )
                    if isinstance(value, (int, float)):
                        worksheet.write(current_row, 1, float(value), number_format)
                    else:
                        worksheet.write(current_row, 1, str(value), cell_format)
                    current_row += 1
                current_row += 1

        # Write daily trends if available (common for Impact and System reports)
        if report_data.get("daily_trends"):
            worksheet.merge_range(
                current_row, 0, current_row, 4, "Daily Trends", header_format
            )
            current_row += 1

            # Write headers
            headers = ["Date"]
            if report_data["daily_trends"]:
                first_day = report_data["daily_trends"][0]
                for key in first_day.keys():
                    if key != "date":
                        headers.append(key.replace("_", " ").title())

                for col, header in enumerate(headers):
                    worksheet.write(current_row, col, header, header_format)

                current_row += 1

                # Write daily data
                for day in report_data["daily_trends"]:
                    try:
                        # Handle date column
                        date_str = day.get("date", "")
                        if isinstance(date_str, str):
                            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                            worksheet.write(current_row, 0, date_obj, date_format)
                        else:
                            worksheet.write(current_row, 0, str(date_str), cell_format)

                        # Handle other columns
                        col = 1
                        for key in first_day.keys():
                            if key != "date":
                                value = day.get(key, "")
                                if isinstance(value, (int, float)):
                                    worksheet.write(
                                        current_row, col, float(value), number_format
                                    )
                                else:
                                    worksheet.write(
                                        current_row, col, str(value), cell_format
                                    )
                                col += 1
                        current_row += 1
                    except (ValueError, TypeError) as e:
                        print(f"Error processing day {day}: {str(e)}")
                        continue

        # Auto-adjust column widths based on content
        for col in range(10):  # Adjust up to 10 columns
            worksheet.autofit()

        workbook.close()

        # Create response
        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        sanitized_title = "".join(
            c for c in str(self.title) if c.isalnum() or c in (" ", "-", "_")
        ).rstrip()
        response["Content-Disposition"] = (
            f'attachment; filename="{sanitized_title}.xlsx"'
        )
        return response

    @classmethod
    def generate_impact_report(cls, start_date, end_date, user, title=None):
        """Generate impact report for the specified date range"""
        metrics = ImpactMetrics.objects.filter(
            date__range=[start_date, end_date]
        ).aggregate(
            total_food=Sum("food_redistributed_kg"),
            total_co2=Sum("co2_emissions_saved"),
            total_meals=Sum("meals_provided"),
            total_value=Sum("monetary_value_saved"),
        )

        # Ensure metrics are not None
        for key in metrics:
            metrics[key] = float(metrics[key] if metrics[key] is not None else 0)

        # Get the daily metrics cleaned and properly formatted
        daily_metrics = list(
            ImpactMetrics.objects.filter(date__range=[start_date, end_date])
            .values("date")
            .annotate(
                food=Sum("food_redistributed_kg"),
                co2=Sum("co2_emissions_saved"),
                meals=Sum("meals_provided"),
                value=Sum("monetary_value_saved"),
            )
            .order_by("date")
        )

        # Initialize empty metrics from the database
        formatted_daily_metrics = []
        for metric in daily_metrics:
            formatted_metric = {
                "date": metric["date"].strftime("%Y-%m-%d"),
                "food_saved": float(metric["food"] or 0),
                "co2_saved": float(metric["co2"] or 0),
                "meals_provided": int(metric["meals"] or 0),
                "value_saved": float(metric["value"] or 0),
            }
            formatted_daily_metrics.append(formatted_metric)

        # If no daily metrics generated
        if not formatted_daily_metrics:
            formatted_daily_metrics = [
                {
                    "date": start_date.strftime("%Y-%m-%d"),
                    "food_saved": 0,
                    "co2_saved": 0,
                    "meals_provided": 0,
                    "value_saved": 0,
                }
            ]

        # Enforce good data structure
        report_data = {"summary": metrics, "daily_trends": formatted_daily_metrics}

        return cls.objects.create(
            title=title or f"Impact Report {start_date} to {end_date}",
            report_type="IMPACT",
            date_range_start=start_date,
            date_range_end=end_date,
            generated_by=user,
            data=report_data,
            summary=f"Total food redistributed: {metrics['total_food']:.1f}kg, CO2 saved: {metrics['total_co2']:.1f}kg, Meals provided: {int(metrics['total_meals'])}, Value saved: ${metrics['total_value']:.2f}",
        )

    @classmethod
    def generate_transaction_report(cls, start_date, end_date, user, title=None):
        """Generate transaction report for the specified date range"""
        transactions = Transaction.objects.filter(
            transaction_date__date__range=[start_date, end_date]
        )

        # Use only the info that can be used with transactions
        metrics = {
            "total_count": transactions.count(),
            "completed_count": transactions.filter(status="COMPLETED").count(),
            "total_value": 0,  # Will count below
        }

        # Calculate total counts to avoid SQLite issues
        total_value = 0
        for transaction in transactions:
            if (
                transaction.request
                and transaction.request.listing
                and transaction.request.listing.price
            ):
                total_value += float(transaction.request.listing.price)
        metrics["total_value"] = total_value

        # Here we will get the status counts
        status_counts = {}
        for status_code, status_label in Transaction.TransactionStatus.choices:
            status_counts[status_code] = transactions.filter(status=status_code).count()

        # Build the summary of the transaction
        summary = f"Total transactions: {metrics['total_count']}, Completed: {metrics['completed_count']}, Total value: ${metrics['total_value'] or 0}"

        return cls.objects.create(
            title=title or f"Transaction Report {start_date} to {end_date}",
            report_type="TRANSACTION",
            date_range_start=start_date,
            date_range_end=end_date,
            generated_by=user,
            data={
                "metrics": metrics,
                "status_breakdown": status_counts,
            },
            summary=summary,
        )

    @classmethod
    def generate_user_activity_report(cls, start_date, end_date, user, title=None):
        """Generate user activity report for the specified date range"""
        User = get_user_model()
        activities = UserActivityLog.objects.filter(
            timestamp__date__range=[start_date, end_date]
        )

        metrics = {
            "total_activities": activities.count(),
            "unique_users": activities.values("user").distinct().count(),
            "activity_types": list(
                activities.values("activity_type")
                .annotate(count=Count("id"))
                .order_by("-count")
            ),
            "user_type_breakdown": list(
                User.objects.filter(last_login__date__range=[start_date, end_date])
                .values("user_type")
                .annotate(count=Count("id"))
            ),
        }

        return cls.objects.create(
            title=title or f"User Activity Report {start_date} to {end_date}",
            report_type="USER_ACTIVITY",
            date_range_start=start_date,
            date_range_end=end_date,
            generated_by=user,
            data=metrics,
            summary=f"Total activities: {metrics['total_activities']}, Unique users: {metrics['unique_users']}",
        )

    @classmethod
    def generate_compliance_report(
        cls, start_date, end_date, user, title: Optional[str] = None
    ) -> "Report":
        """Generate compliance report for the specified date range"""
        compliance_metrics: Dict[str, Union[int, float]] = {
            "total_listings": 0,
            "total_checks": 0,
            "passed": 0,
            "failed": 0,
            "unchecked": 0,
            "compliance_checks_created": 0,
            "compliance_rate": 0.0,
        }

        try:
            listings = FoodListing.objects.filter(
                created_at__date__range=[start_date, end_date]
            )

            if listings.exists():
                compliance_metrics["total_listings"] = listings.count()

                for listing in listings:
                    try:
                        check, created = ComplianceCheck.objects.get_or_create(
                            listing=listing,
                            defaults={
                                "checked_by": user,
                                "is_compliant": True,
                                "notes": "Auto-generated during report creation",
                            },
                        )

                        compliance_metrics["total_checks"] += 1
                        if created:
                            compliance_metrics["compliance_checks_created"] += 1

                        if check.is_compliant:
                            compliance_metrics["passed"] += 1
                        else:
                            compliance_metrics["failed"] += 1
                    except (
                        DBError,
                        ObjectDoesNotExist,
                        AttributeError,
                        ValueError,
                    ):
                        # Handle the error here
                        continue

                if compliance_metrics["total_checks"] > 0:
                    compliance_metrics["compliance_rate"] = float(
                        (
                            compliance_metrics["passed"]
                            / compliance_metrics["total_checks"]
                        )
                        * 100
                    )
        except (DBError, ObjectDoesNotExist, AttributeError, ValueError):
            # If any error happens then just go to the default empty metrics
            pass

        summary = (
            f"Total Listings: {compliance_metrics['total_listings']}, "
            f"Checked: {compliance_metrics['total_checks']}, "
            f"Compliance Rate: {compliance_metrics['compliance_rate']:.1f}%, "
            f"New Compliance Checks: {compliance_metrics['compliance_checks_created']}"
        )

        return cls.objects.create(
            title=title or f"Compliance Report {start_date} to {end_date}",
            report_type="COMPLIANCE",
            date_range_start=start_date,
            date_range_end=end_date,
            generated_by=user,
            data=compliance_metrics,
            summary=summary,
        )

    @classmethod
    def generate_system_performance_report(cls, start_date, end_date, user, title=None):
        """Generate system performance report for the specified date range"""
        # Get aggregate system metrics
        metrics = SystemMetrics.objects.filter(
            date__range=[start_date, end_date]
        ).aggregate(
            avg_response_time=Avg("avg_response_time"),
            avg_transaction_completion=Avg("transaction_completion_rate"),
            avg_request_approval=Avg("request_approval_rate"),
            avg_delivery_completion=Avg("delivery_completion_rate"),
            total_active_users=Sum("active_users"),
            total_new_users=Sum("new_users"),
        )

        # Ensure absence of None values in other metrics
        for key in metrics:
            metrics[key] = float(metrics[key] if metrics[key] is not None else 0)

        # Collect the daily metrics for trending
        daily_metrics = list(
            SystemMetrics.objects.filter(date__range=[start_date, end_date])
            .values("date")
            .annotate(
                active_users=Sum("active_users"),
                response_time=Avg("avg_response_time"),
                completion_rate=Avg("transaction_completion_rate"),
            )
            .order_by("date")
        )

        # Initialize empty metrics after database entries
        formatted_daily_metrics = []
        for metric in daily_metrics:
            formatted_metric = {
                "date": metric["date"].strftime("%Y-%m-%d"),
                "active_users": int(metric["active_users"] or 0),
                "response_time": float(metric["response_time"] or 0),
                "completion_rate": float(metric["completion_rate"] or 0),
            }
            formatted_daily_metrics.append(formatted_metric)

        # If we have no entries in daily metrics then we add an empty one
        if not formatted_daily_metrics:
            formatted_daily_metrics = [
                {
                    "date": start_date.strftime("%Y-%m-%d"),
                    "active_users": 0,
                    "response_time": 0,
                    "completion_rate": 0,
                }
            ]

        report_data = {
            "summary": metrics,
            "daily_trends": formatted_daily_metrics,
            "system_metrics": {
                "server_health": 100.0,  # Default values while having no data
                "avg_response_time": float(metrics["avg_response_time"] or 0),
                "error_rate": 0.0,
                "resource_usage": 0.0,
            },
            "resource_metrics": {
                "cpu_usage": 0.0,
                "memory_usage": 0.0,
                "disk_usage": 0.0,
                "network_usage": 0.0,
                "cpu_alert": False,
                "memory_alert": False,
                "disk_alert": False,
                "network_alert": False,
                "cpu_peak": 0.0,
                "memory_peak": 0.0,
                "disk_peak": 0.0,
                "network_peak": 0.0,
            },
        }

        return cls.objects.create(
            title=title or f"System Performance Report {start_date} to {end_date}",
            report_type="SYSTEM",
            date_range_start=start_date,
            date_range_end=end_date,
            generated_by=user,
            data=report_data,
            summary=f"Avg completion rate: {metrics['avg_transaction_completion']:.1f}%, Response time: {metrics['avg_response_time']:.2f} hours, Active users: {metrics['total_active_users']}",
        )

    @classmethod
    def generate_supplier_performance_report(cls, start_date, end_date, user, title=None):
        """Generate supplier performance report for the specified date range"""
        
        # Get supplier data from transactions
        User = get_user_model()
        suppliers = User.objects.filter(
            user_type="BUSINESS",
            food_listings__created_at__date__range=[start_date, end_date]
        ).distinct()
        
        # Calculate key metrics
        supplier_reliability = calculate_supplier_reliability(start_date, end_date)
        supplier_growth = calculate_supplier_growth(start_date, end_date)
        top_suppliers = get_top_suppliers(start_date, end_date)
        food_categories = get_food_categories_by_supplier(start_date, end_date)
        avg_quality_rating = calculate_avg_quality_rating_by_supplier(start_date, end_date)
        on_time_delivery = get_delivery_performance(start_date, end_date)
        
        # Process suppliers' transaction data
        supplier_transactions = Transaction.objects.filter(
            request__listing__supplier__user_type="BUSINESS",
            transaction_date__date__range=[start_date, end_date]
        )
        
        total_food_volume = supplier_transactions.filter(
            status="COMPLETED"
        ).aggregate(
            total_kg=Sum('request__quantity_requested')
        )['total_kg'] or 0
        
        # Get daily metrics for trends
        daily_metrics = list(
            Transaction.objects.filter(
                request__listing__supplier__user_type="BUSINESS",
                transaction_date__date__range=[start_date, end_date]
            ).annotate(date=TruncDay('transaction_date'))
            .values('date')
            .annotate(
                daily_volume=Sum('request__quantity_requested', filter=Q(status="COMPLETED")),
                daily_transactions=Count('id'),
                completed_transactions=Count('id', filter=Q(status="COMPLETED"))
            ).order_by('date')
        )
        
        # Format daily metrics
        formatted_daily_metrics = []
        for metric in daily_metrics:
            success_rate = 0
            if metric['daily_transactions'] > 0:
                success_rate = (metric['completed_transactions'] / metric['daily_transactions']) * 100
                
            formatted_metric = {
                'date': metric['date'].strftime('%Y-%m-%d'),
                'food_volume': float(metric['daily_volume'] or 0),
                'transactions': metric['daily_transactions'],
                'success_rate': float(success_rate),
            }
            formatted_daily_metrics.append(formatted_metric)
        
        # If no data, provide empty placeholder
        if not formatted_daily_metrics:
            formatted_daily_metrics = [{
                'date': start_date.strftime('%Y-%m-%d'),
                'food_volume': 0,
                'transactions': 0,
                'success_rate': 0,
            }]
        
        # Compile all metrics
        metrics = {
            "total_suppliers": suppliers.count(),
            # Count distinct suppliers with completed transactions in the date range
            "active_suppliers": Transaction.objects.filter(
                request__listing__supplier__user_type="BUSINESS",
                transaction_date__date__range=[start_date, end_date],
                status="COMPLETED",
            ).values("request__listing__supplier").distinct().count(),
            "total_food_volume": float(total_food_volume),
            "supplier_reliability": float(supplier_reliability),
            "supplier_growth": float(supplier_growth),
            "avg_quality_rating": float(avg_quality_rating),
            "on_time_delivery_rate": float(on_time_delivery),
            "top_suppliers": top_suppliers,
            "food_categories": food_categories,
        }
        
        # Create report data structure
        report_data = {
            "metrics": metrics,
            "daily_trends": formatted_daily_metrics
        }
        # Normalize data to valid JSON by round-tripping through json
        import json
        report_data = json.loads(json.dumps(report_data))
        
        # Create summary text
        summary = (
            f"Total active suppliers: {metrics['active_suppliers']}, "
            f"Total food volume: {metrics['total_food_volume']:.1f}kg, "
            f"Avg reliability: {metrics['supplier_reliability']:.1f}%, "
            f"Quality rating: {metrics['avg_quality_rating']:.1f}/5"
        )
        
        return cls.objects.create(
            title=title or f"Supplier Performance Report {start_date} to {end_date}",
            report_type="SUPPLIER",
            date_range_start=start_date,
            date_range_end=end_date,
            generated_by=user,
            data=report_data,
            summary=summary
        )

    @classmethod
    def generate_waste_reduction_report(cls, start_date, end_date, user, title=None):
        """Generate food waste reduction report for the specified date range"""
        
        # Get listings that were successfully rescued (completed transactions)
        rescued_listings = Transaction.objects.filter(
            status="COMPLETED",
            completion_date__date__range=[start_date, end_date]
        )
        
        # Calculate total food rescued
        total_food_rescued = rescued_listings.aggregate(
            total_kg=Sum('request__quantity_requested')
        )['total_kg'] or 0
        
        # Calculate average time to rescue
        avg_rescue_time = calculate_avg_rescue_time(start_date, end_date)
        
        # Get rescued food by category
        rescued_by_category = get_rescued_food_by_category(start_date, end_date)
        
        # Analyze peak rescue times
        peak_rescue_times = analyze_peak_rescue_times(start_date, end_date)
        
        # Get daily waste reduction trend
        waste_reduction_trend = get_waste_reduction_trend(start_date, end_date)
        
        # Calculate economic value and environmental impact
        economic_value = float(total_food_rescued) * 3.0  # $3 per kg food on average
        co2_saved = float(total_food_rescued) * 2.5  # 2.5 kg CO2 per kg food saved
        
        # Compile metrics
        metrics = {
            "total_food_rescued_kg": float(total_food_rescued),
            "avg_time_to_rescue_hours": float(avg_rescue_time),
            "total_successful_rescues": rescued_listings.count(),
            "economic_value_saved": float(economic_value),
            "co2_saved_kg": float(co2_saved),
            "rescued_by_category": rescued_by_category,
            "peak_rescue_times": peak_rescue_times,
        }
        
        # Create report data structure
        report_data = {
            "metrics": metrics,
            "daily_trends": waste_reduction_trend
        }
        
        # Create summary text
        summary = (
            f"Total food rescued: {metrics['total_food_rescued_kg']:.1f}kg, "
            f"CO2 saved: {metrics['co2_saved_kg']:.1f}kg, "
            f"Economic value: ${metrics['economic_value_saved']:.2f}, "
            f"Avg rescue time: {metrics['avg_time_to_rescue_hours']:.1f} hours"
        )
        
        return cls.objects.create(
            title=title or f"Food Waste Reduction Report {start_date} to {end_date}",
            report_type="WASTE_REDUCTION",
            date_range_start=start_date,
            date_range_end=end_date,
            generated_by=user,
            data=report_data,
            summary=summary
        )

    @classmethod
    def generate_beneficiary_impact_report(cls, start_date, end_date, user, title=None):
        """Generate beneficiary impact report for the specified date range"""
        
        # Get recipient/nonprofit data
        User = get_user_model()
        recipients = User.objects.filter(
            user_type__in=["NONPROFIT", "CONSUMER"],
            food_requests__transaction__transaction_date__date__range=[start_date, end_date],
            food_requests__transaction__status="COMPLETED"
        ).distinct()
        
        # Calculate metrics
        metrics = {
            "total_beneficiaries": recipients.count(),
            "new_beneficiaries": calculate_new_beneficiaries(start_date, end_date),
            "food_by_beneficiary_type": calculate_food_by_beneficiary_type(start_date, end_date),
            "estimated_people_served": calculate_people_served(start_date, end_date),
            "nutritional_value": calculate_nutritional_value(start_date, end_date),
            "cost_savings": calculate_beneficiary_savings(start_date, end_date),
            "satisfaction_metrics": get_satisfaction_metrics(start_date, end_date),
        }
        
        # Get daily data for trend analysis
        daily_data = Transaction.objects.filter(
            status="COMPLETED",
            completion_date__date__range=[start_date, end_date],
            request__requester__user_type__in=["NONPROFIT", "CONSUMER"]
        ).annotate(
            date=TruncDay('completion_date')
        ).values('date').annotate(
            food_received=Sum('request__quantity_requested'),
            transaction_count=Count('id'),
            beneficiaries_count=Count('request__requester', distinct=True)
        ).order_by('date')
        
        # Format daily trends
        trends = []
        for day in daily_data:
            trends.append({
                'date': day['date'].strftime('%Y-%m-%d'),
                'food_received': float(day['food_received'] or 0),
                'transaction_count': day['transaction_count'],
                'beneficiaries_count': day['beneficiaries_count']
            })
        
        # If no data, provide an empty placeholder
        if not trends:
            trends = [{
                'date': start_date.strftime('%Y-%m-%d'),
                'food_received': 0,
                'transaction_count': 0,
                'beneficiaries_count': 0
            }]
        
        # Create report data
        report_data = {
            "metrics": metrics,
            "daily_trends": trends
        }
        
        # Create summary text
        summary = (
            f"Beneficiaries served: {metrics['total_beneficiaries']}, "
            f"Est. people reached: {metrics['estimated_people_served']}, "
            f"Cost savings: ${metrics['cost_savings']:.2f}"
        )
        
        return cls.objects.create(
            title=title or f"Beneficiary Impact Report {start_date} to {end_date}",
            report_type="BENEFICIARY",
            date_range_start=start_date,
            date_range_end=end_date,
            generated_by=user,
            data=report_data,
            summary=summary
        )

    @classmethod
    def generate_volunteer_performance_report(cls, start_date, end_date, user, title=None):
        """Generate volunteer performance report for the specified date range"""
        # Get User model for volunteer data
        User = get_user_model()
        
        # Get active volunteers with deliveries in the date range
        active_volunteers = User.objects.filter(
            user_type="VOLUNTEER",
            deliveries__created_at__date__range=[start_date, end_date]
        ).distinct()
        
        # Get all deliveries in the date range
        deliveries = DeliveryAssignment.objects.filter(
            created_at__date__range=[start_date, end_date]
        )
        
        # Calculate key metrics
        total_deliveries = deliveries.count()
        completed_deliveries = deliveries.filter(status="DELIVERED").count()
        failed_deliveries = deliveries.filter(status="FAILED").count()
        
        # Calculate delivery completion rate
        completion_rate = 0
        if total_deliveries > 0:
            completion_rate = (completed_deliveries / total_deliveries) * 100
        
        # Calculate total food delivered (in kg)
        total_food_delivered = deliveries.filter(
            status="DELIVERED"
        ).aggregate(
            total_kg=Sum('estimated_weight')
        )['total_kg'] or 0
        
        # Calculate average delivery time (from assignment to delivery)
        completed_with_times = deliveries.filter(
            status="DELIVERED",
            assigned_at__isnull=False,
            delivered_at__isnull=False
        )
        
        avg_delivery_time_hours = 0
        if completed_with_times.exists():
            # Calculate time difference in hours for each delivery
            total_hours = 0
            count = 0
            
            for delivery in completed_with_times:
                if delivery.assigned_at and delivery.delivered_at:
                    time_diff = (delivery.delivered_at - delivery.assigned_at).total_seconds() / 3600
                    
                    # Include only reasonable values (avoid negative or extreme outliers)
                    if 0 <= time_diff <= 24:  # Limit to 24 hours to avoid outliers
                        total_hours += time_diff
                        count += 1
            
            if count > 0:
                avg_delivery_time_hours = round(total_hours / count, 2)
        
        # Calculate on-time delivery rate
        # Define on-time as: delivered before delivery_window_end
        on_time_deliveries = deliveries.filter(
            status="DELIVERED",
            delivered_at__isnull=False
        ).filter(
            delivered_at__lt=F('delivery_window_end')
        ).count()
        
        on_time_rate = 0
        if completed_deliveries > 0:
            on_time_rate = (on_time_deliveries / completed_deliveries) * 100
        
        # Get top performing volunteers by number of deliveries
        top_volunteers = get_top_volunteers(start_date, end_date)
        
        # Get volunteer reliability data
        volunteer_reliability = calculate_volunteer_reliability(start_date, end_date)
        
        # Get volunteer activity by day of week
        activity_by_day = get_volunteer_activity_by_day(start_date, end_date)
        
        # Compile all metrics
        metrics = {
            "total_active_volunteers": active_volunteers.count(),
            "total_deliveries": total_deliveries,
            "completed_deliveries": completed_deliveries,
            "failed_deliveries": failed_deliveries,
            "completion_rate": float(completion_rate),
            "total_food_delivered_kg": float(total_food_delivered),
            "avg_delivery_time_hours": float(avg_delivery_time_hours),
            "on_time_delivery_rate": float(on_time_rate),
            "top_volunteers": top_volunteers,
            "volunteer_reliability": volunteer_reliability,
            "activity_by_day": activity_by_day
        }
        
        # Get daily volunteer performance for trends
        daily_performance = get_daily_volunteer_performance(start_date, end_date)
        
        # Create report data structure
        report_data = {
            "metrics": metrics,
            "daily_trends": daily_performance
        }
        
        # Create summary text
        summary = (
            f"Active volunteers: {metrics['total_active_volunteers']}, "
            f"Completed deliveries: {metrics['completed_deliveries']}, "
            f"Food delivered: {metrics['total_food_delivered_kg']:.1f}kg, "
            f"On-time rate: {metrics['on_time_delivery_rate']:.1f}%"
        )
        
        return cls.objects.create(
            title=title or f"Volunteer Performance Report {start_date} to {end_date}",
            report_type="VOLUNTEER",
            date_range_start=start_date,
            date_range_end=end_date,
            generated_by=user,
            data=report_data,
            summary=summary
        )

    @classmethod
    def generate_expiry_waste_report(cls, start_date, end_date, user, title=None):
        """Generate listing expiry and food waste report for the specified date range"""
        
        # Get all expired listings in the date range - listings that reached their expiry date
        expired_listings = FoodListing.objects.filter(
            models.Q(status="EXPIRED") | 
            models.Q(expiry_date__date__range=[start_date, end_date], expiry_date__lte=timezone.now()),
            created_at__date__range=[start_date, end_date]
        )
        
        # Use Transaction to get rescued listings
        rescued_transactions = Transaction.objects.filter(
            status="COMPLETED",
            completion_date__date__range=[start_date, end_date]
        )
        rescued_listing_ids = rescued_transactions.values_list("request__listing_id", flat=True).distinct()
        rescued_listings_count = rescued_listing_ids.count()
        
        # Calculate key metrics
        total_listings = FoodListing.objects.filter(
            created_at__date__range=[start_date, end_date]
        ).count()
        
        expired_count = expired_listings.count()
        rescued_count = rescued_listings_count
        
        # Calculate waste percentage
        waste_percentage = 0
        if total_listings > 0:
            waste_percentage = (expired_count / total_listings) * 100
        
        # Calculate rescue percentage
        rescue_percentage = 0
        if total_listings > 0:
            rescue_percentage = (rescued_count / total_listings) * 100
            
        # Calculate total food wasted (kg)
        total_food_wasted = expired_listings.aggregate(
            total_kg=Sum('quantity')
        )['total_kg'] or 0
        
        # Get average time to expiry (hours between creation and expiry)
        total_hours_to_expiry = 0
        count_with_valid_times = 0
        
        for listing in expired_listings:
            if listing.created_at and listing.expiry_date:
                hours_diff = (listing.expiry_date - listing.created_at).total_seconds() / 3600
                if 0 < hours_diff < 720:  # Filter outliers (greater than 30 days)
                    total_hours_to_expiry += hours_diff
                    count_with_valid_times += 1
        
        avg_time_to_expiry = 0
        if count_with_valid_times > 0:
            avg_time_to_expiry = total_hours_to_expiry / count_with_valid_times
            
        # Analyze expired listings by supplier
        supplier_expiry_data = expired_listings.values(
            'supplier__id',
            'supplier__email', 
            'supplier__first_name',
            'supplier__last_name',
            'supplier__businessprofile__company_name'
        ).annotate(
            expired_count=Count('id'),
            total_wasted_kg=Sum('quantity')
        ).order_by('-expired_count')[:10]  # Top 10 suppliers by expired listings
        
        # Format supplier data
        suppliers_with_expired = []
        for supplier in supplier_expiry_data:
            # Get supplier name
            company_name = supplier.get('supplier__businessprofile__company_name', '')
            first_name = supplier.get('supplier__first_name', '')
            last_name = supplier.get('supplier__last_name', '')
            email = supplier.get('supplier__email', '')
            
            if company_name:
                supplier_name = company_name
            elif first_name and last_name:
                supplier_name = f"{first_name} {last_name}"
            else:
                supplier_name = email
                
            suppliers_with_expired.append({
                'supplier_id': supplier['supplier__id'],
                'supplier_name': supplier_name,
                'expired_count': supplier['expired_count'],
                'wasted_kg': float(supplier['total_wasted_kg'] or 0)
            })
        
        # Get expired listings by food type
        food_types_expired = expired_listings.values(
            'listing_type'
        ).annotate(
            count=Count('id'),
            total_kg=Sum('quantity')
        ).order_by('-count')
        
        # Format food types data
        expired_by_type = []
        for food_type in food_types_expired:
            expired_by_type.append({
                'type': food_type['listing_type'],
                'count': food_type['count'],
                'wasted_kg': float(food_type['total_kg'] or 0)
            })
        
        # Get daily expired and rescued food trends
        daily_expiry_data = []
        current_date = start_date
        
        while current_date <= end_date:
            # Count expired listings for this day
            day_expired = expired_listings.filter(
                expiry_date__date=current_date
            ).aggregate(
                count=Count('id'),
                quantity=Sum('quantity')
            )
            
            # Count rescued listings for this day using transactions
            day_rescued_tx = rescued_transactions.filter(
                completion_date__date=current_date
            )
            day_rescued_listing_ids = day_rescued_tx.values_list("request__listing_id", flat=True).distinct()
            day_rescued_count = day_rescued_listing_ids.count()
            day_rescued_kg = day_rescued_tx.aggregate(quantity=Sum('request__quantity_requested'))['quantity'] or 0
            
            daily_expiry_data.append({
                'date': current_date.strftime('%Y-%m-%d'),
                'expired_count': day_expired['count'] or 0,
                'expired_kg': float(day_expired['quantity'] or 0),
                'rescued_count': day_rescued_count,
                'rescued_kg': float(day_rescued_kg),
            })
            
            current_date += timezone.timedelta(days=1)
        
        # Compile metrics
        metrics = {
            "total_listings": total_listings,
            "expired_listings_count": expired_count,
            "rescued_listings_count": rescued_count,
            "waste_percentage": float(waste_percentage),
            "rescue_percentage": float(rescue_percentage),
            "total_food_wasted_kg": float(total_food_wasted),
            "avg_time_to_expiry_hours": float(avg_time_to_expiry),
            "suppliers_with_most_expired": suppliers_with_expired,
            "expired_by_food_type": expired_by_type
        }
        
        # Create report data structure
        report_data = {
            "metrics": metrics,
            "daily_trends": daily_expiry_data
        }
        
        # Create summary
        summary = (
            f"Expired Listings: {expired_count} ({waste_percentage:.1f}% of total), "
            f"Food wasted: {float(total_food_wasted):.1f}kg, "
            f"Avg time to expiry: {avg_time_to_expiry:.1f} hours"
        )
        
        return cls.objects.create(
            title=title or f"Listing Expiry & Food Waste Report {start_date} to {end_date}",
            report_type="EXPIRY_WASTE",
            date_range_start=start_date,
            date_range_end=end_date,
            generated_by=user,
            data=report_data,
            summary=summary
        )

    @classmethod
    def generate_user_retention_churn_report(cls, start_date, end_date, user, title=None):
        """Generate user retention and churn report for the specified date range"""
        User = get_user_model()
        # Calculate new signups vs returning users
        new_signups = User.objects.filter(
            date_joined__date__range=[start_date, end_date]
        ).count()
        # Get active users in the period (users who had any activity)
        active_user_data = get_active_users_data(start_date, end_date)
        returning_users = active_user_data['returning_users']
        # Calculate retention rates
        retention_data = calculate_retention_rates(start_date, end_date)
        # Calculate churn rates
        churn_data = calculate_churn_rates(start_date, end_date)
        # Get user engagement metrics
        engagement_metrics = calculate_user_engagement(start_date, end_date)
        # Get user breakdown by type
        user_type_metrics = calculate_metrics_by_user_type(start_date, end_date)
        # Daily user activity for trend analysis
        daily_metrics = get_daily_user_metrics(start_date, end_date)

        # Only include simple values in metrics
        metrics = {
            "total_users": User.objects.count(),
            "new_signups": new_signups,
            "returning_users": returning_users,
            "active_users": active_user_data['active_users'],
            "inactive_users": active_user_data['inactive_users'],
            "retention_rate_7day": float(retention_data['seven_day_retention']),
            "retention_rate_30day": float(retention_data['thirty_day_retention']),
            "churn_rate": float(churn_data['churn_rate']),
            "churned_users_count": churn_data['churned_users'],
            "avg_actions_per_user": float(engagement_metrics['avg_actions_per_user']),
        }
        # Add breakdowns as separate keys
        breakdowns = {
            "user_type_breakdown": user_type_metrics['breakdown'],
            "retention_by_user_type": user_type_metrics['retention'],
            "churn_by_user_type": user_type_metrics['churn'],
            "engagement_by_user_type": user_type_metrics['engagement'],
            "most_common_actions": engagement_metrics['most_common_actions'],
        }
        # Create report data structure
        report_data = {
            "metrics": metrics,
            "daily_trends": daily_metrics,
            **breakdowns
        }
        # Create summary text
        summary = (
            f"New signups: {new_signups}, Returning users: {returning_users}, "
            f"7-day retention: {retention_data['seven_day_retention']:.1f}%, "
            f"30-day retention: {retention_data['thirty_day_retention']:.1f}%, "
            f"Churn rate: {churn_data['churn_rate']:.1f}%"
        )
        return cls.objects.create(
            title=title or f"User Retention & Churn Report {start_date} to {end_date}",
            report_type="USER_RETENTION",
            date_range_start=start_date,
            date_range_end=end_date,
            generated_by=user,
            data=report_data,
            summary=summary
        )


def calculate_supplier_reliability(start_date, end_date):
    """Calculate supplier reliability as percentage of successful transactions"""
    suppliers_data = Transaction.objects.filter(
        request__listing__supplier__user_type="BUSINESS",
        transaction_date__date__range=[start_date, end_date]
    ).values('request__listing__supplier').annotate(
        total_transactions=Count('id'),
        completed_transactions=Count('id', filter=Q(status="COMPLETED"))
    )
    
    if not suppliers_data:
        return 0.0
    
    # Calculate overall reliability across all suppliers
    total_transactions = sum(data['total_transactions'] for data in suppliers_data)
    completed_transactions = sum(data['completed_transactions'] for data in suppliers_data)
    
    if total_transactions == 0:
        return 0.0
    
    return (completed_transactions / total_transactions) * 100


def get_top_suppliers(start_date, end_date, limit=5):
    """Get top suppliers by transaction volume"""
    suppliers = Transaction.objects.filter(
        request__listing__supplier__user_type="BUSINESS",
        transaction_date__date__range=[start_date, end_date],
        status="COMPLETED"
    ).values(
        'request__listing__supplier__id',
        'request__listing__supplier__email',
        'request__listing__supplier__first_name',
        'request__listing__supplier__last_name'
    ).annotate(
        transaction_count=Count('id'),
        total_food_kg=Sum('request__quantity_requested')
    ).order_by('-transaction_count')[:limit]

    # Post-process to create supplier name after the query
    result = []
    for supplier in suppliers:
        first_name = supplier.get('request__listing__supplier__first_name', '')
        last_name = supplier.get('request__listing__supplier__last_name', '')
        email = supplier.get('request__listing__supplier__email', '')
        
        # Use full name if available, otherwise use email
        if first_name and last_name:
            supplier_name = f"{first_name} {last_name}"
        else:
            supplier_name = email
            
        result.append({
            'supplier_id': supplier['request__listing__supplier__id'],
            'supplier_name': supplier_name,
            'transaction_count': supplier['transaction_count'],
            'total_food_kg': float(supplier['total_food_kg'] if supplier['total_food_kg'] else 0)
        })
        
    return result


def calculate_supplier_growth(start_date, end_date):
    """Calculate supplier growth over the period"""
    # Get the midpoint of the date range to compare first half vs second half
    date_range = (end_date - start_date).days
    if date_range <= 1:
        return 0.0
    
    midpoint = start_date + timedelta(days=date_range // 2)
    
    # Count active suppliers in first half
    first_half_suppliers = Transaction.objects.filter(
        request__listing__supplier__user_type="BUSINESS",
        transaction_date__date__range=[start_date, midpoint]
    ).values('request__listing__supplier').distinct().count()
    
    # Count active suppliers in second half
    second_half_suppliers = Transaction.objects.filter(
        request__listing__supplier__user_type="BUSINESS",
        transaction_date__date__range=[midpoint + timedelta(days=1), end_date]
    ).values('request__listing__supplier').distinct().count()
    
    if first_half_suppliers == 0:
        return 100.0 if second_half_suppliers > 0 else 0.0
    
    growth_rate = ((second_half_suppliers - first_half_suppliers) / first_half_suppliers) * 100
    return growth_rate


def get_food_categories_by_supplier(start_date, end_date):
    """Get most popular listing types supplied by suppliers"""
    qs = (
        Transaction.objects.filter(
            request__listing__supplier__user_type="BUSINESS",
            transaction_date__date__range=[start_date, end_date],
            status="COMPLETED",
        )
        .values('request__listing__listing_type')
        .annotate(
            count=Count('id'),
            total_kg=Sum('request__quantity_requested'),
        )
        .order_by('-count')[:10]
    )
    # Convert Decimal to float for JSON serialization
    result = []
    for rec in qs:
        result.append({
            'listing_type': rec['request__listing__listing_type'],
            'count': rec['count'],
            'total_kg': float(rec['total_kg'] or 0),
        })
    return result


def calculate_avg_quality_rating_by_supplier(start_date, end_date):
    """Calculate average quality rating for suppliers"""
    return Rating.objects.filter(
        transaction__completion_date__date__range=[start_date, end_date]
    ).aggregate(avg_rating=Avg('rating'))['avg_rating'] or 0.0


def get_delivery_performance(start_date, end_date):
    """Calculate on-time delivery performance"""
    total_deliveries = DeliveryAssignment.objects.filter(
        transaction__request__listing__supplier__user_type="BUSINESS",
        created_at__date__range=[start_date, end_date],
        status="DELIVERED"
    ).count()
    
    # Consider a delivery on-time if delivered within 24 hours of assignment
    on_time_deliveries = DeliveryAssignment.objects.filter(
        transaction__request__listing__supplier__user_type="BUSINESS",
        created_at__date__range=[start_date, end_date],
        status="DELIVERED"
    ).annotate(
        delivery_time=ExpressionWrapper(
            F('delivered_at') - F('created_at'),
            output_field=models.DurationField()
        )
    ).filter(delivery_time__lte=timedelta(hours=24)).count()
    
    if total_deliveries == 0:
        return 0.0
    
    return (on_time_deliveries / total_deliveries) * 100


def calculate_avg_rescue_time(start_date, end_date):
    """Calculate average time from listing creation to rescue (completion) in hours"""
    # Get completed transactions within the date range
    completed_transactions = Transaction.objects.filter(
        status="COMPLETED",
        completion_date__date__range=[start_date, end_date]
    ).select_related('request__listing')
    
    if not completed_transactions.exists():
        return 0
    
    # Calculate time difference for each transaction
    total_hours = 0
    count = 0
    
    for transaction in completed_transactions:
        if transaction.request and transaction.request.listing:
            listing_created = transaction.request.listing.created_at
            transaction_completed = transaction.completion_date
            
            # Calculate time difference in hours
            if listing_created and transaction_completed:
                time_diff = (transaction_completed - listing_created).total_seconds() / 3600
                
                # Only count reasonable values (avoid negative or extremely large values)
                if 0 <= time_diff <= 72:  # Limit to 3 days to avoid outliers
                    total_hours += time_diff
                    count += 1
    
    # Return average or 0 if no valid data
    return round(total_hours / count, 2) if count > 0 else 0


def get_rescued_food_by_category(start_date, end_date):
    """Get breakdown of rescued food by category (using listing_type since food_category doesn't exist)"""
    # Get all food categories with successful transactions
    rescued_categories = Transaction.objects.filter(
        status="COMPLETED",
        completion_date__date__range=[start_date, end_date]
    ).values(
        'request__listing__listing_type'  # Changed from food_category to listing_type
    ).annotate(
        total_kg=Sum('request__quantity_requested'),
        count=Count('id')
    ).order_by('-total_kg')
    
    # Format results
    categories = []
    for category in rescued_categories:
        categories.append({
            'category': category['request__listing__listing_type'],  # Changed from food_category to listing_type
            'total_kg': float(category['total_kg'] or 0),
            'count': category['count'],
        })
    
    return categories


def analyze_peak_rescue_times(start_date, end_date):
    """Analyze what days and times have the most rescue activity"""
    # Get transactions by day of week
    transactions_by_day = Transaction.objects.filter(
        status="COMPLETED",
        completion_date__date__range=[start_date, end_date]
    ).annotate(
        day_of_week=ExtractWeekDay('completion_date')
    ).values('day_of_week').annotate(
        count=Count('id')
    ).order_by('day_of_week')
    
    # Get transactions by hour
    transactions_by_hour = Transaction.objects.filter(
        status="COMPLETED",
        completion_date__date__range=[start_date, end_date]
    ).annotate(
        hour=ExtractHour('completion_date')
    ).values('hour').annotate(
        count=Count('id')
    ).order_by('hour')
    
    # Format results
    days = []
    for day in transactions_by_day:
        days.append({
            'day_of_week': day['day_of_week'],
            'day_name': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][day['day_of_week'] % 7],
            'count': day['count'],
        })
    
    hours = []
    for hour_data in transactions_by_hour:
        hour = hour_data['hour']
        hours.append({
            'hour': hour,
            'formatted_hour': f"{hour}:00",
            'count': hour_data['count'],
        })
    
    return {
        'days': days,
        'hours': hours,
        'peak_day': max(days, key=lambda x: x['count']) if days else None,
        'peak_hour': max(hours, key=lambda x: x['count']) if hours else None,
    }


def get_waste_reduction_trend(start_date, end_date):
    """Get daily trend of waste reduction over the specified period"""
    # Get daily total rescued food
    daily_totals = Transaction.objects.filter(
        status="COMPLETED",
        completion_date__date__range=[start_date, end_date]
    ).annotate(
        date=TruncDay('completion_date')
    ).values('date').annotate(
        food_saved=Sum('request__quantity_requested')
    ).order_by('date')
    
    # Format results
    trend = []
    running_total = 0
    
    # Create a complete date range (including days with no rescues)
    date_range = []
    current_date = start_date
    while current_date <= end_date:
        date_range.append(current_date)
        current_date += timezone.timedelta(days=1)
    
    # Fill in the trend data
    for current_date in date_range:
        # Find data for this date, if it exists
        day_data = next((day for day in daily_totals if day['date'].date() == current_date), None)
        
        daily_amount = float(day_data['food_saved'] if day_data else 0)
        running_total += daily_amount
        
        trend.append({
            'date': current_date.strftime('%Y-%m-%d'),
            'daily_amount': daily_amount,
            'cumulative_amount': running_total,
        })
    
    return trend


def calculate_new_beneficiaries(start_date, end_date):
    """Calculate the number of new beneficiaries during the date range"""
    User = get_user_model()
    
    # Count users of type NONPROFIT or CONSUMER who registered in this date range
    new_beneficiaries = User.objects.filter(
        user_type__in=["NONPROFIT", "CONSUMER"],
        date_joined__date__range=[start_date, end_date]
    ).count()
    
    return new_beneficiaries


def calculate_food_by_beneficiary_type(start_date, end_date):
    """Calculate food received broken down by beneficiary type"""
    # Get food quantities grouped by beneficiary type
    food_by_type = Transaction.objects.filter(
        status="COMPLETED",
        completion_date__date__range=[start_date, end_date],
        request__requester__user_type__in=["NONPROFIT", "CONSUMER"]
    ).values(
        'request__requester__user_type'
    ).annotate(
        total_kg=Sum('request__quantity_requested'),
        transaction_count=Count('id')
    ).order_by('request__requester__user_type')
    
    # Format results
    result = []
    for item in food_by_type:
        beneficiary_type = item['request__requester__user_type']
        # Format the type label to be more readable
        type_label = "Nonprofit Organization" if beneficiary_type == "NONPROFIT" else "Individual Consumer"
        
        result.append({
            'beneficiary_type': beneficiary_type,
            'type_label': type_label,
            'total_kg': float(item['total_kg'] or 0),
            'transaction_count': item['transaction_count']
        })
    
    return result


def calculate_people_served(start_date, end_date):
    """Estimate the number of people served based on food quantity and beneficiary type"""
    # Get total food by beneficiary type
    food_by_type = calculate_food_by_beneficiary_type(start_date, end_date)
    
    # Estimate people served based on beneficiary type
    # Assumption: Each nonprofit serves 10x more people than a consumer with the same amount of food
    total_people_served = 0
    
    for item in food_by_type:
        food_kg = item['total_kg']
        if item['beneficiary_type'] == "NONPROFIT":
            # Each kg of food to a nonprofit helps ~10 people (estimate)
            people_served = int(food_kg * 10)
        else:
            # Each kg of food to a consumer helps ~1 person (estimate)
            people_served = int(food_kg * 1)
        
        total_people_served += people_served
    
    return total_people_served


def calculate_nutritional_value(start_date, end_date):
    """Estimate nutritional value of redistributed food"""
    # Get total food redistributed in the period
    total_food = Transaction.objects.filter(
        status="COMPLETED",
        completion_date__date__range=[start_date, end_date],
        request__requester__user_type__in=["NONPROFIT", "CONSUMER"]
    ).aggregate(
        total_kg=Sum('request__quantity_requested')
    )['total_kg'] or 0
    
    # Calculate estimated nutritional values
    # These are rough estimates - in a real system you'd have food type data
    nutritional_data = {
        'calories': int(float(total_food) * 1500),  # ~1500 calories per kg
        'protein_g': int(float(total_food) * 50),   # ~50g protein per kg
        'carbs_g': int(float(total_food) * 150),    # ~150g carbs per kg
        'fat_g': int(float(total_food) * 35),       # ~35g fat per kg
        'fiber_g': int(float(total_food) * 20),     # ~20g fiber per kg
    }
    
    return nutritional_data


def calculate_beneficiary_savings(start_date, end_date):
    """Calculate the cost savings for beneficiaries"""
    # Get total food received by beneficiaries
    transactions = Transaction.objects.filter(
        status="COMPLETED", 
        completion_date__date__range=[start_date, end_date],
        request__requester__user_type__in=["NONPROFIT", "CONSUMER"]
    ).select_related('request__listing')
    
    total_savings = 0
    
    for transaction in transactions:
        if transaction.request and transaction.request.listing:
            quantity = transaction.request.quantity_requested
            # For cost savings, use a higher retail value than the listing price
            # since beneficiaries would pay more at retail
            retail_value_per_kg = 5.00  # Estimated retail value per kg
            
            if quantity:
                transaction_savings = float(quantity) * retail_value_per_kg
                total_savings += transaction_savings
    
    return total_savings


def get_satisfaction_metrics(start_date, end_date):
    """Get beneficiary satisfaction metrics from ratings"""
    # Get ratings given by beneficiaries
    ratings = Rating.objects.filter(
        transaction__completion_date__date__range=[start_date, end_date]
    )
    
    # Calculate metrics
    avg_rating = ratings.aggregate(avg=Avg('rating'))['avg'] or 0
    total_ratings = ratings.count()
    
    # Get distribution of ratings
    rating_distribution = ratings.values('rating').annotate(count=Count('id')).order_by('rating')
    
    # Format into a result dictionary
    distribution = {}
    for i in range(1, 6):  # Ensure all ratings 1-5 are represented
        distribution[str(i)] = 0
    
    for item in rating_distribution:
        distribution[str(item['rating'])] = item['count']
    
    return {
        'average_rating': float(avg_rating),
        'total_ratings': total_ratings,
        'distribution': distribution,
        'percentage_satisfied': calculate_satisfaction_percentage(ratings)
    }


def calculate_satisfaction_percentage(ratings):
    """Calculate percentage of 'satisfied' beneficiaries (ratings of 4 or 5)"""
    if not ratings.exists():
        return 0
    
    total = ratings.count()
    satisfied = ratings.filter(rating__gte=4).count()
    
    if total == 0:
        return 0
    
    return (satisfied / total) * 100


def get_top_volunteers(start_date, end_date, limit=5):
    """Get top performing volunteers by delivery count and reliability"""
    User = get_user_model()
    
    # Get volunteers with completed deliveries in the date range
    volunteers = User.objects.filter(
        user_type="VOLUNTEER",
        deliveries__status="DELIVERED",
        deliveries__delivered_at__date__range=[start_date, end_date]
    ).annotate(
        delivery_count=Count('deliveries', filter=Q(
            deliveries__status="DELIVERED",
            deliveries__delivered_at__date__range=[start_date, end_date]
        )),
        total_assigned=Count('deliveries', filter=Q(
            deliveries__created_at__date__range=[start_date, end_date]
        )),
        food_delivered=Sum('deliveries__estimated_weight', filter=Q(
            deliveries__status="DELIVERED",
            deliveries__delivered_at__date__range=[start_date, end_date]
        ))
    ).order_by('-delivery_count')[:limit]
    
    # Format result
    result = []
    for volunteer in volunteers:
        reliability = 0
        if volunteer.total_assigned > 0:
            reliability = (volunteer.delivery_count / volunteer.total_assigned) * 100
            
        result.append({
            'volunteer_id': volunteer.id,
            'volunteer_name': volunteer.get_full_name() or volunteer.email,
            'delivery_count': volunteer.delivery_count,
            'food_delivered_kg': float(volunteer.food_delivered or 0),
            'reliability_percentage': float(reliability)
        })
    
    return result


def calculate_volunteer_reliability(start_date, end_date):
    """Calculate volunteer reliability metrics"""
    User = get_user_model()
    
    # Get volunteers with at least one delivery in the date range
    volunteers_with_deliveries = User.objects.filter(
        user_type="VOLUNTEER",
        deliveries__created_at__date__range=[start_date, end_date]
    ).annotate(
        total_assigned=Count('deliveries', filter=Q(
            deliveries__created_at__date__range=[start_date, end_date]
        )),
        completed=Count('deliveries', filter=Q(
            deliveries__status="DELIVERED",
            deliveries__delivered_at__date__range=[start_date, end_date]
        )),
        failed=Count('deliveries', filter=Q(
            deliveries__status="FAILED",
            deliveries__updated_at__date__range=[start_date, end_date]
        )),
        on_time=Count('deliveries', filter=Q(
            deliveries__status="DELIVERED",
            deliveries__delivered_at__date__range=[start_date, end_date],
            deliveries__delivered_at__lt=F('deliveries__delivery_window_end')
        ))
    )
    
    # Calculate overall reliability metrics
    total_volunteers = volunteers_with_deliveries.count()
    total_assigned = sum(v.total_assigned for v in volunteers_with_deliveries)
    total_completed = sum(v.completed for v in volunteers_with_deliveries)
    total_failed = sum(v.failed for v in volunteers_with_deliveries)
    total_on_time = sum(v.on_time for v in volunteers_with_deliveries)
    
    # Calculate percentages
    completion_rate = 0
    on_time_rate = 0
    failure_rate = 0
    
    if total_assigned > 0:
        completion_rate = (total_completed / total_assigned) * 100
        failure_rate = (total_failed / total_assigned) * 100
        
    if total_completed > 0:
        on_time_rate = (total_on_time / total_completed) * 100
    
    # Count highly reliable volunteers (>90% completion rate)
    reliable_volunteers = 0
    for volunteer in volunteers_with_deliveries:
        if volunteer.total_assigned >= 3:  # Only count volunteers with meaningful sample size
            volunteer_completion_rate = (volunteer.completed / volunteer.total_assigned) * 100
            if volunteer_completion_rate >= 90:
                reliable_volunteers += 1
    
    reliable_percentage = 0
    if total_volunteers > 0:
        reliable_percentage = (reliable_volunteers / total_volunteers) * 100
    
    return {
        'overall_completion_rate': float(completion_rate),
        'on_time_delivery_rate': float(on_time_rate),
        'failure_rate': float(failure_rate),
        'reliable_volunteers_count': reliable_volunteers,
        'reliable_volunteers_percentage': float(reliable_percentage)
    }


def get_volunteer_activity_by_day(start_date, end_date):
    """Get volunteer activity patterns by day of week"""
    # Get completed deliveries grouped by day of week
    deliveries_by_day = DeliveryAssignment.objects.filter(
        status="DELIVERED",
        delivered_at__date__range=[start_date, end_date]
    ).annotate(
        day_of_week=ExtractWeekDay('delivered_at')
    ).values('day_of_week').annotate(
        count=Count('id'),
        food_delivered=Sum('estimated_weight'),
        volunteer_count=Count('volunteer', distinct=True)
    ).order_by('day_of_week')
    
    # Format results
    days = []
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    # Initialize counts for all days
    for i, day_name in enumerate(day_names):
        # Find data for this day if it exists
        day_data = next((day for day in deliveries_by_day if day['day_of_week'] % 7 == i), None)
        
        days.append({
            'day_of_week': i,
            'day_name': day_name,
            'delivery_count': day_data['count'] if day_data else 0,
            'food_delivered_kg': float(day_data['food_delivered'] if day_data and day_data['food_delivered'] else 0),
            'volunteer_count': day_data['volunteer_count'] if day_data else 0
        })
    
    # Get the most active day
    most_active_day = max(days, key=lambda x: x['delivery_count']) if days else None
    
    return {
        'days': days,
        'most_active_day': most_active_day
    }


def get_daily_volunteer_performance(start_date, end_date):
    """Get daily volunteer performance metrics"""
    # Create a complete date range
    date_range = []
    current_date = start_date
    while current_date <= end_date:
        date_range.append(current_date)
        current_date += timezone.timedelta(days=1)


def get_active_users_data(start_date, end_date):
    """Get active and inactive users data for the specified date range using UserActivityLog"""
    User = get_user_model()
    # Users with any activity in the period
    active_user_ids = set(
        UserActivityLog.objects.filter(timestamp__date__range=[start_date, end_date])
        .values_list('user_id', flat=True)
    )
    # All users registered before or during the period
    total_users = User.objects.filter(date_joined__date__lte=end_date).count()
    # New users in this period
    new_users = User.objects.filter(date_joined__date__range=[start_date, end_date]).count()
    new_user_ids = set(User.objects.filter(date_joined__date__range=[start_date, end_date]).values_list('id', flat=True))
    returning_users = len(active_user_ids - new_user_ids)
    # Inactive users: registered before period, no activity in period
    existing_users_before_period = set(User.objects.filter(date_joined__date__lt=start_date).values_list('id', flat=True))
    inactive_users = len(existing_users_before_period - active_user_ids)
    return {
        'active_users': len(active_user_ids),
        'inactive_users': inactive_users,
        'returning_users': returning_users,
        'new_users': new_users,
        'total_users': total_users
    }


def calculate_retention_rates(start_date, end_date):
    """Calculate user retention rates for 7-day and 30-day periods using UserActivityLog"""
    User = get_user_model()
    total_days = (end_date - start_date).days
    if total_days < 14:
        return {'seven_day_retention': 0.0, 'thirty_day_retention': 0.0}
    # 7-day retention
    first_period_start = start_date
    first_period_end = start_date + timedelta(days=min(7, total_days // 3))
    second_period_start = end_date - timedelta(days=min(7, total_days // 3))
    second_period_end = end_date
    first_period_active = set(UserActivityLog.objects.filter(timestamp__date__range=[first_period_start, first_period_end]).values_list('user_id', flat=True))
    second_period_active = set(UserActivityLog.objects.filter(timestamp__date__range=[second_period_start, second_period_end]).values_list('user_id', flat=True))
    seven_day_retention = 0.0
    if first_period_active:
        retained = len(first_period_active & second_period_active)
        seven_day_retention = (retained / len(first_period_active)) * 100
    # 30-day retention
    thirty_day_retention = 0.0
    if total_days >= 45:
        month_first_start = start_date
        month_first_end = start_date + timedelta(days=15)
        month_second_start = end_date - timedelta(days=15)
        month_second_end = end_date
        month_first_active = set(UserActivityLog.objects.filter(timestamp__date__range=[month_first_start, month_first_end]).values_list('user_id', flat=True))
        month_second_active = set(UserActivityLog.objects.filter(timestamp__date__range=[month_second_start, month_second_end]).values_list('user_id', flat=True))
        if month_first_active:
            retained = len(month_first_active & month_second_active)
            thirty_day_retention = (retained / len(month_first_active)) * 100
    return {'seven_day_retention': round(seven_day_retention, 2), 'thirty_day_retention': round(thirty_day_retention, 2)}


def calculate_churn_rates(start_date, end_date):
    """Calculate user churn rate for the specified date range using UserActivityLog"""
    User = get_user_model()
    pre_period_start = start_date - timedelta(days=30)
    pre_period_end = start_date - timedelta(days=1)
    pre_period_active = set(UserActivityLog.objects.filter(timestamp__date__range=[pre_period_start, pre_period_end]).values_list('user_id', flat=True))
    current_period_active = set(UserActivityLog.objects.filter(timestamp__date__range=[start_date, end_date]).values_list('user_id', flat=True))
    churned_users = pre_period_active - current_period_active
    churn_rate = 0.0
    if pre_period_active:
        churn_rate = (len(churned_users) / len(pre_period_active)) * 100
    return {'churned_users': len(churned_users), 'churn_rate': round(churn_rate, 2), 'previous_active_users': len(pre_period_active)}


def calculate_user_engagement(start_date, end_date):
    """Calculate user engagement metrics for the specified date range using UserActivityLog"""
    User = get_user_model()
    active_user_data = get_active_users_data(start_date, end_date)
    active_users = active_user_data['active_users']
    total_actions = UserActivityLog.objects.filter(timestamp__date__range=[start_date, end_date]).count()
    avg_actions_per_user = 0
    if active_users > 0:
        avg_actions_per_user = total_actions / active_users
    # Most common actions
    action_counts = UserActivityLog.objects.filter(timestamp__date__range=[start_date, end_date]).values('activity_type').annotate(count=Count('id')).order_by('-count')
    most_common_actions = [{'action_type': a['activity_type'], 'count': a['count']} for a in action_counts]
    return {
        'total_actions': total_actions,
        'avg_actions_per_user': round(avg_actions_per_user, 2),
        'action_breakdown': {a['activity_type']: a['count'] for a in action_counts},
        'most_common_actions': most_common_actions
    }


def calculate_metrics_by_user_type(start_date, end_date):
    """Calculate user retention and churn metrics broken down by user type using UserActivityLog"""
    User = get_user_model()
    user_types = ["BUSINESS", "NONPROFIT", "VOLUNTEER", "CONSUMER"]
    user_type_breakdown = []
    retention_by_type = []
    churn_by_type = []
    engagement_by_type = []
    for user_type in user_types:
        users_of_type = User.objects.filter(user_type=user_type)
        total_users_of_type = users_of_type.count()
        if total_users_of_type == 0:
            continue
        # Active users of this type
        active_ids = set(UserActivityLog.objects.filter(user__user_type=user_type, timestamp__date__range=[start_date, end_date]).values_list('user_id', flat=True))
        active_count = len(active_ids)
        inactive_count = total_users_of_type - active_count
        new_users_count = users_of_type.filter(date_joined__date__range=[start_date, end_date]).count()
        user_type_breakdown.append({
            'user_type': user_type,
            'total_users': total_users_of_type,
            'active_users': active_count,
            'inactive_users': inactive_count,
            'new_users': new_users_count,
            'active_percentage': round((active_count / total_users_of_type) * 100, 2) if total_users_of_type > 0 else 0
        })
        # Retention/churn
        pre_period_start = start_date - timedelta(days=30)
        pre_period_end = start_date - timedelta(days=1)
        pre_active = set(UserActivityLog.objects.filter(user__user_type=user_type, timestamp__date__range=[pre_period_start, pre_period_end]).values_list('user_id', flat=True))
        retained = pre_active & active_ids
        retention_rate = (len(retained) / len(pre_active) * 100) if pre_active else 0.0
        retention_by_type.append({
            'user_type': user_type,
            'retention_rate': round(retention_rate, 2),
            'active_in_previous': len(pre_active),
            'retained_users': len(retained)
        })
        churned = pre_active - active_ids
        churn_rate = (len(churned) / len(pre_active) * 100) if pre_active else 0.0
        churn_by_type.append({
            'user_type': user_type,
            'churn_rate': round(churn_rate, 2),
            'churned_users': len(churned),
            'active_in_previous': len(pre_active)
        })
        # Engagement
        total_actions = UserActivityLog.objects.filter(user__user_type=user_type, timestamp__date__range=[start_date, end_date]).count()
        login_actions = UserActivityLog.objects.filter(user__user_type=user_type, timestamp__date__range=[start_date, end_date], activity_type__icontains='login').count()
        type_specific_actions = total_actions - login_actions
        avg_actions = total_actions / active_count if active_count > 0 else 0.0
        engagement_by_type.append({
            'user_type': user_type,
            'total_actions': total_actions,
            'avg_actions_per_user': round(avg_actions, 2),
            'login_actions': login_actions,
            'type_specific_actions': type_specific_actions
        })
    return {
        'breakdown': user_type_breakdown,
        'retention': retention_by_type,
        'churn': churn_by_type,
        'engagement': engagement_by_type
    }


def get_daily_user_metrics(start_date, end_date):
    """Get daily user metrics for trend analysis using UserActivityLog"""
    User = get_user_model()
    date_range = []
    current_date = start_date
    while current_date <= end_date:
        date_range.append(current_date)
        current_date += timezone.timedelta(days=1)
    daily_metrics = []
    for day in date_range:
        day_active_ids = set(UserActivityLog.objects.filter(timestamp__date=day).values_list('user_id', flat=True))
        new_users = User.objects.filter(date_joined__date=day).count()
        business_users = User.objects.filter(user_type="BUSINESS", id__in=day_active_ids).count()
        nonprofit_users = User.objects.filter(user_type="NONPROFIT", id__in=day_active_ids).count()
        volunteer_users = User.objects.filter(user_type="VOLUNTEER", id__in=day_active_ids).count()
        consumer_users = User.objects.filter(user_type="CONSUMER", id__in=day_active_ids).count()
        user_actions = UserActivityLog.objects.filter(timestamp__date=day).count()
        avg_actions = user_actions / len(day_active_ids) if day_active_ids else 0
        daily_metrics.append({
            'date': day.strftime('%Y-%m-%d'),
            'active_users': len(day_active_ids),
            'new_users': new_users,
            'business_users': business_users,
            'nonprofit_users': nonprofit_users,
            'volunteer_users': volunteer_users,
            'consumer_users': consumer_users,
            'total_actions': user_actions,
            'avg_actions_per_user': round(avg_actions, 2)
        })
    return daily_metrics
