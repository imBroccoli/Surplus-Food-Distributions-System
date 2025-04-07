import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models, transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
import sweetify

from food_listings.models import FoodListing
from notifications.services import NotificationService

from .forms import FoodRequestForm
from .models import DeliveryAssignment, FoodRequest, Rating, Transaction

logger = logging.getLogger(__name__)


@login_required
def browse_listings(request):
    # Base queryset for active listings
    listings = (
        FoodListing.objects.filter(status="ACTIVE", expiry_date__gt=timezone.now())
        .select_related("supplier")
        .prefetch_related("images")
    )

    # Filter based on user type
    if request.user.user_type == "NONPROFIT":
        # Nonprofits can see NONPROFIT_ONLY and DONATION listings
        listings = listings.filter(
            models.Q(listing_type="NONPROFIT_ONLY")
            | models.Q(listing_type="DONATION")
            | models.Q(listing_type="COMMERCIAL")
        )

        # Filter out listings requiring verification if nonprofit is not verified
        if not request.user.nonprofitprofile.verified_nonprofit:
            listings = listings.filter(requires_verification=False)
    else:
        # Other users (like consumers) can only see COMMERCIAL and DONATION listings
        listings = listings.filter(
            models.Q(listing_type="COMMERCIAL") | models.Q(listing_type="DONATION")
        )

    listings = listings.order_by("expiry_date")
    paginator = Paginator(listings, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "transactions/browse_listings.html", {"page_obj": page_obj})


@login_required
def make_request(request, listing_id):
    listing = get_object_or_404(FoodListing, pk=listing_id)
    
    if listing.supplier == request.user:
        sweetify.error(request, "You cannot request your own listing", timer=3000)
        return redirect("transactions:browse_listings")
        
    if request.method == "POST":
        form = FoodRequestForm(request.POST, user=request.user, listing=listing)
        if form.is_valid():
            food_request = form.save(commit=False)
            food_request.listing = listing
            food_request.requester = request.user
            food_request.save()
            
            # Send notification to supplier about new request
            try:
                NotificationService.create_notification(
                    recipient=listing.supplier,
                    notification_type="REQUEST_STATUS",
                    title="New Food Request",
                    message=f"New request for {food_request.quantity_requested} {listing.unit} of {listing.title}",
                    data={
                        "request_id": food_request.id,
                        "listing_id": listing.id,
                        "quantity": str(food_request.quantity_requested),
                        "unit": listing.unit,
                    },
                    priority="HIGH",
                    link=reverse("transactions:manage_requests"),
                )
            except Exception as notification_error:
                logger.error(
                    f"Error sending supplier notification: {notification_error}"
                )
                # Don't show error to user since request was still created successfully
                
            sweetify.success(request, "Your request has been submitted successfully", timer=3000)
            return redirect("transactions:requests")
    else:
        form = FoodRequestForm(user=request.user, listing=listing)
        
    return render(
        request, "transactions/request_form.html", {"form": form, "listing": listing}
    )


@login_required
def my_requests(request):
    page_size = 10
    page_number = max(1, int(request.GET.get("page", 1)))
    start = (page_number - 1) * page_size
    end = page_number * page_size

    requests = (
        FoodRequest.objects.filter(requester=request.user)
        .select_related(
            "listing",
            "listing__supplier",
            "listing__supplier__businessprofile",  # Changed from businessprofile to businessprofile
            "transaction",
        )
        .order_by("-created_at")[start:end]
    )

    # Since we're already limiting the query, we can create a simple page object
    class SimplePage:
        def __init__(self, object_list):
            self.object_list = object_list
            self.number = page_number

        def has_next(self):
            return len(self.object_list) == page_size

        def has_previous(self):
            return self.number > 1

        def previous_page_number(self):
            return self.number - 1

        def next_page_number(self):
            return self.number + 1

        def __iter__(self):
            return iter(self.object_list)

    page_obj = SimplePage(list(requests))

    return render(request, "transactions/my_requests.html", {"page_obj": page_obj})


@login_required
def manage_requests(request):
    if request.user.user_type != "BUSINESS":
        return HttpResponseForbidden("Only business users can access this page")

    requests = FoodRequest.objects.filter(listing__supplier=request.user).order_by(
        "-created_at"
    )

    paginator = Paginator(requests, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "transactions/manage_requests.html", {"page_obj": page_obj})


