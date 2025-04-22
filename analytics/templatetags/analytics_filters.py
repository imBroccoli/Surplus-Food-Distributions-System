from django import template
from django.template.defaultfilters import floatformat

register = template.Library()


@register.filter
def format_report_type(value):
    """Format report type for display"""
    if not value:
        return ""
    # First convert URL-friendly format to database format
    value = value.lower().replace("-", "_")
    # Then format for display
    return value.replace("_", " ")


@register.filter
def format_activity_type(value):
    """Format activity type for display"""
    if not value:
        return "Unknown"

    # Replace underscores with spaces and title case
    formatted = value.replace("_", " ").title()

    # Handle special cases
    if formatted.startswith("View "):
        return "View"
    if formatted.startswith("Create "):
        return "Create"
    if formatted.startswith("Update "):
        return "Update"
    if formatted.startswith("Delete "):
        return "Delete"

    return formatted


@register.filter
def percentage(value, total):
    """Calculate percentage safely"""
    try:
        if total in (None, 0):
            return 0
        return floatformat(float(value) / float(total) * 100, 1)
    except (ValueError, ZeroDivisionError, TypeError):
        return 0


@register.filter
def absolute(value):
    """Return absolute value"""
    try:
        return abs(float(value))
    except (ValueError, TypeError):
        return 0


@register.filter
def format_metric_name(value):
    """Format metric name by replacing underscores with spaces and title casing"""
    if not value:
        return ""
    return value.replace("_", " ").title()


@register.filter
def format_metric_value(value):
    """Format numeric values with appropriate decimal places"""
    try:
        float_val = float(value)
        # If it's a whole number, display without decimals
        if float_val == int(float_val):
            return floatformat(float_val, 0)
        # Otherwise format with 1 decimal place
        return floatformat(float_val, 1)
    except (ValueError, TypeError):
        return value
