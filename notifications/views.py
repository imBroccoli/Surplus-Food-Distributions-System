import logging
import sweetify
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.timesince import timesince
from django.views.decorators.http import require_http_methods
from users.models import ConsumerProfile
from .models import Notification

logger = logging.getLogger(__name__)


@login_required
def notification_list(request):
    notifications = request.user.notifications.all()
    paginator = Paginator(notifications, 20)
    page = request.GET.get("page")
    notifications = paginator.get_page(page)

    return render(
        request,
        "notifications/notification_list.html",
        {"notifications": notifications},
    )


@login_required
def mark_as_read(request, notification_id):
    notification = get_object_or_404(
        Notification, id=notification_id, recipient=request.user
    )
    notification.mark_as_read()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"status": "success"})
    return redirect("notifications:notification_list")


@login_required
@require_http_methods(["POST"])
def mark_all_as_read(request):
    try:
        updated = request.user.notifications.filter(is_read=False).update(
            is_read=True, read_at=timezone.now()
        )

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "status": "success",
                    "message": f"Marked {updated} notifications as read",
                }
            )

        sweetify.success(
            request, f"Marked {updated} notifications as read", 
            timer=3000, 
            toast=True,
            position='top-end'
        )
        return redirect("notifications:notification_list")
    except Exception as e:
        logger.error(f"Error marking notifications as read: {str(e)}")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"status": "error", "message": "Failed to mark notifications as read"},
                status=500,
            )
        sweetify.error(
            request, "Failed to mark notifications as read", 
            timer=3000, 
            toast=True,
            position='top-end'
        )
        return redirect("notifications:notification_list")


@login_required
def get_unread_count(request):
    count = request.user.notifications.filter(is_read=False).count()
    return JsonResponse({"count": count})


@login_required
def get_recent_notifications(request):
    """Get recent notifications for the dropdown"""
    notifications = request.user.notifications.all()[:5]

    html = []
    for notification in notifications:
        priority_class = {
            "HIGH": "border-danger",
            "MEDIUM": "border-warning",
            "LOW": "border-info",
        }.get(notification.priority, "")

        html.append(f"""
            <div class="notification-item p-3 border-start border-4 {priority_class} {"bg-light" if not notification.is_read else ""}">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <h6 class="mb-1">{notification.title}</h6>
                        <p class="mb-1 small">{notification.message}</p>
                        <small class="text-muted">{timesince(notification.created_at)} ago</small>
                    </div>
                    {'<span class="badge bg-primary ms-2">New</span>' if not notification.is_read else ""}
                </div>
                <div class="mt-2">
                    {'<a href="' + notification.link + '" class="btn btn-sm btn-primary">View</a>' if notification.link else ""}
                    {'<button class="btn btn-sm btn-outline-secondary ms-2" onclick="markAsRead(' + str(notification.id) + ')">Mark as read</button>' if not notification.is_read else ""}
                </div>
            </div>
        """)

    if not notifications:
        html.append("""
            <div class="p-3 text-center text-muted">
                <i class="fas fa-bell-slash mb-2"></i>
                <p class="mb-0">No new notifications</p>
            </div>
        """)

    return JsonResponse({"html": "\n".join(html)})


@login_required
def notification_settings(request):
    """View for managing notification settings"""
    try:
        # Get the appropriate profile based on user type
        if request.user.user_type == "BUSINESS":
            user_profile = request.user.businessprofile
        elif request.user.user_type == "NONPROFIT":
            user_profile = request.user.nonprofitprofile
        elif request.user.user_type == "VOLUNTEER":
            user_profile = request.user.volunteer_profile
        elif request.user.user_type == "ADMIN":
            user_profile = request.user.admin_profile
        elif request.user.user_type == "CONSUMER":
            # Try to get existing profile or create a new one
            user_profile, created = ConsumerProfile.objects.get_or_create(
                user=request.user,
                defaults={
                    "notification_frequency": "immediate",
                    "push_notifications": False,
                },
            )
        else:
            user_profile = None

        if request.method == "POST":
            # Update notification preferences
            if user_profile:
                user_profile.push_notifications = (
                    request.POST.get("push_notifications", False) == "on"
                )
                user_profile.notification_frequency = request.POST.get(
                    "notification_frequency", "immediate"
                )
                user_profile.save(
                    update_fields=["push_notifications", "notification_frequency"]
                )
                sweetify.success(
                    request, 
                    "Notification settings updated successfully!", 
                    timer=3000, 
                    toast=True,
                    position='top-end'
                )
            return redirect("notifications:settings")

        return render(
            request, "notifications/settings.html", {"user_profile": user_profile}
        )

    except Exception as e:
        logger.error(
            f"Error in notification_settings for user {request.user.email}: {str(e)}"
        )
        sweetify.error(
            request, 
            "Error loading notification settings. Please try again.", 
            timer=3000, 
            toast=True,
            position='top-end'
        )
        return redirect("users:surplus_landing")


@require_http_methods(["POST"])
@login_required
def clear_messages(request):
    """Clear all messages from the user's session"""
    storage = messages.get_messages(request)
    storage.used = True
    return JsonResponse({"status": "success"})
