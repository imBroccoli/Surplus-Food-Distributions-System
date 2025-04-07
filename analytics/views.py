from datetime import datetime, timedelta
import csv
from io import BytesIO, StringIO
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.cache import caches
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import DatabaseError, models
from django.db.models import Count, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import TruncDay
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
import sweetify

from food_listings.models import FoodListing
from transactions.models import FoodRequest
from users.models import CustomUser

from .models import (
    DailyAnalytics,
    ImpactMetrics,
    Report,
    SystemMetrics,
    UserActivityLog,
)
from notifications.services import NotificationService

import csv
import xlsxwriter
from datetime import datetime, timedelta
from io import BytesIO, StringIO

# Configure logger with proper name
logger = logging.getLogger("analytics.views")


def is_admin_or_staff(user):
    """Check if user is admin or staff"""
    return user.is_authenticated and (user.is_staff or user.user_type == "ADMIN")


def is_admin(user):
    """Check if user is admin (superuser, staff, or user_type=ADMIN)"""
    return user.is_superuser or user.is_staff or user.user_type == "ADMIN"


def validate_filter_dates(date_from, date_to):
    """Validate filter dates and return cleaned date objects or None"""
    try:
        if date_from:
            date_from = datetime.strptime(date_from, "%Y-%m-%d").date()

        if date_to:
            date_to = datetime.strptime(date_to, "%Y-%m-%d").date()

        # Don't return error for future dates in filters, just limiting to today
        today = timezone.now().date()
        if date_to and date_to > today:
            date_to = today

        return date_from, date_to

    except (ValueError, TypeError):
        # Return None for invalid dates
        return None, None


@login_required
def impact_dashboard(request):
    """View for impact metrics dashboard"""
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Get or calculate today's metrics
    todays_metrics_obj = ImpactMetrics.calculate_for_date(today)

    # If today's metrics are zero, check if we have any data at all
    if (
        todays_metrics_obj.food_redistributed_kg == 0
        and todays_metrics_obj.co2_emissions_saved == 0
        and todays_metrics_obj.meals_provided == 0
    ):
        # Get the most recent record that has data
        recent_metrics = (
            ImpactMetrics.objects.exclude(food_redistributed_kg=0)
            .order_by("-date")
            .first()
        )

        # If found, use it as a fallback for today's display
        if recent_metrics:
            todays_metrics = {
                "food_total": float(recent_metrics.food_redistributed_kg),
                "co2_total": float(recent_metrics.co2_emissions_saved),
                "meals_total": recent_metrics.meals_provided,
                "value_total": float(recent_metrics.monetary_value_saved),
            }
        else:
            # If no data at all, use zeros
            todays_metrics = {
                "food_total": 0,
                "co2_total": 0,
                "meals_total": 0,
                "value_total": 0,
            }
    else:
        # Use today's metrics from the database if they have data
        todays_metrics = {
            "food_total": float(todays_metrics_obj.food_redistributed_kg),
            "co2_total": float(todays_metrics_obj.co2_emissions_saved),
            "meals_total": todays_metrics_obj.meals_provided,
            "value_total": float(todays_metrics_obj.monetary_value_saved),
        }

    # Calculate last 7 days metrics (excluding today)
    metrics_7days = ImpactMetrics.objects.filter(
        date__lt=today,  # Less than today
        date__gte=week_ago,  # Greater than or equal to week ago
    ).aggregate(
        food_total=Sum("food_redistributed_kg"),
        co2_total=Sum("co2_emissions_saved"),
        meals_total=Sum("meals_provided"),
        value_total=Sum("monetary_value_saved"),
    )

    # Add today's metrics to 7 days total
    metrics_7days = {
        "food_total": float(metrics_7days["food_total"] or 0)
        + todays_metrics["food_total"],
        "co2_total": float(metrics_7days["co2_total"] or 0)
        + todays_metrics["co2_total"],
        "meals_total": int(metrics_7days["meals_total"] or 0)
        + todays_metrics["meals_total"],
        "value_total": float(metrics_7days["value_total"] or 0)
        + todays_metrics["value_total"],
    }

    # Calculate last 30 days metrics (excluding today)
    metrics_30days = ImpactMetrics.objects.filter(
        date__lt=today,  # Less than today
        date__gte=month_ago,  # Greater than or equal to month ago
    ).aggregate(
        food_total=Sum("food_redistributed_kg"),
        co2_total=Sum("co2_emissions_saved"),
        meals_total=Sum("meals_provided"),
        value_total=Sum("monetary_value_saved"),
    )

    # Add today's metrics to 30 days total
    metrics_30days = {
        "food_total": float(metrics_30days["food_total"] or 0)
        + todays_metrics["food_total"],
        "co2_total": float(metrics_30days["co2_total"] or 0)
        + todays_metrics["co2_total"],
        "meals_total": int(metrics_30days["meals_total"] or 0)
        + todays_metrics["meals_total"],
        "value_total": float(metrics_30days["value_total"] or 0)
        + todays_metrics["value_total"],
    }

    # Get all-time metrics (total from all records)
    all_time_metrics = ImpactMetrics.objects.aggregate(
        food_total=Sum("food_redistributed_kg"),
        co2_total=Sum("co2_emissions_saved"),
        meals_total=Sum("meals_provided"),
        value_total=Sum("monetary_value_saved"),
    )

    # Ensure no None values in all_time_metrics
    all_time_metrics = {
        "food_total": float(all_time_metrics["food_total"] or 0),
        "co2_total": float(all_time_metrics["co2_total"] or 0),
        "meals_total": int(all_time_metrics["meals_total"] or 0),
        "value_total": float(all_time_metrics["value_total"] or 0),
    }

    # Combine metrics into a context dictionary
    metrics = {
        "today": todays_metrics,
        "last_7_days": metrics_7days,
        "last_30_days": metrics_30days,
        "all_time": all_time_metrics,
    }

    return render(request, "analytics/impact_dashboard.html", {"metrics": metrics})


