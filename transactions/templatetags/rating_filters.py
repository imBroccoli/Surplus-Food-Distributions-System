from django import template
from django.db.models import QuerySet

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary by key"""
    return dictionary.get(key, 0)


@register.filter
def multiply(value, arg):
    """Multiply the value by the argument"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def divisibleby(value, arg):
    """Divide value by arg"""
    try:
        if float(arg) == 0:
            return 0
        return float(value) / float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def has_user_rating(transaction, user):
    """Check if a user has rated a transaction"""
    if not transaction or not hasattr(transaction, "ratings"):
        return False
    return transaction.ratings.filter(rater=user).exists()


@register.filter
def get_latest_rating(ratings):
    """Get the latest rating from a queryset of ratings"""
    if not ratings or not isinstance(ratings, QuerySet):
        return None
    return ratings.order_by("-created_at").first()


@register.filter
def get_user_rating(transaction, user):
    """Get the rating given by a specific user for a transaction"""
    if not transaction or not hasattr(transaction, "get_user_rating_for_user"):
        return None
    return transaction.get_user_rating_for_user(user)


@register.filter
def get_user_rating_id(transaction, user):
    """Get the rating ID given by a specific user for a transaction"""
    if not transaction or not hasattr(transaction, "get_user_rating_for_user"):
        return ""
    rating = transaction.get_user_rating_for_user(user)
    return rating.id if rating else ""
