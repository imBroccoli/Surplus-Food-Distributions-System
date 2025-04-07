import logging
import re
from datetime import timedelta
from decimal import Decimal

from django.urls import resolve
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from django.contrib import messages
from django.core.cache import caches
from django.db.models import Sum
import json

from .models import (
    DailyAnalytics,
    ImpactMetrics,
    Report,
    UserActivityLog,
)

logger = logging.getLogger(__name__)


class UserActivityMiddleware:
    """Middleware to log user activity across the platform"""

    def __init__(self, get_response):
        self.get_response = get_response
        # URL patterns to ignore for logging
        self.ignore_patterns = [
            r"^/admin/",
            r"^/static/",
            r"^/media/",
            r"^/__debug__/",
        ]

    def __call__(self, request):
        # Process the request
        response = self.get_response(request)

        # Log activity only for authenticated users and relevant paths
        if request.user.is_authenticated and not self._should_ignore(request.path):
            self._log_activity(request)

        return response

    def _should_ignore(self, path):
        """Check if the path should be ignored for activity logging"""
        for pattern in self.ignore_patterns:
            if re.match(pattern, path):
                return True
        return False

    def _log_activity(self, request):
        """Log user activity based on URL patterns"""
        try:
            url_name = resolve(request.path_info).url_name
            activity_type = self._determine_activity_type(request.method, url_name)

            # Don't log if we couldn't determine activity type
            if not activity_type:
                return

            # Capture the IP address
            x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(",")[0]
            else:
                ip_address = request.META.get("REMOTE_ADDR")

            # Create activity log entry
            UserActivityLog.objects.create(
                user=request.user,
                activity_type=activity_type,
                details=f"Path: {request.path}, Method: {request.method}",
                ip_address=ip_address,
            )
        except Exception:
            # Silently fail if logging fails - don't interrupt user experience
            pass

    def _determine_activity_type(self, method, url_name):
        """Map URL name to activity type"""
        # Default mapping for common patterns
        if not url_name:
            return None

        # View actions
        if url_name.endswith("_list") or url_name.startswith("browse_"):
            return "VIEW_LIST"

        if url_name.endswith("_detail") or "detail" in url_name:
            return "VIEW_DETAIL"

        # Data entry/modifications
        if method == "POST":
            if "create" in url_name or url_name.endswith("_form"):
                return "CREATE"
            if "update" in url_name or "edit" in url_name:
                return "UPDATE"
            if "delete" in url_name or "remove" in url_name:
                return "DELETE"
            if "login" in url_name:
                return "LOGIN"
            if "logout" in url_name:
                return "LOGOUT"

        # Specific mappings by feature area
        activity_mappings = {
            "listing_list": "VIEW_LISTINGS",
            "listing_detail": "VIEW_LISTING_DETAIL",
            "create_listing": "CREATE_LISTING",
            "update_listing": "UPDATE_LISTING",
            "delete_listing": "DELETE_LISTING",
            "browse_listings": "BROWSE_LISTINGS",
            "make_request": "CREATE_REQUEST",
            "my_requests": "VIEW_MY_REQUESTS",
            "manage_requests": "MANAGE_REQUESTS",
            "handle_request": "HANDLE_REQUEST",
            "my_transactions": "VIEW_TRANSACTIONS",
            "rate_transaction": "RATE_TRANSACTION",
            "available_deliveries": "VIEW_DELIVERIES",
            "my_deliveries": "MANAGE_DELIVERIES",
            "impact_dashboard": "VIEW_IMPACT_METRICS",
            "system_analytics": "VIEW_SYSTEM_ANALYTICS",
            "user_activity": "VIEW_USER_ACTIVITY",
        }

        return activity_mappings.get(url_name, "OTHER")