@login_required
@user_passes_test(is_admin_or_staff)
def system_analytics(request):
    """View for system analytics dashboard (restricted to staff/admin)"""
    today = timezone.now().date()

    # Get or calculate today's system metrics
    todays_metrics = SystemMetrics.calculate_for_date(today)

    # Calculate time periods
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)

    # Get data for historical comparison
    yesterdays_metrics = SystemMetrics.objects.filter(date=yesterday).first()

    # Get data for trends
    daily_metrics = SystemMetrics.objects.filter(
        date__gte=week_ago, date__lte=today
    ).order_by("date")

    # Prepare user activity breakdown
    user_activity_breakdown = (
        UserActivityLog.objects.filter(timestamp__date__gte=week_ago)
        .values("activity_type")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )  # Top 10 activities

    # Get daily user activity counts for chart
    daily_user_activity = (
        UserActivityLog.objects.filter(timestamp__date__gte=week_ago)
        .annotate(day=TruncDay("timestamp"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

    # Calculate growth metrics (comparing today vs yesterday)
    growth = {}
    if yesterdays_metrics:
        growth = {
            "user_growth": _calculate_growth(
                todays_metrics.active_users, yesterdays_metrics.active_users
            ),
            "listing_growth": _calculate_growth(
                todays_metrics.new_listings_count, yesterdays_metrics.new_listings_count
            ),
            "request_growth": _calculate_growth(
                todays_metrics.request_count, yesterdays_metrics.request_count
            ),
            "completion_growth": _calculate_growth(
                todays_metrics.transaction_completion_rate,
                yesterdays_metrics.transaction_completion_rate,
            ),
        }

    # Return context data for the template
    context = {
        "today": todays_metrics,
        "daily_metrics": daily_metrics,
        "growth": growth,
        "user_activity_breakdown": user_activity_breakdown,
        "daily_user_activity": daily_user_activity,
    }

    return render(request, "analytics/system_analytics.html", context)


@login_required
@user_passes_test(is_admin_or_staff)
def user_activity(request):
    """View for user activity logs (restricted to staff/admin)"""
    # Get filter parameters from request
    user_id = request.GET.get("user_id")
    activity_type = request.GET.get("activity_type")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")

    # DataTables server-side parameters
    draw = request.GET.get("draw")
    start = int(request.GET.get("start", 0))
    length = int(request.GET.get("length", 15))
    search_value = request.GET.get("search[value]", "")
    order_column = request.GET.get("order[0][column]", "2")  # Default sort by timestamp
    order_dir = request.GET.get("order[0][dir]", "desc")

    # Validate dates
    date_from, date_to = validate_filter_dates(date_from, date_to)

    # Base queryset - exclude admin users
    logs = UserActivityLog.objects.exclude(user__user_type="ADMIN").select_related(
        "user"
    )  # Optimize user lookups

    # Apply filters if provided
    if user_id:
        logs = logs.filter(user_id=int(user_id))

    if activity_type:
        if activity_type.upper() == "OTHER":
            # For 'OTHER', exclude known activity types
            known_types = ["VIEW_", "CREATE_", "UPDATE_", "DELETE_", "LOGIN", "LOGOUT"]
            q_objects = Q()
            for prefix in known_types:
                q_objects |= Q(activity_type__istartswith=prefix)
            logs = logs.exclude(q_objects)
        else:
            # Use case-insensitive matching for activity type
            logs = logs.filter(activity_type__iregex=f"^{activity_type}$")

    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)

    # Apply search if provided
    if search_value:
        logs = logs.filter(
            Q(user__email__icontains=search_value)
            | Q(activity_type__icontains=search_value)
            | Q(details__icontains=search_value)
            | Q(ip_address__icontains=search_value)
        )

    # Get total counts before pagination
    total_records = logs.count()
    total_filtered = total_records

    # Apply ordering
    column_ordering = {
        "0": "user__email",
        "1": "activity_type",
        "2": "timestamp",
        "3": "ip_address",
        "4": "details",
    }
    order_column = column_ordering.get(order_column, "timestamp")
    if order_dir == "desc":
        order_column = f"-{order_column}"
    logs = logs.order_by(order_column)

    # Handle AJAX request for DataTables
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        # Apply pagination
        logs_page = logs[start : start + length]

        data = []
        for log in logs_page:
            data.append(
                {
                    "user": {
                        "email": log.user.email,
                        "type": log.user.get_user_type_display(),
                    },
                    "activity_type": log.activity_type,
                    "timestamp": log.timestamp.isoformat(),
                    "ip_address": log.ip_address,
                    "details": log.details,
                }
            )

        return JsonResponse(
            {
                "draw": int(draw),
                "recordsTotal": total_records,
                "recordsFiltered": total_filtered,
                "data": data,
            }
        )

    # For regular page load, prepare context data
    raw_types = UserActivityLog.objects.values_list(
        "activity_type", flat=True
    ).distinct()

    # Process activity types to be more user-friendly
    activity_types = set()  # Use a set to remove duplicates
    for raw_type in raw_types:
        # Clean up the activity type
        cleaned_type = raw_type.replace("_", " ").title()
        # Group similar activities (e.g., "View List", "View Detail" -> "View")
        base_type = cleaned_type.split()[0]
        if base_type in ["View", "Create", "Update", "Delete"]:
            activity_types.add(base_type)
        else:
            activity_types.add(cleaned_type)

    # Add "Other" option if not already present
    activity_types.add("Other")

    # Convert to sorted list
    activity_types = sorted(activity_types)

    # Get unique users who have activity logs - using subquery for efficiency
    users_with_activity = (
        UserActivityLog.objects.values("user_id")
        .distinct()
        .annotate(
            user__id=F("user_id"),
            user__email=Subquery(
                CustomUser.objects.filter(id=OuterRef("user_id")).values("email")[:1]
            ),
        )
        .order_by("user__email")
    )

    context = {
        "activity_types": activity_types,
        "users": users_with_activity,
        "filter": {
            "user_id": user_id,
            "activity_type": activity_type,
            "date_from": date_from,
            "date_to": date_to,
        },
    }

    return render(request, "analytics/user_activity.html", context)


@login_required
@user_passes_test(is_admin)
def admin_activity(request):
    """View for admin-only activity logs"""
    # Get filter parameters from request
    admin_id = request.GET.get("admin_id")
    activity_type = request.GET.get("activity_type")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")

    # DataTables server-side parameters
    draw = request.GET.get("draw")
    start = int(request.GET.get("start", 0))
    length = int(request.GET.get("length", 15))
    search_value = request.GET.get("search[value]", "")
    order_column = request.GET.get("order[0][column]", "2")  # Default sort by timestamp
    order_dir = request.GET.get("order[0][dir]", "desc")

    # Validate dates
    date_from, date_to = validate_filter_dates(date_from, date_to)

    # Base queryset - only get admin users' logs
    logs = UserActivityLog.objects.filter(
        user__user_type="ADMIN"  # Filter for admin users only
    ).select_related("user")  # Optimize user lookups

    # Apply filters if provided
    if admin_id:
        logs = logs.filter(user_id=int(admin_id))

    if activity_type:
        if activity_type.upper() == "OTHER":
            # For 'OTHER', exclude known activity types
            known_types = ["VIEW_", "CREATE_", "UPDATE_", "DELETE_", "LOGIN", "LOGOUT"]
            q_objects = Q()
            for prefix in known_types:
                q_objects |= Q(activity_type__istartswith=prefix)
            logs = logs.exclude(q_objects)
        else:
            # Handle consolidated activity types
            prefix = activity_type.upper()
            if prefix in ["VIEW", "CREATE", "UPDATE", "DELETE"]:
                logs = logs.filter(activity_type__istartswith=f"{prefix}_")
            else:
                logs = logs.filter(activity_type__iexact=activity_type)

    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)

    # Apply search if provided
    if search_value:
        logs = logs.filter(
            Q(user__email__icontains=search_value)
            | Q(activity_type__icontains=search_value)
            | Q(details__icontains=search_value)
            | Q(ip_address__icontains=search_value)
        )

    # Get total counts before pagination
    total_records = logs.count()
    total_filtered = total_records

    # Apply ordering
    column_ordering = {
        "0": "user__email",
        "1": "activity_type",
        "2": "timestamp",
        "3": "ip_address",
        "4": "details",
    }
    order_column = column_ordering.get(order_column, "timestamp")
    if order_dir == "desc":
        order_column = f"-{order_column}"
    logs = logs.order_by(order_column)

    # Handle AJAX request for DataTables
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        # Apply pagination
        logs_page = logs[start : start + length]

        data = []
        for log in logs_page:
            data.append(
                {
                    "user_email": log.user.email,
                    "activity_type": log.activity_type,
                    "timestamp": log.timestamp.isoformat(),
                    "ip_address": log.ip_address,
                    "details": log.details,
                }
            )

        return JsonResponse(
            {
                "draw": int(draw),
                "recordsTotal": total_records,
                "recordsFiltered": total_filtered,
                "data": data,
            }
        )

    # For regular page load, prepare context data
    raw_types = (
        UserActivityLog.objects.filter(user__user_type="ADMIN")
        .values_list("activity_type", flat=True)
        .distinct()
    )

    # Process activity types to be more user-friendly
    activity_types = set()
    for raw_type in raw_types:
        cleaned_type = raw_type.replace("_", " ").title()
        base_type = cleaned_type.split()[0]
        if base_type in ["View", "Create", "Update", "Delete"]:
            activity_types.add(base_type)
        else:
            activity_types.add(cleaned_type)

    activity_types.add("Other")
    activity_types = sorted(activity_types)

    # Get admin users who have activity logs
    admins_with_activity = (
        CustomUser.objects.filter(
            user_type="ADMIN", id__in=logs.values_list("user_id", flat=True)
        )
        .values("id", "email")
        .order_by("email")
    )

    context = {
        "activity_types": activity_types,
        "admins": admins_with_activity,
        "filter": {
            "admin_id": admin_id,
            "activity_type": activity_type,
            "date_from": date_from,
            "date_to": date_to,
        },
    }

    return render(request, "analytics/admin_activity.html", context)


def _calculate_growth(current, previous):
    """Helper function to calculate growth percentage"""
    if not previous or previous == 0:
        return 100 if current > 0 else 0

    change = current - previous
    percentage = (change / previous) * 100
    return round(percentage, 1)


@login_required
def reports_dashboard(request):
    """Dashboard for accessing all report types"""
    # First check if user is staff/admin, otherwise forbidden
    if (
        not request.user.is_staff
        and not request.user.is_superuser
        and request.user.user_type != "ADMIN"
    ):
        return HttpResponseForbidden("Access denied. Admin users only.")

    try:
        # Optimize query by selecting only needed fields and using select_related
        reports = (
            Report.objects.select_related("generated_by")
            .only(
                "id",
                "title",
                "report_type",
                "date_generated",
                "is_scheduled",
                "schedule_frequency",
                "generated_by__email",
                "generated_by__first_name",
                "generated_by__last_name",
            )
            .order_by("-date_generated")
        )

        # Filter by status if specified
        status = request.GET.get("status")
        if status == "scheduled":
            reports = reports.filter(is_scheduled=True)
        elif status == "one-time":
            reports = reports.filter(is_scheduled=False)

        # Add pagination with smaller page size for better performance
        paginator = Paginator(reports, 8)  # Show 8 reports per page
        page = request.GET.get("page")
        try:
            recent_reports = paginator.page(page)
        except PageNotAnInteger:
            recent_reports = paginator.page(1)
        except EmptyPage:
            recent_reports = paginator.page(paginator.num_pages)

        # For AJAX requests, separate the response based on Accept header
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            if request.headers.get("Accept") == "application/json":
                # Return only the minimal data needed for pagination in JSON format
                # This drastically reduces the response size
                reports_data = []
                for report in recent_reports:
                    # Format date as a readable string instead of using naturaltime
                    date_generated = report.date_generated
                    time_diff = timezone.now() - date_generated

                    if time_diff.days == 0:
                        if time_diff.seconds < 3600:
                            minutes = time_diff.seconds // 60
                            date_display = (
                                f"{minutes} minute{'s' if minutes != 1 else ''} ago"
                            )
                        else:
                            hours = time_diff.seconds // 3600
                            date_display = (
                                f"{hours} hour{'s' if hours != 1 else ''} ago"
                            )
                    elif time_diff.days == 1:
                        date_display = "Yesterday"
                    elif time_diff.days < 7:
                        date_display = f"{time_diff.days} days ago"
                    else:
                        date_display = date_generated.strftime("%b %d, %Y")

                    reports_data.append(
                        {
                            "id": report.id,
                            "title": report.title,
                            "report_type": report.report_type,
                            "report_type_display": report.get_report_type_display(),
                            "date_generated": report.date_generated.isoformat(),
                            "date_display": date_display,
                            "generated_by": report.generated_by.get_full_name()
                            or report.generated_by.email,
                        }
                    )

                return JsonResponse(
                    {
                        "reports": reports_data,
                        "has_next": recent_reports.has_next(),
                        "has_previous": recent_reports.has_previous(),
                        "current_page": recent_reports.number,
                        "total_pages": paginator.num_pages,
                        "page_range": list(paginator.page_range),
                        "next_page_number": recent_reports.next_page_number()
                        if recent_reports.has_next()
                        else None,
                        "previous_page_number": recent_reports.previous_page_number()
                        if recent_reports.has_previous()
                        else None,
                    }
                )
            else:
                # Return HTML snippet for backward compatibility
                html = render_to_string(
                    "analytics/reports_table.html",
                    {"recent_reports": recent_reports},
                    request=request,
                )
                return JsonResponse(
                    {
                        "html": html,
                        "has_next": recent_reports.has_next(),
                        "has_previous": recent_reports.has_previous(),
                        "current_page": recent_reports.number,
                        "total_pages": paginator.num_pages,
                    }
                )

        # Get only essential fields for scheduled reports
        scheduled_reports = (
            Report.objects.select_related("generated_by")
            .only(
                "id",
                "title",
                "report_type",
                "date_generated",
                "schedule_frequency",
                "generated_by__email",
                "generated_by__first_name",
                "generated_by__last_name",
            )
            .filter(
                is_scheduled=True,
                date_generated__gte=timezone.now() - timedelta(days=90),
            )
            .order_by("-date_generated")[:5]
        )

        context = {
            "recent_reports": recent_reports,
            "scheduled_reports": scheduled_reports,
        }

        return render(request, "analytics/reports_dashboard.html", context)

    except DatabaseError as e:
        messages.error(
            request,
            f"Error loading reports dashboard: {str(e)}. Please try again later.",
        )
        return redirect("analytics:dashboard")


@login_required
@user_passes_test(is_admin)
def report_list(request, report_type):
    """List all reports of a specific type"""
    # Map URL-friendly names to actual report types
    report_type_mapping = {
        "impact": "IMPACT",
        "transaction": "TRANSACTION",
        "user-activity": "USER_ACTIVITY",
        "compliance": "COMPLIANCE",
        "system": "SYSTEM",
    }

    # Get the actual report type from the mapping
    actual_report_type = report_type_mapping.get(report_type.lower())
    if not actual_report_type:
        messages.error(request, "Invalid report type")
        return redirect("analytics:reports_dashboard")

    reports = Report.objects.filter(report_type=actual_report_type)

    # Apply status filter if provided
    status = request.GET.get("status")
    if status == "scheduled":
        reports = reports.filter(is_scheduled=True)
    elif status == "one-time":
        reports = reports.filter(is_scheduled=False)

    paginator = Paginator(reports, 10)
    page = request.GET.get("page")
    reports = paginator.get_page(page)

    return render(
        request,
        "analytics/report_list.html",
        {
            "reports": reports,
            "report_type": report_type,
            "current_filter": status,
        },
    )


@login_required
@user_passes_test(is_admin)
def report_detail(request, report_id):
    """View a specific report's details"""
    try:
        report = Report.objects.get(pk=report_id)
        return render(request, "analytics/report_detail.html", {"report": report})
    except ObjectDoesNotExist:
        messages.error(request, "Report not found")
        return redirect("analytics:reports_dashboard")
    except DatabaseError as e:
        messages.error(request, f"Error retrieving report: {str(e)}")
        return redirect("analytics:reports_dashboard")


@login_required
@user_passes_test(is_admin)
def generate_report(request):
    """Generate a new report"""
    from django import forms
    from django.utils import timezone

    class ReportForm(forms.Form):
        report_type = forms.ChoiceField(choices=Report.REPORT_TYPES)
        title = forms.CharField()
        date_range_start = forms.DateField()
        date_range_end = forms.DateField()
        description = forms.CharField(required=False)

        def clean(self):
            cleaned_data = super().clean()
            start_date = cleaned_data.get("date_range_start")
            end_date = cleaned_data.get("date_range_end")

            # Use the system date for validation
            today = timezone.now().date()

            if start_date:
                if start_date > today:
                    self.add_error(
                        "date_range_start", "Start date cannot be in the future"
                    )
            if end_date:
                if end_date > today:
                    self.add_error("date_range_end", "End date cannot be in the future")
            if start_date and end_date and end_date < start_date:
                self.add_error("date_range_end", "End date cannot be before start date")
            return cleaned_data

    if request.method == "POST":
        form = ReportForm(request.POST)
        if form.is_valid():
            try:
                report_type = form.cleaned_data["report_type"]
                title = form.cleaned_data["title"]
                start_date = form.cleaned_data["date_range_start"]
                end_date = form.cleaned_data["date_range_end"]
                description = form.cleaned_data.get("description", "")

                # Validate date range
                if end_date < start_date:
                    form.add_error(None, "End date cannot be before start date")
                    return render(
                        request, "analytics/generate_report.html", {"form": form}
                    )

                # Map report types to generator functions
                generators = {
                    "IMPACT": Report.generate_impact_report,
                    "TRANSACTION": Report.generate_transaction_report,
                    "USER_ACTIVITY": Report.generate_user_activity_report,
                    "COMPLIANCE": Report.generate_compliance_report,
                    "SYSTEM": Report.generate_system_performance_report,
                }

                # Get the generator function
                generator = generators.get(report_type)
                if not generator:
                    form.add_error("report_type", "Invalid report type")
                    return render(
                        request, "analytics/generate_report.html", {"form": form}
                    )

                try:
                    # Generate the report
                    report = generator(
                        start_date=start_date,
                        end_date=end_date,
                        user=request.user,
                        title=title,
                    )

                    # Ensure report was created
                    if not report or not report.id:
                        # Create a basic report if generation failed
                        report = Report.objects.create(
                            title=title,
                            report_type=report_type,
                            date_range_start=start_date,
                            date_range_end=end_date,
                            generated_by=request.user,
                            data={"metrics": {}, "daily_trends": []},
                            summary=f"No data available for this {report_type.lower()} report",
                        )

                    if description:
                        report.description = description
                        report.save()

                    sweetify.success(request, "Report generated successfully", timer=3000)
                    return redirect("analytics:report_detail", report_id=report.id)

                except Exception as e:
                    form.add_error(None, f"Error generating report: {str(e)}")
                    return render(
                        request, "analytics/generate_report.html", {"form": form}
                    )

            except ValidationError as e:
                form.add_error(None, str(e))
                return render(request, "analytics/generate_report.html", {"form": form})

    else:
        initial_type = request.GET.get("type", "").upper()
        if initial_type and initial_type in dict(Report.REPORT_TYPES):
            form = ReportForm(initial={"report_type": initial_type})
        else:
            form = ReportForm()

    return render(request, "analytics/generate_report.html", {"form": form})


@login_required
@require_POST
def regenerate_report(request, report_id):
    """Regenerate an existing report with fresh data"""
    report = get_object_or_404(Report, id=report_id)
    try:
        # Get the appropriate generator function based on report type
        generator_functions = {
            "IMPACT": Report.generate_impact_report,
            "TRANSACTION": Report.generate_transaction_report,
            "USER_ACTIVITY": Report.generate_user_activity_report,
            "COMPLIANCE": Report.generate_compliance_report,
            "SYSTEM": Report.generate_system_performance_report,
        }
        
        generator = generator_functions.get(report.report_type)
        if not generator:
            raise ValueError(f"Unsupported report type: {report.report_type}")
        
        # Generate a fresh report with the same parameters
        fresh_report = generator(
            start_date=report.date_range_start,
            end_date=report.date_range_end,
            user=report.generated_by,
            title=report.title,
        )
        
        # Copy data from fresh report to original report
        report.data = fresh_report.data
        report.summary = fresh_report.summary
        
        # Update the timestamp to current time
        now = timezone.now()
        report.date_generated = now
        
        # Update the title to indicate it's regenerated (if not already marked)
        if not "- Regenerated" in report.title:
            report.title = f"{report.title} - Regenerated {now.strftime('%H:%M')}"
        
        # Save the updated original report
        report.save()
        
        # Delete the temporary fresh report
        fresh_report.delete()
        
        # Send success notification
        NotificationService.create_report_notification(
            report=report,
            notification_type="REPORT_GENERATED",
            user=request.user,
            extra_context={"regenerated": True},
        )
        
        # Log successful regeneration
        logger.info(f"Report {report_id} successfully regenerated by {request.user}")
        
        return JsonResponse(
            {"status": "success", "message": "Report regenerated successfully"}
        )
    except Exception as e:
        logger.error(f"Error regenerating report {report_id}: {str(e)}")
        NotificationService.create_report_notification(
            report=report,
            notification_type="REPORT_ERROR",
            user=request.user,
            extra_context={"error": str(e)},
        )
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@require_POST
def unschedule_report(request, report_id):
    """Remove scheduling from a report"""
    report = get_object_or_404(Report, id=report_id)
    if (
        request.user.is_staff
        or request.user.is_superuser
        or request.user == report.generated_by
    ):
        result = report.unschedule_report()
        return JsonResponse(result)
    return JsonResponse({"status": "error", "message": "Unauthorized"}, status=403)


@login_required
@require_POST
def schedule_report(request, report_id):
    """Schedule a report for periodic generation"""
    report = get_object_or_404(Report, id=report_id)
    if (
        request.user.is_staff
        or request.user.is_superuser
        or request.user == report.generated_by
    ):
        frequency = request.POST.get("frequency")
        schedule_time = request.POST.get("schedule_time")

        # Handle unscheduling
        if frequency == "UNSCHEDULE":
            result = report.unschedule_report()
            return JsonResponse(result)

        # Attempt to schedule the report
        result = report.schedule_report(frequency, schedule_time)
        return JsonResponse(result)
    return JsonResponse({"status": "error", "message": "Unauthorized"}, status=403)


@login_required
@require_POST
def delete_report(request, report_id):
    """Delete a report"""
    report = get_object_or_404(Report, id=report_id)
    try:
        report.delete()
        return JsonResponse(
            {"status": "success", "message": "Report deleted successfully"}
        )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@user_passes_test(is_admin)
def update_report(request, report_id):
    """Update a report's details"""
    try:
        report = Report.objects.get(pk=report_id)

        if request.method == "POST":
            title = request.POST.get("title")
            description = request.POST.get("description")

            if title:
                report.title = title
            if description:
                report.description = description

            try:
                report.full_clean()  # Validate before saving
                report.save()
                sweetify.success(request, "Report updated successfully", timer=3000)
                return redirect("analytics:report_detail", report_id=report.id)
            except ValidationError as e:
                sweetify.error(request, str(e), timer=5000)
                return render(
                    request, "analytics/update_report.html", {"report": report}
                )

        return render(request, "analytics/update_report.html", {"report": report})

    except ObjectDoesNotExist:
        sweetify.error(request, "Report not found", timer=3000)
        return redirect("analytics:reports_dashboard")


@login_required
@user_passes_test(is_admin)
def export_report(request, report_id, export_format):
    """Export a report in various formats"""
    try:
        report = Report.objects.get(pk=report_id)

        if export_format == "pdf":
            response = report.export_as_pdf()
            response["Content-Type"] = "application/pdf"
            filename = f"{report.title}.pdf"
        elif export_format == "csv":
            response = report.export_as_csv()
            response["Content-Type"] = "text/csv"
            filename = f"{report.title}.csv"
        elif export_format == "excel":
            response = report.export_as_excel()
            response["Content-Type"] = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            filename = f"{report.title}.xlsx"
        else:
            messages.error(request, "Invalid export format")
            return redirect("analytics:report_detail", report_id=report.id)

        # Ensure filename is URL safe and properly encoded
        filename = "".join(
            c for c in filename if c.isalnum() or c in (" ", "-", "_", ".")
        ).rstrip()
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    except ObjectDoesNotExist:
        messages.error(request, "Report not found")
        return redirect("analytics:reports_dashboard")
    except (ValidationError, DatabaseError) as e:
        messages.error(request, f"Error exporting report: {str(e)}")
        return redirect("analytics:report_detail", report_id=report_id)


@login_required
def analytics_dashboard(request):
    """Main analytics dashboard view"""
    return render(request, "analytics/dashboard.html")


@login_required
@user_passes_test(lambda u: u.user_type == "ADMIN")
def admin_analytics_dashboard(request):
    """Admin view for analytics management"""
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)

    # Get recent impact metrics
    impact_metrics = ImpactMetrics.objects.filter(date__gte=week_ago).order_by("-date")

    # Get system metrics
    system_metrics = SystemMetrics.objects.filter(date__gte=week_ago).order_by("-date")

    # Get active user breakdown
    user_breakdown = (
        UserActivityLog.objects.filter(timestamp__date__gte=week_ago)
        .values("user__user_type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # Get most active listings
    top_listings = (
        DailyAnalytics.objects.filter(date__gte=week_ago)
        .values("listing__title", "listing__supplier__email")
        .annotate(
            total_requests=Sum("requests_received"),
            total_food_saved=Sum("food_saved_kg"),
        )
        .order_by("-total_requests")[:10]
    )

    return render(
        request,
        "analytics/admin/analytics_dashboard.html",
        {
            "impact_metrics": impact_metrics,
            "system_metrics": system_metrics,
            "user_breakdown": user_breakdown,
            "top_listings": top_listings,
            "section": "analytics",
        },
    )


@login_required
def business_analytics(request):
    """Business analytics view for businesses to track their impact"""
    if request.user.user_type != "BUSINESS":
        return HttpResponseForbidden("Access denied. Business accounts only.")

    today = timezone.now().date()
    month_ago = today - timedelta(days=30)

    try:
        # Get daily analytics with proper aggregation
        daily_metrics = list(
            DailyAnalytics.objects.filter(
                user=request.user, date__gte=month_ago, date__lte=today
            )
            .values("date")
            .annotate(
                daily_food=Sum("food_saved_kg"),
                daily_requests=Sum("requests_received"),
                daily_fulfilled=Sum("requests_fulfilled"),
            )
            .order_by("date")
        )

        # Calculate running totals
        running_food_total = 0
        running_requests_total = 0
        running_fulfilled_total = 0

        for metric in daily_metrics:
            running_food_total += float(metric["daily_food"] or 0)
            running_requests_total += int(metric["daily_requests"] or 0)
            running_fulfilled_total += int(metric["daily_fulfilled"] or 0)
            metric["cumulative_food"] = running_food_total
            metric["cumulative_requests"] = running_requests_total
            metric["cumulative_fulfilled"] = running_fulfilled_total

        # Get active listings count
        active_listings_count = FoodListing.objects.filter(
            supplier=request.user, status="ACTIVE"
        ).count()

        # Get actual request and completion counts directly from transactions
        from transactions.models import FoodRequest, Transaction

        total_requests = FoodRequest.objects.filter(
            listing__supplier=request.user
        ).count()
        total_completed = Transaction.objects.filter(
            request__listing__supplier=request.user, status="COMPLETED"
        ).count()

        # Calculate food weights by type (commercial vs donation)
        from django.db.models import Case, When

        food_by_type = Transaction.objects.filter(
            request__listing__supplier=request.user, status="COMPLETED"
        ).aggregate(
            commercial_weight=Sum(
                Case(
                    When(
                        request__listing__listing_type="COMMERCIAL",
                        then="request__quantity_requested",
                    ),
                    default=0,
                    output_field=models.DecimalField(),
                )
            ),
            donation_weight=Sum(
                Case(
                    When(
                        request__listing__listing_type__in=[
                            "DONATION",
                            "NONPROFIT_ONLY",
                        ],
                        then="request__quantity_requested",
                    ),
                    default=0,
                    output_field=models.DecimalField(),
                )
            ),
        )

        # Calculate total food weight and percentages
        commercial_weight = float(food_by_type["commercial_weight"] or 0)
        donation_weight = float(food_by_type["donation_weight"] or 0)
        total_food_weight = commercial_weight + donation_weight

        # Calculate percentages (avoid division by zero)
        if total_food_weight > 0:
            commercial_percentage = (commercial_weight / total_food_weight) * 100
            donation_percentage = (donation_weight / total_food_weight) * 100
        else:
            commercial_percentage = 0
            donation_percentage = 0

        # Calculate environmental impact
        co2_saved = total_food_weight * 2.5  # 2.5 kg CO2 per kg food saved
        water_saved = total_food_weight * 1000  # 1000L water per kg food saved

        # Format chart data
        monthly_data = {
            "labels": [d["date"].strftime("%b %d") for d in daily_metrics],
            "food_data": [d["cumulative_food"] for d in daily_metrics],
            "requests_data": [d["cumulative_requests"] for d in daily_metrics],
        }

        context = {
            "title": "Business Analytics",
            "stats": {
                "listings": active_listings_count,
                "completed": total_completed,
                "food_weight": total_food_weight,
                "co2_saved": co2_saved,
                "car_equivalent": int(co2_saved * 2.4),  # 2.4 miles per kg CO2
                "water_saved": int(water_saved),
                "requests": total_requests,
                "commercial_weight": commercial_weight,
                "donation_weight": donation_weight,
                "commercial_percentage": commercial_percentage,
                "donation_percentage": donation_percentage,
            },
            "monthly_data": monthly_data,
        }

        return render(request, "analytics/business_analytics.html", context)

    except (ValidationError, ObjectDoesNotExist) as e:
        messages.error(request, f"Error calculating analytics: {str(e)}")
        return redirect("analytics:dashboard")


@login_required
@user_passes_test(is_admin)
def all_reports(request):
    """View all reports with bulk selection capability"""
    try:
        # Filter parameters
        report_type = request.GET.get("type", "")
        start_date = request.GET.get("start_date", "")
        end_date = request.GET.get("end_date", "")

        # Base queryset with optimization
        reports = Report.objects.select_related("generated_by").order_by(
            "-date_generated"
        )

        # Apply filters if provided
        if report_type:
            # Check if the report type exists in valid choices
            valid_types = dict(Report.REPORT_TYPES).keys()
            normalized_type = report_type.upper()
            if normalized_type in valid_types:
                reports = reports.filter(report_type=normalized_type)

        # Only apply date filters if they are valid non-empty strings
        if start_date and start_date.strip():
            try:
                # Convert start_date string to datetime, set time to start of day
                start_datetime = timezone.make_aware(
                    datetime.strptime(start_date.strip(), "%Y-%m-%d").replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                )
                reports = reports.filter(date_generated__gte=start_datetime)
            except (ValueError, TypeError):
                # Log the error but don't halt execution
                logger.warning(f"Invalid start_date format: {start_date}")

        if end_date and end_date.strip():
            try:
                # Convert end_date string to datetime, set time to end of day
                end_datetime = timezone.make_aware(
                    datetime.strptime(end_date.strip(), "%Y-%m-%d").replace(
                        hour=23, minute=59, second=59, microsecond=999999
                    )
                )
                reports = reports.filter(date_generated__lte=end_datetime)
            except (ValueError, TypeError):
                # Log the error but don't halt execution
                logger.warning(f"Invalid end_date format: {end_date}")

        paginator = Paginator(reports, 15)  # Show 15 reports per page
        page = request.GET.get("page")

        try:
            reports_page = paginator.page(page)
        except PageNotAnInteger:
            reports_page = paginator.page(1)
        except EmptyPage:
            reports_page = paginator.page(paginator.num_pages)

        # Prepare report type choices for filter dropdown
        report_type_choices = [
            {"value": type_code, "display": type_display}
            for type_code, type_display in Report.REPORT_TYPES
        ]

        context = {
            "reports": reports_page,
            "report_type_choices": report_type_choices,
            "filters": {
                "report_type": report_type,
                "start_date": start_date,
                "end_date": end_date,
            },
            "selected_count": 0,  # Initial count for JavaScript tracking
        }

        return render(request, "analytics/all_reports.html", context)

    except DatabaseError as e:
        messages.error(
            request,
            f"Error loading reports: {str(e)}. Please try again later.",
        )
        return redirect("analytics:reports_dashboard")


@login_required
@user_passes_test(is_admin)
def bulk_delete_reports(request):
    """Delete multiple reports at once"""
    if request.method == "POST":
        report_ids = request.POST.getlist("report_ids")

        # Preserve filter state for redirect
        redirect_params = {}
        if request.POST.get("type"):
            redirect_params["type"] = request.POST.get("type")
        if request.POST.get("start_date"):
            redirect_params["start_date"] = request.POST.get("start_date")
        if request.POST.get("end_date"):
            redirect_params["end_date"] = request.POST.get("end_date")
        if request.POST.get("page"):
            redirect_params["page"] = request.POST.get("page")

        try:
            deleted_count = Report.objects.filter(id__in=report_ids).delete()[0]
            messages.success(
                request,
                f"Successfully deleted {deleted_count} report{'s' if deleted_count != 1 else ''}",
            )
        except DatabaseError as e:
            messages.error(request, f"Error deleting reports: {str(e)}")

        # Redirect back to all_reports with preserved filters
        redirect_url = reverse("analytics:all_reports")
        if redirect_params:
            redirect_url += "?" + urlencode(redirect_params)
        return redirect(redirect_url)

    return redirect("analytics:all_reports")


@login_required
def business_analytics_data(request):
    """API endpoint for real-time business analytics data"""
    if not request.user.user_type == "BUSINESS":
        return JsonResponse({"error": "Unauthorized"}, status=403)

    try:
        # Get data from cache first
        cache_key = f"business_analytics_{request.user.id}"
        cached_data = caches["analytics"].get(cache_key)

        if cached_data:
            return JsonResponse(cached_data)

        # Calculate metrics if not in cache
        today = timezone.now().date()
        month_ago = today - timedelta(days=30)

        # Get user's listings
        listings = FoodListing.objects.filter(supplier=request.user)
        active_listings = listings.filter(status="ACTIVE").count()

        # Get requests data
        requests = FoodRequest.objects.filter(listing__supplier=request.user)
        total_requests = requests.count()
        completed_requests = requests.filter(status="COMPLETED").count()

        # Calculate food saved (only from completed requests)
        food_saved = (
            FoodRequest.objects.filter(
                listing__supplier=request.user,
                status="COMPLETED"
            ).aggregate(total_kg=Sum("quantity_requested"))["total_kg"]
            or 0
        )

        # Calculate success rate from completed requests
        success_rate = (
            (completed_requests / total_requests * 100) if total_requests > 0 else 0
        )

        # Get daily metrics with proper date range
        date_range = []
        current_date = month_ago
        while current_date <= today:
            date_range.append(current_date)
            current_date += timedelta(days=1)

        # Get activity metrics for each day in range
        daily_metrics = {
            date: {
                "daily_food": 0,
                "daily_requests": 0,
                "daily_fulfilled": 0,
                "cumulative_food": 0,
                "cumulative_requests": 0,
                "cumulative_fulfilled": 0,
            }
            for date in date_range
        }

        # Get actual metrics from database
        db_metrics = (
            DailyAnalytics.objects.filter(
                user=request.user, date__gte=month_ago, date__lte=today
            )
            .values("date")
            .annotate(
                daily_food=Sum("food_saved_kg"),
                daily_requests=Sum("requests_received"),
                daily_fulfilled=Sum("requests_fulfilled"),
            )
            .order_by("date")
        )

        # Update daily metrics with actual data and prepare timeline data
        timeline_listings = []  # List to store daily listing counts
        timeline_requests = []  # List to store daily request counts

        # Get daily listing counts
        listing_counts = (
            FoodListing.objects.filter(
                supplier=request.user,
                created_at__date__gte=month_ago,
                created_at__date__lte=today,
            )
            .values("created_at__date")
            .annotate(count=Count("id"))
            .order_by("created_at__date")
        )

        listing_count_dict = {
            item["created_at__date"]: item["count"] for item in listing_counts
        }

        # Get daily request counts
        request_counts = (
            FoodRequest.objects.filter(
                listing__supplier=request.user,
                created_at__date__gte=month_ago,
                created_at__date__lte=today,
            )
            .values("created_at__date")
            .annotate(count=Count("id"))
            .order_by("created_at__date")
        )

        request_count_dict = {
            item["created_at__date"]: item["count"] for item in request_counts
        }

        # Update running totals and timeline data
        running_food = 0
        running_requests = 0
        running_fulfilled = 0

        for date in date_range:
            # Get daily counts or default to 0
            daily_listings = listing_count_dict.get(date, 0)
            daily_requests = request_count_dict.get(date, 0)

            # Add to timeline data
            timeline_listings.append(daily_listings)
            timeline_requests.append(daily_requests)

            # Update metrics for the day
            metrics = daily_metrics[date]
            db_metric = next((m for m in db_metrics if m["date"] == date), None)

            if db_metric:
                daily_food = float(db_metric["daily_food"] or 0)
                daily_requests = int(db_metric["daily_requests"] or 0)
                daily_fulfilled = int(db_metric["daily_fulfilled"] or 0)

                running_food += daily_food
                running_requests += daily_requests
                running_fulfilled += daily_fulfilled

                metrics.update(
                    {
                        "daily_food": daily_food,
                        "daily_requests": daily_requests,
                        "daily_fulfilled": daily_fulfilled,
                        "cumulative_food": running_food,
                        "cumulative_requests": running_requests,
                        "cumulative_fulfilled": running_fulfilled,
                    }
                )

        # Get request distribution data for pie chart
        request_status = (
            FoodRequest.objects.filter(listing__supplier=request.user)
            .values("status")
            .annotate(count=Count("id"))
            .order_by("status")
        )

        request_labels = []
        request_data = []
        for status in request_status:
            request_labels.append(status["status"].title())
            request_data.append(status["count"])

        # Compile response data
        response_data = {
            "metrics": {
                "total_listings": active_listings,
                "total_requests": total_requests,
                "food_saved": float(food_saved),
                "success_rate": float(success_rate),
            },
            "daily_metrics": [
                {"date": date.strftime("%Y-%m-%d"), **metrics}
                for date, metrics in daily_metrics.items()
            ],
            "charts": {
                "activity": {
                    "labels": [date.strftime("%Y-%m-%d") for date in date_range],
                    "listings": timeline_listings,
                    "requests": timeline_requests,
                },
                "requests": {"labels": request_labels, "data": request_data},
            },
        }

        # Cache the data for 1 minute
        caches["analytics"].set(cache_key, response_data, 60)

        return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"Error in business_analytics_data: {str(e)}")
        return JsonResponse({"error": "Internal server error"}, status=500)


@login_required
def business_export(request, export_format):
    """Export business analytics data in various formats"""
    if request.user.user_type != "BUSINESS":
        return HttpResponseForbidden("Access denied. Business accounts only.")

    try:
        # Get latest analytics data
        today = timezone.now().date()
        month_ago = today - timedelta(days=30)

        # Get daily analytics data
        daily_metrics = (
            DailyAnalytics.objects.filter(
                user=request.user, date__gte=month_ago, date__lte=today
            )
            .values("date")
            .annotate(
                daily_food=Sum("food_saved_kg"),
                daily_requests=Sum("requests_received"),
                daily_fulfilled=Sum("requests_fulfilled"),
            )
            .order_by("date")
        )

        # Calculate totals
        running_food_total = 0
        running_requests_total = 0
        running_fulfilled_total = 0
        formatted_metrics = []

        for metric in daily_metrics:
            running_food_total += float(metric["daily_food"] or 0)
            running_requests_total += int(metric["daily_requests"] or 0)
            running_fulfilled_total += int(metric["daily_fulfilled"] or 0)

            formatted_metrics.append(
                {
                    "date": metric["date"],
                    "daily_food": float(metric["daily_food"] or 0),
                    "daily_requests": int(metric["daily_requests"] or 0),
                    "daily_fulfilled": int(metric["daily_fulfilled"] or 0),
                    "cumulative_food": running_food_total,
                    "cumulative_requests": running_requests_total,
                    "cumulative_fulfilled": running_fulfilled_total,
                }
            )

        # Get active listings count
        active_listings = FoodListing.objects.filter(
            supplier=request.user, status="ACTIVE"
        ).count()

        # Handle different export formats
        if export_format == "pdf":
            return export_business_pdf(request.user, formatted_metrics, active_listings)
        elif export_format == "csv":
            return export_business_csv(request.user, formatted_metrics, active_listings)
        elif export_format == "excel":
            return export_business_excel(
                request.user, formatted_metrics, active_listings
            )
        else:
            return JsonResponse({"error": "Invalid export format"}, status=400)

    except Exception as e:
        logger.error(f"Error exporting business analytics: {str(e)}")
        return JsonResponse({"error": "Export failed"}, status=500)


def export_business_pdf(user, metrics, active_listings):
    """Export business analytics as PDF with enhanced formatting"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,  # Slightly reduced margins for better space usage
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
        title="Business Analytics Report",
    )

    elements = []
    styles = getSampleStyleSheet()

    # Enhanced title style with better spacing
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        spaceAfter=25,
        spaceBefore=15,
        textColor=colors.HexColor("#2c3e50"),
        alignment=1,
        leading=30,  # Improved line spacing
    )
    elements.append(Paragraph("Business Analytics Report", title_style))

    # Business info style
    info_style = ParagraphStyle(
        "InfoStyle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#34495e"),
        spaceAfter=5,
        spaceBefore=5,
        leading=14,
    )
    elements.append(Paragraph(f"Generated for: {user.email}", info_style))
    elements.append(Paragraph(f"Date: {timezone.now().strftime('%B %d, %Y')}", info_style))
    elements.append(Spacer(1, 20))

    # Overview section with enhanced styling
    overview_style = ParagraphStyle(
        "Overview",
        parent=styles["Heading2"],
        fontSize=16,
        spaceBefore=15,
        spaceAfter=15,
        textColor=colors.HexColor("#2c3e50"),
        leading=20,
    )
    elements.append(Paragraph("Overview Metrics", overview_style))

    # Get actual request and completion counts directly from transactions
    from transactions.models import FoodRequest, Transaction
    
    # Get actual transaction-based metrics to match the dashboard view
    total_requests = FoodRequest.objects.filter(
        listing__supplier=user
    ).count()
    
    total_completed = Transaction.objects.filter(
        request__listing__supplier=user, status="COMPLETED"
    ).count()
    
    # Calculate food weights by type (commercial vs donation)
    from django.db.models import Case, When
    
    food_by_type = Transaction.objects.filter(
        request__listing__supplier=user, status="COMPLETED"
    ).aggregate(
        commercial_weight=Sum(
            Case(
                When(
                    request__listing__listing_type="COMMERCIAL",
                    then="request__quantity_requested",
                ),
                default=0,
                output_field=models.DecimalField(),
            )
        ),
        donation_weight=Sum(
            Case(
                When(
                    request__listing__listing_type__in=[
                        "DONATION",
                        "NONPROFIT_ONLY",
                    ],
                    then="request__quantity_requested",
                ),
                default=0,
                output_field=models.DecimalField(),
            )
        ),
    )
    
    # Calculate total food weight and percentages
    commercial_weight = float(food_by_type["commercial_weight"] or 0)
    donation_weight = float(food_by_type["donation_weight"] or 0)
    total_food_weight = commercial_weight + donation_weight
    
    # Calculate environmental impact
    co2_saved = total_food_weight * 2.5  # 2.5 kg CO2 per kg food saved
    water_saved = total_food_weight * 1000  # 1000L water per kg food saved
    
    # Calculate success rate
    success_rate = (float(total_completed) / float(total_requests) * 100) if total_requests > 0 else 0.0

    # Create overview metrics table with improved spacing
    overview_data = [
        ["Metric", "Value"],
        ["Active Listings", str(active_listings)],
        ["Total Requests", str(total_requests)],
        ["Completed Requests", str(total_completed)],
        ["Food Saved (kg)", f"{total_food_weight:.1f}"],
        ["CO2 Saved (kg)", f"{co2_saved:.1f}"],
        ["Success Rate (%)", f"{success_rate:.1f}"],
    ]

    # Create overview table with specific widths and styling
    overview_table = Table(overview_data, colWidths=[300, 200], rowHeights=25)
    overview_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 12),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#2c3e50")),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),  # Left align first column
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),  # Right align second column
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),  # Consistent cell padding
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    elements.append(overview_table)
    elements.append(Spacer(1, 25))

    # Business distribution section
    if commercial_weight > 0 or donation_weight > 0:
        elements.append(Paragraph("Food Distribution by Type", overview_style))
        
        # Calculate percentages
        if total_food_weight > 0:
            commercial_percentage = (commercial_weight / total_food_weight)
            donation_percentage = (donation_weight / total_food_weight)
        else:
            commercial_percentage = 0
            donation_percentage = 0
            
        distribution_data = [
            ["Type", "Weight (kg)", "Percentage (%)"],
            ["Commercial", f"{commercial_weight:.1f}", f"{commercial_percentage:.1f}"],
            ["Donation", f"{donation_weight:.1f}", f"{donation_percentage:.1f}"],
            ["Total", f"{total_food_weight:.1f}", "100.0"],
        ]
        
        distribution_table = Table(distribution_data, colWidths=[200, 150, 150], rowHeights=25)
        distribution_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 12),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
            ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#2c3e50")),
            ("ALIGN", (0, 1), (0, -1), "LEFT"),  # Left align type column
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),  # Right align numeric columns
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]))
        elements.append(distribution_table)
        elements.append(Spacer(1, 25))

    # Detailed metrics section with enhanced styling
    if metrics:
        elements.append(Paragraph("Detailed Daily Metrics", overview_style))
        
        # Column widths optimized for content
        col_widths = [90, 85, 85, 85, 85, 85, 85]  # Total ~600 points
        
        table_data = [
            [
                "Date",
                "Daily Food\n(kg)",
                "Daily\nRequests",
                "Completed\nRequests",
                "Total Food\n(kg)",
                "Total\nRequests",
                "Success\nRate (%)",
            ]
        ]

        # Add data rows with proper formatting - keep this part as it's just historical data
        for metric in metrics:
            success_rate = (metric["daily_fulfilled"] / metric["daily_requests"] * 100) if metric["daily_requests"] > 0 else 0.0
            table_data.append([
                metric["date"].strftime("%Y-%m-%d"),
                f"{metric['daily_food']:.1f}",
                str(metric["daily_requests"]),
                str(metric["daily_fulfilled"]),
                f"{metric['cumulative_food']:.1f}",
                str(metric["cumulative_requests"]),
                f"{success_rate:.1f}",
            ])

        # Create detailed table with specific styling
        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            # Header styling
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            # Data rows styling
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
            ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#2c3e50")),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            # Alignment
            ("ALIGN", (0, 1), (0, -1), "LEFT"),  # Date column left aligned
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),  # Numeric columns right aligned
            # Grid styling
            ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            # Alternate row colors for better readability
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            # Line height
            ("LEADING", (0, 0), (-1, -1), 12),
        ]))
        elements.append(table)

    # Build PDF
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="business_analytics.pdf"'
    response.write(pdf)
    return response


def export_business_csv(user, metrics, active_listings):
    """Export business analytics as CSV"""
    output = StringIO()
    writer = csv.writer(output)

    # Write title and overview
    writer.writerow(["Business Analytics Report"])
    writer.writerow([])
    writer.writerow(["Overview Metrics"])
    
    # Get actual request and completion counts directly from transactions
    from transactions.models import FoodRequest, Transaction
    
    # Get actual transaction-based metrics to match the dashboard view
    total_requests = FoodRequest.objects.filter(
        listing__supplier=user
    ).count()
    
    total_completed = Transaction.objects.filter(
        request__listing__supplier=user, status="COMPLETED"
    ).count()
    
    # Calculate food weights by type (commercial vs donation)
    from django.db.models import Case, When
    
    food_by_type = Transaction.objects.filter(
        request__listing__supplier=user, status="COMPLETED"
    ).aggregate(
        commercial_weight=Sum(
            Case(
                When(
                    request__listing__listing_type="COMMERCIAL",
                    then="request__quantity_requested",
                ),
                default=0,
                output_field=models.DecimalField(),
            )
        ),
        donation_weight=Sum(
            Case(
                When(
                    request__listing__listing_type__in=[
                        "DONATION",
                        "NONPROFIT_ONLY",
                    ],
                    then="request__quantity_requested",
                ),
                default=0,
                output_field=models.DecimalField(),
            )
        ),
    )
    
    # Calculate total food weight and percentages
    commercial_weight = float(food_by_type["commercial_weight"] or 0)
    donation_weight = float(food_by_type["donation_weight"] or 0)
    total_food_weight = commercial_weight + donation_weight
    
    # Calculate environmental impact
    co2_saved = total_food_weight * 2.5  # 2.5 kg CO2 per kg food saved
    water_saved = total_food_weight * 1000  # 1000L water per kg food saved
    
    # Calculate success rate
    success_rate = (float(total_completed) / float(total_requests) * 100) if total_requests > 0 else 0.0
    
    # Write overview metrics data
    writer.writerow(["Active Listings", active_listings])
    writer.writerow(["Total Requests", total_requests])
    writer.writerow(["Completed Requests", total_completed])
    writer.writerow(["Food Saved (kg)", f"{total_food_weight:.1f}"])
    writer.writerow(["CO2 Saved (kg)", f"{co2_saved:.1f}"])
    writer.writerow(["Success Rate (%)", f"{success_rate:.1f}"])
    writer.writerow([])
    
    # Write food distribution data
    writer.writerow(["Food Distribution by Type"])
    writer.writerow(["Type", "Weight (kg)", "Percentage (%)"])
    
    # Calculate percentages
    if total_food_weight > 0:
        commercial_percentage = (commercial_weight / total_food_weight) * 100
        donation_percentage = (donation_weight / total_food_weight) * 100
    else:
        commercial_percentage = 0
        donation_percentage = 0
        
    writer.writerow(["Commercial", f"{commercial_weight:.1f}", f"{commercial_percentage:.1f}"])
    writer.writerow(["Donation", f"{donation_weight:.1f}", f"{donation_percentage:.1f}"])
    writer.writerow(["Total", f"{total_food_weight:.1f}", "100.0"])
    writer.writerow([])

    # Write detailed metrics
    writer.writerow(["Detailed Daily Metrics"])
    writer.writerow([
        "Date",
        "Daily Food (kg)",
        "Daily Requests",
        "Completed",
        "Total Food (kg)",
        "Total Requests",
        "Success Rate (%)",
    ])

    # Keep the historical data from DailyAnalytics
    for metric in metrics:
        daily_success_rate = (metric["daily_fulfilled"] / metric["daily_requests"] * 100) if metric["daily_requests"] > 0 else 0.0
        writer.writerow([
            metric["date"].strftime("%Y-%m-%d"),
            f"{metric['daily_food']:.1f}",
            metric["daily_requests"],
            metric["daily_fulfilled"],
            f"{metric['cumulative_food']:.1f}",
            metric["cumulative_requests"],
            f"{daily_success_rate:.1f}",
        ])

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="business_analytics.csv"'
    response.write(output.getvalue())
    return response


def export_business_excel(user, metrics, active_listings):
    """Export business analytics as Excel"""
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()

    # Get actual request and completion counts directly from transactions
    from transactions.models import FoodRequest, Transaction
    
    # Get actual transaction-based metrics to match the dashboard view
    total_requests = FoodRequest.objects.filter(
        listing__supplier=user
    ).count()
    
    total_completed = Transaction.objects.filter(
        request__listing__supplier=user, status="COMPLETED"
    ).count()
    
    # Calculate food weights by type (commercial vs donation)
    from django.db.models import Case, When
    
    food_by_type = Transaction.objects.filter(
        request__listing__supplier=user, status="COMPLETED"
    ).aggregate(
        commercial_weight=Sum(
            Case(
                When(
                    request__listing__listing_type="COMMERCIAL",
                    then="request__quantity_requested",
                ),
                default=0,
                output_field=models.DecimalField(),
            )
        ),
        donation_weight=Sum(
            Case(
                When(
                    request__listing__listing_type__in=[
                        "DONATION",
                        "NONPROFIT_ONLY",
                    ],
                    then="request__quantity_requested",
                ),
                default=0,
                output_field=models.DecimalField(),
            )
        ),
    )
    
    # Calculate total food weight and percentages
    commercial_weight = float(food_by_type["commercial_weight"] or 0)
    donation_weight = float(food_by_type["donation_weight"] or 0)
    total_food_weight = commercial_weight + donation_weight
    
    # Calculate percentages
    if total_food_weight > 0:
        commercial_percentage = commercial_weight / total_food_weight
        donation_percentage = donation_weight / total_food_weight
    else:
        commercial_percentage = 0
        donation_percentage = 0
    
    # Calculate environmental impact
    co2_saved = total_food_weight * 2.5  # 2.5 kg CO2 per kg food saved
    water_saved = total_food_weight * 1000  # 1000L water per kg food saved
    
    # Calculate success rate
    success_rate = (float(total_completed) / float(total_requests) * 100) if total_requests > 0 else 0.0
    

    # Add formats
    title_format = workbook.add_format({
        "bold": True,
        "font_size": 16,
        "font_color": "#2c3e50",
        "align": "center",
        "valign": "vcenter",
    })
    header_format = workbook.add_format({
        "bold": True,
        "font_size": 11,
        "bg_color": "#3498db",
        "font_color": "white",
        "align": "center",
        "valign": "vcenter",
        "border": 1,
    })
    cell_format = workbook.add_format({
        "font_size": 10,
        "align": "right",
        "valign": "vcenter",
        "border": 1,
    })
    left_align_format = workbook.add_format({
        "font_size": 10,
        "align": "left",
        "valign": "vcenter",
        "border": 1,
    })
    date_format = workbook.add_format({
        "font_size": 10,
        "align": "left",
        "valign": "vcenter",
        "border": 1,
        "num_format": "yyyy-mm-dd",
    })
    number_format = workbook.add_format({
        "font_size": 10,
        "align": "right",
        "valign": "vcenter",
        "border": 1,
        "num_format": "#,##0.0",
    })
    percent_format = workbook.add_format({
        "font_size": 10,
        "align": "right",
        "valign": "vcenter",
        "border": 1,
        "num_format": "0.0%",
    })

    # Write title
    worksheet.merge_range("A1:G1", "Business Analytics Report", title_format)
    
    # Write overview section header
    worksheet.merge_range("A3:B3", "Overview Metrics", header_format)
    
    # Write actual transaction-based overview metrics
    overview_data = [
        ["Active Listings", active_listings],
        ["Total Requests", total_requests],
        ["Completed Requests", total_completed],
        ["Food Saved (kg)", total_food_weight],
        ["CO2 Saved (kg)", co2_saved],
        ["Success Rate (%)", success_rate / 100],  # Convert to decimal for percentage format
    ]
    
    current_row = 4
    for label, value in overview_data:
        worksheet.write(current_row, 0, label, left_align_format)
        if isinstance(value, float):
            if label == "Success Rate (%)":
                worksheet.write(current_row, 1, value, percent_format)
            else:
                worksheet.write(current_row, 1, value, number_format)
        else:
            worksheet.write(current_row, 1, value, cell_format)
        current_row += 1
    
    # Add space before distribution section
    current_row += 1
    
    # Write food distribution section
    if commercial_weight > 0 or donation_weight > 0:
        worksheet.merge_range(current_row, 0, current_row, 2, "Food Distribution by Type", header_format)
        current_row += 1
        
        # Write distribution headers
        dist_headers = ["Type", "Weight (kg)", "Percentage (%)"]
        for col, header in enumerate(dist_headers):
            worksheet.write(current_row, col, header, header_format)
        current_row += 1
        
        # Write distribution data
        worksheet.write(current_row, 0, "Commercial", left_align_format)
        worksheet.write(current_row, 1, commercial_weight, number_format)
        worksheet.write(current_row, 2, commercial_percentage, percent_format)
        current_row += 1
        
        worksheet.write(current_row, 0, "Donation", left_align_format)
        worksheet.write(current_row, 1, donation_weight, number_format)
        worksheet.write(current_row, 2, donation_percentage, percent_format)
        current_row += 1
        
        worksheet.write(current_row, 0, "Total", left_align_format)
        worksheet.write(current_row, 1, total_food_weight, number_format)
        worksheet.write(current_row, 2, 1.0, percent_format)  # 100%
        current_row += 2
    
    # Write detailed metrics section
    if metrics:
        worksheet.merge_range(current_row, 0, current_row, 6, "Detailed Daily Metrics", header_format)
        current_row += 1
        
        # Write headers
        headers = [
            "Date",
            "Daily Food (kg)",
            "Daily Requests",
            "Completed",
            "Total Food (kg)",
            "Total Requests",
            "Success Rate (%)",
        ]
        for col, header in enumerate(headers):
            worksheet.write(current_row, col, header, header_format)
        
        # Write data
        current_row += 1
        for metric in metrics:
            daily_success_rate = (metric["daily_fulfilled"] / metric["daily_requests"] * 100) if metric["daily_requests"] > 0 else 0.0
            worksheet.write(current_row, 0, metric["date"], date_format)
            worksheet.write(current_row, 1, metric["daily_food"], number_format)
            worksheet.write(current_row, 2, metric["daily_requests"], cell_format)
            worksheet.write(current_row, 3, metric["daily_fulfilled"], cell_format)
            worksheet.write(current_row, 4, metric["cumulative_food"], number_format)
            worksheet.write(current_row, 5, metric["cumulative_requests"], cell_format)
            worksheet.write(current_row, 6, daily_success_rate / 100, percent_format)  # Convert to decimal for percentage format
            current_row += 1

    # Adjust column widths
    worksheet.set_column("A:A", 15)  # Date
    worksheet.set_column("B:G", 15)  # Data columns

    workbook.close()

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="business_analytics.xlsx"'
    return response
