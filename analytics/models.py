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
)
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

                # Format metrics data
                for key, value in report_data["metrics"].items():
                    # Format metric name to be clearer
                    formatted_key = key.replace("_", " ").title()
                    if isinstance(value, (int, float)):
                        formatted_value = (
                            "{:,.2f}".format(value)
                            if isinstance(value, float)
                            else "{:,}".format(value)
                        )
                    else:
                        formatted_value = str(value)
                    metrics_data.append([formatted_key, formatted_value])

                if metrics_data:
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

        if report_data.get("metrics") and isinstance(report_data["metrics"], dict):
            writer.writerow(["Key Metrics"])
            writer.writerow(["Metric", "Value"])  # Column Header Columns
            for key, value in report_data["metrics"].items():
                # Format numbers with commas for thousands
                if isinstance(value, (int, float)):
                    formatted_value = (
                        "{:,.2f}".format(value)
                        if isinstance(value, float)
                        else "{:,}".format(value)
                    )
                else:
                    formatted_value = value
                writer.writerow([key.title(), formatted_value])

            writer.writerow([])  # Empty row for spacing

        if (
            report_data.get("daily_trends")
            and isinstance(report_data["daily_trends"], list)
            and report_data["daily_trends"]
        ):
            writer.writerow(["Daily Trends"])

            # Write headers for trends
            first_day = report_data["daily_trends"][0]
            headers = ["Date"] + [key for key in first_day.keys() if key != "date"]
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
                            formatted_value = "{:,.2f}".format(value)
                        elif isinstance(value, int):
                            formatted_value = "{:,}".format(value)
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
