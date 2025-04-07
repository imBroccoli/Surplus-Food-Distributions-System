from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import models
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
import sweetify  # Import sweetify at the top level

from notifications.services import NotificationService
from .forms import ComplianceCheckForm, FoodImageForm, FoodListingForm
from .models import ComplianceCheck, FoodListing


def is_admin_user(user):
    return user.is_authenticated and user.is_staff


@login_required
def listing_list(request):
    # Get sort parameter from query string
    sort_param = request.GET.get("sort", "date_desc")  # Default to newest first

    # Base queryset
    listings = FoodListing.objects.filter(supplier=request.user)

    # Apply sorting
    if sort_param == "date_asc":
        listings = listings.order_by("created_at")
    elif sort_param == "date_desc":
        listings = listings.order_by("-created_at")
    elif sort_param == "expiry_asc":
        listings = listings.order_by("expiry_date")
    elif sort_param == "expiry_desc":
        listings = listings.order_by("-expiry_date")
    elif sort_param == "title_asc":
        listings = listings.order_by("title")
    elif sort_param == "title_desc":
        listings = listings.order_by("-title")

    paginator = Paginator(listings, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "food_listings/listing_list.html",
        {"page_obj": page_obj, "current_sort": sort_param},
    )


@login_required
def listing_create(request):
    if request.user.user_type != "BUSINESS":
        messages.error(request, "Only business users can create listings")
        return redirect("users:surplus_landing")

    if request.method == "POST":
        form = FoodListingForm(request.POST)
        image_form = FoodImageForm(request.POST, request.FILES)

        if form.is_valid() and (not request.FILES or image_form.is_valid()):
            listing = form.save(commit=False)
            listing.supplier = request.user
            listing.status = "DRAFT"  # Start as draft

            # Ensure expiry_date is timezone aware
            if timezone.is_naive(listing.expiry_date):
                listing.expiry_date = timezone.make_aware(listing.expiry_date)

            listing.save()

            if request.FILES and image_form.is_valid():
                image = image_form.save(commit=False)
                image.listing = listing
                image.save()

            # Use sweetify instead of Django messages
            sweetify.success(request, "Food listing created successfully", timer=3000)

            return redirect("listings:detail", pk=listing.pk)
        else:
            if form.errors:
                for field, errors in form.errors.items():
                    messages.error(request, f"{field}: {', '.join(errors)}")
            if image_form.errors and request.FILES:
                for field, errors in image_form.errors.items():
                    messages.error(request, f"{field}: {', '.join(errors)}")
    else:
        form = FoodListingForm()
        image_form = FoodImageForm()

    return render(
        request,
        "food_listings/listing_form.html",
        {"form": form, "image_form": image_form, "title": "Create Food Listing"},
    )


@login_required
def listing_update(request, pk):
    listing = get_object_or_404(FoodListing, pk=pk)

    if listing.supplier != request.user:
        return HttpResponseForbidden("You don't have permission to edit this listing")

    if request.method == "POST":
        form = FoodListingForm(request.POST, instance=listing)
        image_form = FoodImageForm(request.POST, request.FILES)

        if form.is_valid():
            form.save()

            if image_form.is_valid() and image_form.cleaned_data.get("image"):
                image = image_form.save(commit=False)
                image.listing = listing
                image.save()

            # Use sweetify instead of Django messages
            sweetify.success(request, "Food listing updated successfully", timer=3000)

            # Create notification for updated listing
            NotificationService.create_listing_notification(
                listing, notification_type="LISTING_UPDATE"
            )

            return redirect("listings:detail", pk=listing.pk)
    else:
        form = FoodListingForm(instance=listing)
        image_form = FoodImageForm()

    return render(
        request,
        "food_listings/listing_form.html",
        {
            "form": form,
            "image_form": image_form,
            "title": "Update Food Listing",
            "listing": listing,
        },
    )


@login_required
def listing_delete(request, pk):
    listing = get_object_or_404(FoodListing, pk=pk)

    if listing.supplier != request.user:
        return HttpResponseForbidden("You don't have permission to delete this listing")

    if request.method == "POST":
        listing.delete()
        sweetify.success(request, "Food listing deleted successfully", timer=3000)
        return redirect("listings:list")

    return render(
        request, "food_listings/listing_confirm_delete.html", {"listing": listing}
    )


@login_required
def listing_detail(request, pk):
    listing = get_object_or_404(
        FoodListing.objects.select_related(
            "supplier",
            "supplier__businessprofile",
            "compliance_check",
            "compliance_check__checked_by",
        ).prefetch_related("images"),
        pk=pk,
    )

    # Handle status changes
    if request.method == "POST" and listing.supplier == request.user:
        action = request.POST.get("action")
        if action == "activate" and listing.status == "DRAFT":
            listing.status = "ACTIVE"
            listing.save()
            # Add persistent sweetify message to ensure it appears
            sweetify.success(request, "Listing has been activated and is now visible to others", persistent=True)
            NotificationService.create_listing_notification(
                listing, notification_type="LISTING_ACTIVE"
            )
        elif action == "deactivate" and listing.status == "ACTIVE":
            listing.status = "DRAFT"
            listing.save()
            # Add persistent sweetify message to ensure it appears
            sweetify.success(request, "Listing has been deactivated and is now in draft mode", persistent=True)

    return render(request, "food_listings/listing_detail.html", {"listing": listing})


