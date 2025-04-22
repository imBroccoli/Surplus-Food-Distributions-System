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
from reportlab.lib.pagesizes import letter
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
    avg_response_time = models.DurationField(
        null=True, blank=True, help_text="Average time to respond to requests"
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

        # Calculate average response time (in hours)
        response_times = (
            FoodRequest.objects.filter(
                status__in=["APPROVED", "REJECTED"], updated_at__date=date
            )
            .annotate(
                response_time=ExpressionWrapper(
                    F("updated_at") - F("created_at"),
                    output_field=models.DurationField(),
                )
            )
            .aggregate(avg_time=Avg("response_time"), count=Count("id"))
        )

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
                transaction__in=completed_transactions_today
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
                "avg_response_time": response_times["avg_time"]
                if response_times["count"] > 0
                else None,
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
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
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
                    if key in ['top_suppliers', 'food_categories', 'rescued_by_category', 'peak_rescue_times']:
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
                                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
                                ("ALIGN", (1, 1), (1, -1), "RIGHT"),  # Right align count
                            ])
                        )
                        elements.append(hour_table)
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
                    # Calculate column widths for contents
                    col_widths = [100] + [80] * (len(headers) - 1)
                    table = Table(table_data, colWidths=col_widths, repeatRows=1)
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
                                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, 0), 10),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                                (
                                    "TOPPADDING",
                                    (0, 0),
                                    (-1, 0),
                                    12,
                                ),  # Add padding at the top of a header
                                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                                (
                                    "TEXTCOLOR",
                                    (0, 1),
                                    (-1, -1),
                                    colors.HexColor("#2c3e50"),
                                ),
                                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                                ("FONTSIZE", (0, 1), (-1, -1), 9),
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
                                (
                                    "ALIGN",
                                    (1, 1),
                                    (-1, -1),
                                    "RIGHT",
                                ),  # Right-align numeric columns
                                (
                                    "ALIGN",
                                    (0, 1),
                                    (0, -1),
                                    "LEFT",
                                ),  # Left-align date column
                                (
                                    "LEFTPADDING",
                                    (0, 0),
                                    (-1, -1),
                                    8,
                                ),  # Adjusted padding
                                (
                                    "RIGHTPADDING",
                                    (0, 0),
                                    (-1, -1),
                                    8,
                                ),  # Adjusted padding
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
                # Skip complex nested structures - we'll handle them separately
                if key in ['top_suppliers', 'food_categories', 'rescued_by_category', 'peak_rescue_times']:
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

        # Handle timedelta conversion for avg_response_time
        avg_response_time = metrics["avg_response_time"]
        if avg_response_time:
            # Convert timedelta to seconds
            metrics["avg_response_time"] = avg_response_time.total_seconds()
        else:
            metrics["avg_response_time"] = 0

        # Ensure absence of None values in other metrics
        for key in metrics:
            if (
                key != "avg_response_time"
            ):  # Skip avg_response_time as it's already handled
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
            # Convert timedelta to seconds for response_time
            response_time = metric["response_time"]
            if response_time and isinstance(response_time, timedelta):
                response_time = response_time.total_seconds()
            else:
                response_time = 0

            formatted_metric = {
                "date": metric["date"].strftime("%Y-%m-%d"),
                "active_users": int(metric["active_users"] or 0),
                "response_time": float(response_time),
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
            summary=f"Avg completion rate: {metrics['avg_transaction_completion']:.1f}%, Response time: {metrics['avg_response_time']:.2f}s, Active users: {metrics['total_active_users']}",
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
        transaction__request__listing__supplier__user_type="BUSINESS",
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