class AnalyticsMiddleware:
    """Middleware to track analytics data"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.user.is_authenticated:
            try:
                # Check if this is a transaction-related action
                if "transactions" in request.path and request.method == "POST":
                    url_name = resolve(request.path_info).url_name

                    # Handle request approval
                    if url_name == "handle_request" and "approve" in request.path:
                        self._update_daily_analytics(request)
                        self._update_impact_metrics(request)

                    # Handle transaction completion via delivery
                    elif (
                        url_name == "update_delivery_status"
                        and request.POST.get("status") == "DELIVERED"
                    ):
                        self._update_daily_analytics(request, is_delivery=True)
                        self._update_impact_metrics(request)

                    # Handle new request creation
                    elif url_name == "create_request":
                        self._update_daily_analytics(request, is_new_request=True)

            except Exception as e:
                # Log error but don't interrupt user flow
                logger.error(f"Analytics middleware error: {str(e)}")

        return response

    def _update_daily_analytics(self, request, is_new_request=False, is_delivery=False):
        """Update daily analytics when a transaction is completed or request is created"""
        from transactions.models import FoodRequest, DeliveryAssignment

        try:
            # Extract request_id based on the action type
            request_id = None
            if is_delivery:
                # For delivery updates, get the request from the delivery assignment
                delivery_id = int(request.path.split("/")[-2])
                delivery = DeliveryAssignment.objects.select_related(
                    "transaction__request"
                ).get(id=delivery_id)
                request_id = delivery.transaction.request.id
            else:
                # For direct request actions (approve/create)
                request_id = int(request.path.split("/")[-2])

            food_request = FoodRequest.objects.get(id=request_id)

            # Get or create analytics entry
            analytics, created = DailyAnalytics.objects.get_or_create(
                date=timezone.now().date(),
                user=food_request.listing.supplier,
                listing=food_request.listing,
                defaults={
                    "requests_received": 0,
                    "requests_fulfilled": 0,
                    "food_saved_kg": Decimal("0"),
                },
            )

            if is_new_request:
                # Only increment requests_received for new requests
                analytics.requests_received += 1
            else:
                # For approvals/completions, increment fulfilled and food saved
                analytics.requests_fulfilled += 1
                if food_request.quantity_requested:
                    analytics.food_saved_kg += Decimal(
                        str(food_request.quantity_requested)
                    )

            analytics.full_clean()
            analytics.save()

        except Exception as e:
            logger.error(f"Error updating daily analytics: {str(e)}")

    def _update_impact_metrics(self, request):
        """Update impact metrics when a transaction is completed"""
        try:
            metrics = ImpactMetrics.calculate_for_date(timezone.now().date())
            metrics.save()
        except Exception as e:
            logger.error(f"Error updating impact metrics: {str(e)}")


class ReportSchedulerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._scheduled_reports = {}

    def __call__(self, request):
        response = self.get_response(request)

        # Only process scheduled reports for authenticated users
        if hasattr(request, "user") and request.user.is_authenticated:
            self._process_scheduled_reports(request)

        return response

    def _process_scheduled_reports(self, request):
        from .models import Report
        from datetime import datetime, timedelta
        from django.utils import timezone
        from notifications.services import NotificationService

        now = timezone.now()

        # Get all active scheduled reports
        scheduled_reports = Report.objects.filter(
            is_scheduled=True, schedule_time__isnull=False
        ).select_related("generated_by")

        for report in scheduled_reports:
            report_key = f"{report.id}_{report.schedule_frequency}"

            # Skip if already processed within the time window
            if report_key in self._scheduled_reports:
                last_run = self._scheduled_reports[report_key]
                if self._should_skip_report(report, last_run, now):
                    continue

            # Check if report should be generated now
            if self._should_generate_report(report, now):
                try:
                    # Generate the report
                    report.generate_report()

                    # Create notification
                    NotificationService.create_report_notification(
                        report=report,
                        notification_type="REPORT_GENERATED",
                        user=report.generated_by,
                    )

                    # Update last run time
                    self._scheduled_reports[report_key] = now

                except Exception as e:
                    # Log error and create notification
                    import logging

                    logger = logging.getLogger(__name__)
                    logger.error(
                        f"Error generating scheduled report {report.id}: {str(e)}"
                    )

                    NotificationService.create_report_notification(
                        report=report,
                        notification_type="REPORT_ERROR",
                        user=report.generated_by,
                        extra_context={"error": str(e)},
                    )

    def _should_skip_report(self, report, last_run, now):
        """Determine if report should be skipped based on last run time"""
        if report.schedule_frequency == "DAILY":
            return (now - last_run) < timedelta(hours=23)
        elif report.schedule_frequency == "WEEKLY":
            return (now - last_run) < timedelta(days=6)
        elif report.schedule_frequency == "MONTHLY":
            return (now - last_run) < timedelta(days=27)
        return False

    def _should_generate_report(self, report, now):
        """Determine if report should be generated based on schedule"""
        if not report.schedule_time:
            return False

        current_time = now.time()
        schedule_time = report.schedule_time

        # Allow 5-minute window for report generation
        time_diff = abs(
            (current_time.hour * 60 + current_time.minute)
            - (schedule_time.hour * 60 + schedule_time.minute)
        )

        return time_diff <= 5


class AnalyticsNotificationMiddleware(MiddlewareMixin):
    """Middleware to handle analytics notifications and prevent persistence"""

    def process_request(self, request):
        """Process incoming request"""
        request.analytics_page = request.path.startswith("/analytics/")

    def process_response(self, request, response):
        """Process outgoing response"""
        if hasattr(request, "_messages"):
            storage = messages.get_messages(request)
            messages_to_keep = []

            for message in storage:
                # Keep only messages that are relevant to the current request
                is_current_message = getattr(
                    message, "request_path", None
                ) == request.path or "swal" in getattr(message, "extra_tags", "")

                if is_current_message:
                    messages_to_keep.append(message)

            # Clear all messages and re-add only the ones we want to keep
            storage.used = True

            for message in messages_to_keep:
                messages.add_message(
                    request,
                    message.level,
                    message.message,
                    extra_tags=message.extra_tags,
                )

        return response


class RealTimeAnalyticsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.analytics_cache = caches["analytics"]

    def __call__(self, request):
        response = self.get_response(request)

        if (
            request.user.is_authenticated
            and request.user.user_type == "BUSINESS"
            and "text/html" in response.get("Content-Type", "")
        ):
            try:
                self._update_real_time_analytics(request.user)
            except Exception as e:
                logger.error(f"Error updating real-time analytics: {str(e)}")

        return response

    def _update_real_time_analytics(self, user):
        today = timezone.now().date()
        month_ago = today - timedelta(days=30)
        # Include current hour in cache key to refresh data more frequently
        current_time = timezone.now()
        cache_key = (
            f"business_analytics_{user.id}_{today.isoformat()}_{current_time.hour}"
        )

        # Always update cache for real-time analytics
        daily_metrics = list(
            DailyAnalytics.objects.filter(
                user=user, date__gte=month_ago, date__lte=today
            )
            .values("date")
            .annotate(
                daily_food=Sum("food_saved_kg"),
                daily_requests=Sum("requests_received"),
            )
            .order_by("date")
        )

        # Calculate running totals
        running_food_total = 0
        running_requests_total = 0

        for metric in daily_metrics:
            running_food_total += float(metric["daily_food"] or 0)
            running_requests_total += int(metric["daily_requests"] or 0)
            metric["cumulative_food"] = running_food_total
            metric["cumulative_requests"] = running_requests_total

        # Cache the processed data with a shorter expiration time
        self.analytics_cache.set(cache_key, daily_metrics, 60)  # 1 minute cache


from django.core.cache import caches
from django.utils import timezone


class RealTimeAnalyticsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Process request
        if hasattr(request, "user") and request.user.is_authenticated:
            self._update_analytics_cache(request)

        response = self.get_response(request)
        return response

    def _update_analytics_cache(self, request):
        """Update analytics cache for real-time data"""
        if request.user.user_type == "BUSINESS":
            cache_key = f"business_analytics_{request.user.id}"
            # Only invalidate cache for relevant actions
            if request.method in ["POST", "PUT", "DELETE"] or (
                request.method == "GET"
                and any(
                    path in request.path
                    for path in ["/listings/", "/requests/", "/transactions/"]
                )
            ):
                caches["analytics"].delete(cache_key)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Process view to track analytics-related actions"""
        if not hasattr(request, "user") or not request.user.is_authenticated:
            return None

        # Track views of analytics pages for caching decisions
        if "analytics" in request.path:
            self._track_analytics_view(request)

        return None

    def _track_analytics_view(self, request):
        """Track analytics page views for smart caching"""
        user_id = request.user.id
        view_key = f"analytics_view_{user_id}"
        caches["analytics"].set(view_key, timezone.now(), 300)  # Cache for 5 minutes