@login_required
def nonprofit_listings(request):
    """View for nonprofit-specific listings and donation listings"""
    if request.user.user_type != "NONPROFIT":
        sweetify.error(request, "Only nonprofit organizations can access this page", timer=3000)
        return redirect("listings:list")

    nonprofitprofile = request.user.nonprofitprofile
    verification_status = nonprofitprofile.get_verification_status()

    listings = (
        FoodListing.objects.filter(status="ACTIVE", expiry_date__gt=timezone.now())
        .filter(
            models.Q(listing_type="NONPROFIT_ONLY") | models.Q(listing_type="DONATION")
        )
        .order_by("expiry_date")
    )

    # Hide verified-only listings for pending/rejected nonprofits
    if not nonprofitprofile.can_access_verified_listings():
        listings = listings.filter(requires_verification=False)

        # Add appropriate status message using sweetify
        if verification_status == "REJECTED":
            sweetify.error(
                request,
                "Your organization's verification has been rejected. Some listings are not visible. "
                "Please update your verification documents and resubmit.",
                persistent=True
            )
        else:  # PENDING
            sweetify.warning(
                request,
                "Your organization's verification is pending. Some listings will not be visible "
                "until verification is complete.",
                persistent=True
            )

    paginator = Paginator(listings, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "food_listings/nonprofit_listings.html",
        {
            "page_obj": page_obj,
            "is_verified": nonprofitprofile.verified_nonprofit,
            "verification_status": verification_status,
        },
    )


@login_required
@user_passes_test(is_admin_user)
def compliance_list(request):
    """View for listing all food listings requiring compliance checks"""
    listings = FoodListing.objects.select_related("compliance_check").all()

    # Filter based on compliance status
    filter_status = request.GET.get("status")
    if filter_status == "unchecked":
        listings = listings.filter(compliance_check__isnull=True)
    elif filter_status == "compliant":
        listings = listings.filter(compliance_check__is_compliant=True)
    elif filter_status == "non_compliant":
        listings = listings.filter(compliance_check__is_compliant=False)

    paginator = Paginator(listings, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "food_listings/compliance/compliance_list.html",
        {"page_obj": page_obj, "filter_status": filter_status or "all"},
    )


@login_required
@user_passes_test(is_admin_user)
def compliance_check(request, pk):
    """View for performing a compliance check on a specific listing"""
    listing = get_object_or_404(FoodListing, pk=pk)
    compliance_check = ComplianceCheck.objects.filter(listing=listing).first()

    if request.method == "POST":
        form = ComplianceCheckForm(request.POST, instance=compliance_check)
        if form.is_valid():
            check = form.save(commit=False)
            check.listing = listing
            check.checked_by = request.user
            check.save()

            # Notify the supplier about the compliance check
            NotificationService.create_compliance_notification(
                listing, check.is_compliant
            )

            # Use sweetify instead of Django messages
            sweetify.success(request, "Compliance check completed successfully", timer=3000)

            return redirect("listings:compliance_list")
    else:
        form = ComplianceCheckForm(instance=compliance_check)

    return render(
        request,
        "food_listings/compliance/compliance_check.html",
        {"form": form, "listing": listing, "compliance_check": compliance_check},
    )


@login_required
@user_passes_test(lambda u: u.user_type == "ADMIN")
def admin_listings_list(request):
    listings = (
        FoodListing.objects.select_related(
            "supplier", "supplier__businessprofile", "compliance_check"
        )
        .prefetch_related("images")
        .all()
    )

    # Filter by listing type if specified
    listing_type = request.GET.get("type")
    if listing_type:
        listings = listings.filter(listing_type=listing_type)

    # Filter by status if specified
    status = request.GET.get("status")
    if status:
        listings = listings.filter(status=status)

    # Filter by compliance if specified
    compliance = request.GET.get("compliance")
    if compliance == "compliant":
        listings = listings.filter(compliance_check__is_compliant=True)
    elif compliance == "non_compliant":
        listings = listings.filter(compliance_check__is_compliant=False)
    elif compliance == "pending":
        listings = listings.filter(compliance_check__isnull=True)

    return render(
        request,
        "food_listings/admin/listings_list.html",
        {
            "listings": listings,
            "current_type": listing_type,
            "current_status": status,
            "current_compliance": compliance,
            "section": "listings",
        },
    )