@login_required
@transaction.atomic
def handle_request(request, request_id, action):
    food_request = get_object_or_404(FoodRequest, pk=request_id)
    old_status = food_request.status

    if food_request.listing.supplier != request.user:
        return HttpResponseForbidden("You don't have permission to handle this request")

    if action not in ["approve", "reject"]:
        sweetify.error(request, "Invalid action", timer=3000)
        return redirect("transactions:manage_requests")

    try:
        if action == "approve":
            # Lock the food listing row to prevent race conditions
            listing = FoodListing.objects.select_for_update().get(
                pk=food_request.listing.pk
            )

            # Check if enough quantity is available
            if listing.quantity < food_request.quantity_requested:
                sweetify.error(request, "Not enough quantity available to fulfill this request", timer=3000)
                return redirect("transactions:manage_requests")

            # Create transaction first to maintain atomicity
            transaction_obj = Transaction.objects.create(request=food_request)

            # Update request status and listing quantity
            food_request.status = "APPROVED"
            food_request.save(update_fields=["status"])

            # Update the listing quantity
            if not food_request.update_listing_quantity():
                raise ValidationError("Failed to update listing quantity")

            # Create delivery assignment with proper time windows
            pickup_window_start = food_request.pickup_date
            pickup_window_end = pickup_window_start + timezone.timedelta(
                minutes=30
            )  # 30 min pickup window
            delivery_window_start = pickup_window_end + timezone.timedelta(
                minutes=15
            )  # 15 min buffer
            delivery_window_end = delivery_window_start + timezone.timedelta(
                hours=1
            )  # 1 hour delivery window

            delivery = DeliveryAssignment.objects.create(
                transaction=transaction_obj,
                status="PENDING",
                pickup_window_start=pickup_window_start,
                pickup_window_end=pickup_window_end,
                delivery_window_start=delivery_window_start,
                delivery_window_end=delivery_window_end,
                estimated_weight=food_request.quantity_requested,
                pickup_notes=f"Pickup from {food_request.listing.supplier.get_full_name()} at {food_request.listing.address or 'address not provided'}",
                delivery_notes=f"Deliver to {food_request.requester.get_full_name()} at {getattr(food_request.requester, 'address', 'address not provided')}",
            )

            # Notify volunteers about the new delivery
            try:
                NotificationService.create_available_delivery_notification(delivery)
            except Exception as notification_error:
                logger.error(
                    f"Error sending new delivery notification: {notification_error}"
                )

            try:
                NotificationService.create_request_notification(
                    food_request, old_status
                )
                sweetify.success(request, "Request has been approved successfully", timer=3000)
            except Exception as notification_error:
                logger.error(
                    f"Notification error in handle_request: {notification_error}"
                )
                sweetify.success(request, "Request has been approved successfully, but notification failed", timer=5000)
        else:
            food_request.status = "REJECTED"
            food_request.save(update_fields=["status"])

            try:
                NotificationService.create_request_notification(
                    food_request, old_status
                )
                sweetify.success(request, "Request has been rejected successfully", timer=3000)
            except Exception as notification_error:
                logger.error(
                    f"Notification error in handle_request: {notification_error}"
                )
                sweetify.success(request, "Request has been rejected successfully, but notification failed", timer=5000)

    except ValidationError as e:
        sweetify.error(request, str(e), timer=5000)
        return redirect("transactions:manage_requests")
    except Exception as e:
        sweetify.error(request, f"Error processing request: {str(e)}", timer=5000)
        return redirect("transactions:manage_requests")

    return redirect("transactions:manage_requests")


@login_required
@transaction.atomic
def cancel_request(request, request_id):
    """Cancel a pending food request"""
    food_request = get_object_or_404(FoodRequest, pk=request_id, requester=request.user)

    if food_request.status != "PENDING":
        sweetify.error(request, "Only pending requests can be cancelled", timer=3000)
        return redirect("transactions:requests")

    old_status = food_request.status
    food_request.status = "CANCELLED"
    food_request.save()

    try:
        NotificationService.create_request_notification(food_request, old_status)
        sweetify.success(request, "Request cancelled successfully", timer=3000)
    except Exception as e:
        logger.error(f"Error sending cancellation notification: {e}")
        sweetify.success(request, "Request cancelled successfully, but notification failed", timer=5000)

    return redirect("transactions:requests")


