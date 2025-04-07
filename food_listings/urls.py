from django.urls import path

from . import views

app_name = "listings"

urlpatterns = [
    path("", views.listing_list, name="list"),
    path("create/", views.listing_create, name="create"),
    path("<int:pk>/", views.listing_detail, name="detail"),
    path("<int:pk>/update/", views.listing_update, name="update"),
    path("<int:pk>/delete/", views.listing_delete, name="delete"),
    path("nonprofit/", views.nonprofit_listings, name="nonprofit_listings"),
    path(
        "browse/", views.nonprofit_listings, name="browse"
    ),  # Alias for nonprofit_listings
    path("compliance/", views.compliance_list, name="compliance_list"),
    path("compliance/<int:pk>/", views.compliance_check, name="compliance_check"),
    path("admin/listings/", views.admin_listings_list, name="admin_listings_list"),
]
