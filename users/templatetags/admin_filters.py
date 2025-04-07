from django import template
from django.template.defaultfilters import length

register = template.Library()

@register.filter(name='length_is')
def length_is(value, arg):
    """
    Replacement for Django's removed length_is filter.
    Returns a boolean if the value's length is the argument.
    """
    try:
        return len(value) == int(arg)
    except (ValueError, TypeError):
        return False