@login_required
def my_transactions(request):
    if request.user.user_type != "BUSINESS":
        return HttpResponseForbidden("Only business users can access this page")

    transactions = Transaction.objects.filter(
        request__listing__supplier=request.user
    ).order_by("-transaction_date")

    paginator = Paginator(transactions, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "transactions/my_transactions.html", {"page_obj": page_obj})


@login_required
def rate_transaction(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id)

    # Check if user is part of the transaction
    if not request.user.is_authenticated or request.user not in [
        transaction.request.requester,
        transaction.request.listing.supplier,
    ]:
        return HttpResponseForbidden("You are not authorized to rate this transaction")

    # Check if user has already rated
    if Rating.objects.filter(transaction=transaction, rater=request.user).exists():
        sweetify.warning(request, "You have already rated this transaction", timer=3000)
        return redirect(
            "transactions:requests"
            if request.user == transaction.request.requester
            else "transactions:my_transactions"
        )

    if request.method == "POST":
        rating_value = request.POST.get("rating")
        comment = request.POST.get("comment", "")

        if not rating_value:
            sweetify.error(request, "This field is required", timer=3000)
            return render(
                request,
                "transactions/rate_transaction.html",
                {"transaction": transaction},
            )

        try:
            rating_value = int(rating_value)
            if 1 <= rating_value <= 5:
                # Determine who is being rated
                if request.user == transaction.request.requester:
                    rated_user = transaction.request.listing.supplier
                else:
                    rated_user = transaction.request.requester

                # Create the rating
                Rating.objects.create(
                    transaction=transaction,
                    rater=request.user,
                    rated_user=rated_user,
                    rating=rating_value,
                    comment=comment,
                )

                # Create notification for new rating
                NotificationService.create_rating_notification(
                    {
                        "rating": rating_value,
                        "transaction_id": transaction.id,
                        "rated_user": rated_user,
                    }
                )

                sweetify.success(request, "Rating submitted successfully", timer=3000)
                return redirect(
                    "transactions:requests"
                    if request.user == transaction.request.requester
                    else "transactions:my_transactions"
                )
            else:
                sweetify.error(request, "Invalid rating value", timer=3000)
        except (ValueError, TypeError):
            sweetify.error(request, "Invalid rating value", timer=3000)

    return render(
        request, "transactions/rate_transaction.html", {"transaction": transaction}
    )


@login_required
def available_deliveries(request):
    if request.user.user_type != "VOLUNTEER":
        return HttpResponseForbidden("Only volunteer users can access this page")

    deliveries = (
        DeliveryAssignment.objects.filter(volunteer=None, status="PENDING")
        .select_related(
            "transaction__request__listing", "transaction__request__requester"
        )
        .order_by("pickup_window_start")
    )

    # Add preferred time display text
    for delivery in deliveries:
        if delivery.transaction.request.preferred_time:
            delivery.preferred_time_display = dict(FoodRequest._meta.get_field('preferred_time').choices)[delivery.transaction.request.preferred_time]

    paginator = Paginator(deliveries, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request, "transactions/available_deliveries.html", {"page_obj": page_obj}
    )


@login_required
def my_deliveries(request):
    if request.user.user_type != "VOLUNTEER":
        return HttpResponseForbidden("Only volunteer users can access this page")

    deliveries = (
        DeliveryAssignment.objects.filter(volunteer=request.user)
        .select_related(
            "transaction__request__listing", "transaction__request__requester"
        )
        .order_by("-created_at")
    )

    paginator = Paginator(deliveries, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "transactions/my_deliveries.html", {"page_obj": page_obj})


@login_required
def accept_delivery(request, delivery_id):
    if request.user.user_type != "VOLUNTEER":
        return HttpResponseForbidden("Only volunteer users can accept deliveries")

    delivery = get_object_or_404(
        DeliveryAssignment, pk=delivery_id, status="PENDING", volunteer=None
    )

    try:
        with transaction.atomic():
            delivery.volunteer = request.user
            delivery.status = "ASSIGNED"
            delivery.assigned_at = timezone.now()
            delivery.save()
            sweetify.success(request, "Delivery assignment accepted successfully", timer=3000)
    except Exception as e:
        sweetify.error(request, f"Error accepting delivery: {str(e)}", timer=5000)

    return redirect("transactions:my_deliveries")


