"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic.base import RedirectView

from users.views import logout_view

urlpatterns = [
    # Root URL redirects to landing page
    path("", RedirectView.as_view(url="/users/", permanent=True), name="root"),
    path("admin/logout/", logout_view, name="admin_logout"),  # Add this before admin urls
    path("admin/", admin.site.urls),
    path("users/", include("users.urls")),
    path("listings/", include("food_listings.urls")),
    path("transactions/", include("transactions.urls")),
    path("analytics/", include("analytics.urls")),
    path("notifications/", include("notifications.urls")),
    # Redirect /manage/nonprofits/verification/ to /users/nonprofits/verification/
    path(
        "manage/nonprofits/verification/",
        RedirectView.as_view(url="/users/nonprofits/verification/", permanent=True),
    ),
    # Redirect /surplus/ to /users/surplus/ for backward compatibility
    path("surplus/", RedirectView.as_view(url="/users/surplus/", permanent=True)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
