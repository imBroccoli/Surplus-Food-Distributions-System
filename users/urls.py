from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    # Main URLs
    path("", views.landing_page, name="landing"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_view, name="register"),
    path("profile/", views.profile_view, name="profile"),
    path("edit-profile/", views.edit_profile, name="edit_profile"),
    path("surplus/", views.surplus_landing, name="surplus_landing"),
    # Admin management URLs
    path("users/", views.admin_users_list, name="admin_users_list"),
    path("users/create/", views.admin_user_create, name="admin_user_create"),
    path("users/<int:user_id>/edit/", views.admin_user_edit, name="admin_user_edit"),
    path(
        "users/<int:user_id>/toggle-status/",
        views.admin_toggle_user_status,
        name="admin_toggle_user_status",
    ),
    # Nonprofit verification URLs - moved under manage/
    path(
        "nonprofits/verification/",
        views.nonprofit_verification_list,
        name="nonprofit_verification_list",
    ),
    path("nonprofits/verify/", views.verify_nonprofit, name="verify_nonprofit"),
    # Password reset URLs
    path(
        "password-reset/",
        views.RateLimitedPasswordResetView.as_view(
            template_name="registration/password_reset_form.html"
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url="/users/reset/done/",  # Explicit success URL
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    # Clear welcome message
    path(
        "clear-welcome-message/",
        views.clear_welcome_message,
        name="clear_welcome_message",
    ),
    path(
        "clear-profile-updated/",
        views.clear_profile_updated,
        name="clear_profile_updated",
    ),
]