@login_required
def update_delivery_status(request, delivery_id):
    if request.user.user_type != "VOLUNTEER":
        return HttpResponseForbidden("Only volunteer users can update delivery status")
    delivery = get_object_or_404(
        DeliveryAssignment, pk=delivery_id, volunteer=request.user
    )
    old_status = delivery.status
    new_status = request.POST.get("status")
    if new_status not in ["IN_TRANSIT", "DELIVERED", "FAILED"]:
        sweetify.error(request, "Invalid status update", timer=3000)
        return redirect("transactions:my_deliveries")
    try:
        with transaction.atomic():
            delivery.status = new_status
            if new_status == "IN_TRANSIT":
                delivery.picked_up_at = timezone.now()
            elif new_status == "DELIVERED":
                current_time = timezone.now()
                delivery.delivered_at = current_time
                # Update volunteer statistics
                volunteer_profile = request.user.volunteer_profile
                volunteer_profile.completed_deliveries += 1
                volunteer_profile.total_impact += delivery.estimated_weight
                volunteer_profile.save()
                # Update transaction status
                delivery.transaction.status = "COMPLETED"
                delivery.transaction.completion_date = current_time
                delivery.transaction.save()
                # Update food request status
                delivery.transaction.request.status = "COMPLETED"
                delivery.transaction.request.save()
            delivery.save()
            # Create notification for delivery update
            NotificationService.create_delivery_notification(delivery, old_status)
            sweetify.success(request, "Delivery status updated successfully", timer=3000)
    except Exception as e:
        sweetify.error(request, f"Error updating status: {str(e)}", timer=5000)
        
    return redirect("transactions:my_deliveries")


@login_required
def nonprofit_requests(request):
    """View for nonprofits to manage their special food requests"""
    if request.user.user_type != "NONPROFIT":
        return HttpResponseForbidden("Only nonprofit users can access this page")

    requests = (
        FoodRequest.objects.filter(requester=request.user, is_bulk_request=True)
        .select_related("listing", "listing__supplier")
        .order_by("-created_at")
    )

    verified = request.user.nonprofitprofile.verified_nonprofit

    paginator = Paginator(requests, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    metrics = {
        "total_beneficiaries": sum(r.beneficiary_count or 0 for r in requests),
        "total_quantity": sum(r.quantity_requested for r in requests),
        "completed_requests": requests.filter(status="COMPLETED").count(),
        "pending_requests": requests.filter(status="PENDING").count(),
    }

    return render(
        request,
        "transactions/nonprofit_requests.html",
        {"page_obj": page_obj, "metrics": metrics, "is_verified": verified},
    )


@login_required
def transaction_detail(request, transaction_id):
    """
    View function to display the details of a specific transaction.
    Only authenticated users who are part of the transaction can view it.
    """
    transaction = get_object_or_404(Transaction, id=transaction_id)

    # Check if user has permission to view this transaction
    if request.user not in [
        transaction.request.listing.supplier,
        transaction.request.requester,
    ] and (not transaction.delivery or request.user != transaction.delivery.volunteer):
        return HttpResponseForbidden(
            "You don't have permission to view this transaction"
        )

    return render(
        request, "transactions/transaction_detail.html", {"transaction": transaction}
    )


@login_required
def ratings_received(request):
    """View for displaying ratings received by the user"""
    ratings = Rating.objects.filter(rated_user=request.user).order_by("-created_at")

    # Get rating statistics
    from django.db.models import Avg

    rating_stats = {
        "average": ratings.aggregate(avg=Avg("rating"))["avg"] or 0,
        "count": ratings.count(),
        "distribution": {str(i): ratings.filter(rating=i).count() for i in range(1, 6)},
    }

    # Paginate results
    paginator = Paginator(ratings, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "transactions/ratings_received.html",
        {"page_obj": page_obj, "rating_stats": rating_stats},
    )


@login_required
def ratings_given(request):
    """View for displaying ratings given by the user"""
    ratings = Rating.objects.filter(rater=request.user).order_by("-created_at")

    paginator = Paginator(ratings, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "transactions/ratings_given.html", {"page_obj": page_obj})


@login_required
def rating_detail(request, rating_id):
    """View for displaying detailed information about a specific rating"""
    rating = get_object_or_404(Rating, id=rating_id)

    # Check if user has permission to view this rating
    if request.user not in [rating.rater, rating.rated_user]:
        return HttpResponseForbidden("You don't have permission to view this rating")

    return render(request, "transactions/rating_detail.html", {"rating": rating})
