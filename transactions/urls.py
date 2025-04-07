from django.urls import path

from . import views

app_name = "transactions"

urlpatterns = [
    # Main listing URLs
    path("browse/", views.browse_listings, name="browse_listings"),
    path("request/<int:listing_id>/", views.make_request, name="make_request"),
    path("requests/", views.my_requests, name="requests"),
    path(
        "requests/<int:request_id>/cancel/", views.cancel_request, name="cancel_request"
    ),
    path("manage/", views.manage_requests, name="manage_requests"),
    path(
        "handle/<int:request_id>/<str:action>/",
        views.handle_request,
        name="handle_request",
    ),
    path(
        "my/", views.my_transactions, name="my_transactions"
    ),  # Changed from 'transactions/'
    path("<int:transaction_id>/", views.transaction_detail, name="transaction_detail"),
    path("rate/<int:transaction_id>/", views.rate_transaction, name="rate_transaction"),
    # Rating URLs
    path("ratings/received/", views.ratings_received, name="ratings_received"),
    path("ratings/given/", views.ratings_given, name="ratings_given"),
    path("ratings/<int:rating_id>/", views.rating_detail, name="rating_detail"),
    # Volunteer URLs
    path(
        "deliveries/available/", views.available_deliveries, name="available_deliveries"
    ),
    path("deliveries/my/", views.my_deliveries, name="my_deliveries"),
    path(
        "deliveries/accept/<int:delivery_id>/",
        views.accept_delivery,
        name="accept_delivery",
    ),
    path(
        "deliveries/update/<int:delivery_id>/",
        views.update_delivery_status,
        name="update_delivery_status",
    ),
    # Nonprofit URLs
    path("nonprofit/requests/", views.nonprofit_requests, name="nonprofit_requests"),
]
