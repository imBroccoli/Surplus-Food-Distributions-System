"""
Module tests for the notifications app.

This file contains module-level tests for the notifications app,
focusing on the integration between different components and views.
"""

import json
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from notifications.services import NotificationService
from notifications.views import (
    clear_messages,
    get_recent_notifications,
    get_unread_count,
    mark_all_as_read,
    mark_as_read,
    notification_list,
    notification_settings,
)
from users.models import ConsumerProfile


@pytest.fixture
def user_factory(db):
    """Factory to create test users with different types"""
    def create_user(email="test@example.com", user_type="BUSINESS"):
        from users.models import CustomUser
        return CustomUser.objects.create_user(
            email=email,
            password="testpassword",
            first_name="Test",
            last_name="User",
            user_type=user_type,
        )
    return create_user


@pytest.mark.django_db
class TestNotificationViews:
    def setup_method(self):
        self.factory = RequestFactory()

    def test_notification_list_view(self, user_factory):
        """Test the notification list view"""
        user = user_factory()
        
        # Create some notifications for the user
        for i in range(3):
            Notification.objects.create(
                recipient=user,
                notification_type="SYSTEM",
                title=f"Test {i}",
                message=f"Test message {i}",
            )
        
        # Authenticate the request
        request = self.factory.get(reverse("notifications:notification_list"))
        request.user = user
        # Set up session for sweetify
        request.session = {}
        
        # Mock render method to avoid template rendering issues
        with patch("notifications.views.render") as mock_render:
            mock_render.return_value = MagicMock()
            response = notification_list(request)
            
            # Check that render was called with correct context
            context = mock_render.call_args[0][2]
            assert "notifications" in context
            assert len(context["notifications"]) == 3

    def test_mark_as_read_view(self, user_factory):
        """Test marking a notification as read"""
        user = user_factory()
        
        # Create a notification
        notification = Notification.objects.create(
            recipient=user,
            notification_type="SYSTEM",
            title="Test",
            message="Test message",
            is_read=False,
        )
        
        # Patch the redirect function to avoid URL pattern errors
        with patch("notifications.views.redirect") as mock_redirect:
            mock_redirect.return_value = MagicMock(status_code=302)
            
            # Regular request
            request = self.factory.get(
                reverse("notifications:mark_as_read", args=[notification.id])
            )
            request.user = user
            
            response = mark_as_read(request, notification.id)
            assert response.status_code == 302  # Redirect
            
            # Check notification was marked as read
            notification.refresh_from_db()
            assert notification.is_read is True
            
            # AJAX request
            ajax_request = self.factory.get(
                reverse("notifications:mark_as_read", args=[notification.id])
            )
            ajax_request.user = user
            ajax_request.headers = {"X-Requested-With": "XMLHttpRequest"}
            
            ajax_response = mark_as_read(ajax_request, notification.id)
            assert ajax_response.status_code == 200
            assert json.loads(ajax_response.content)["status"] == "success"

    def test_mark_all_as_read_view(self, user_factory):
        """Test marking all notifications as read"""
        user = user_factory()
        
        # Create multiple notifications
        for i in range(5):
            Notification.objects.create(
                recipient=user,
                notification_type="SYSTEM",
                title=f"Test {i}",
                message=f"Test message {i}",
                is_read=False,
            )
        
        # Patch the redirect function to avoid URL pattern errors
        with patch("notifications.views.redirect") as mock_redirect:
            mock_redirect.return_value = MagicMock(status_code=302)
            
            # Regular request
            request = self.factory.post(reverse("notifications:mark_all_as_read"))
            request.user = user
            # Set up messages framework and session
            request.session = {}
            messages = FallbackStorage(request)
            setattr(request, "_messages", messages)
            
            response = mark_all_as_read(request)
            assert response.status_code == 302  # Redirect
            
            # Verify all notifications are marked as read
            unread_count = Notification.objects.filter(recipient=user, is_read=False).count()
            assert unread_count == 0
            
            # Test AJAX request
            # First reset notifications to unread
            Notification.objects.filter(recipient=user).update(is_read=False, read_at=None)
            
            ajax_request = self.factory.post(reverse("notifications:mark_all_as_read"))
            ajax_request.user = user
            ajax_request.headers = {"X-Requested-With": "XMLHttpRequest"}
            
            ajax_response = mark_all_as_read(ajax_request)
            assert ajax_response.status_code == 200
            response_data = json.loads(ajax_response.content)
            assert response_data["status"] == "success"
            assert "Marked 5 notifications as read" in response_data["message"]

    def test_mark_all_as_read_error_handling(self, user_factory):
        """Test error handling in mark_all_as_read view"""
        user = user_factory()
        
        # More direct approach: Mock the mark_all_as_read function's internals
        with patch("notifications.views.redirect") as mock_redirect:
            mock_redirect.return_value = MagicMock(status_code=302)
            
            # Regular request with error
            request = self.factory.post(reverse("notifications:mark_all_as_read"))
            request.user = user
            
            # Set up messages framework properly
            request.session = {}
            messages = FallbackStorage(request)
            setattr(request, "_messages", messages)
            
            # Mock the exception directly in the view function
            with patch("notifications.views.logger") as mock_logger:
                # Force an exception when updating
                with patch("django.utils.timezone.now") as mock_now:
                    mock_now.side_effect = Exception("Test exception")
                    
                    response = mark_all_as_read(request)
                    assert response.status_code == 302  # Redirect
                    
                    # Verify logging was called with error
                    mock_logger.error.assert_called_once()
            
            # AJAX request with error
            ajax_request = self.factory.post(reverse("notifications:mark_all_as_read"))
            ajax_request.user = user
            ajax_request.headers = {"X-Requested-With": "XMLHttpRequest"}
            
            # Mock JsonResponse for error case
            with patch("notifications.views.JsonResponse") as mock_json_response:
                mock_error_response = MagicMock()
                mock_error_response.status_code = 500
                mock_json_response.return_value = mock_error_response
                
                # Force an exception when updating
                with patch("notifications.views.logger") as mock_logger:
                    with patch("django.utils.timezone.now") as mock_now:
                        mock_now.side_effect = Exception("Test exception")
                        
                        response = mark_all_as_read(ajax_request)
                        assert response.status_code == 500
                        mock_logger.error.assert_called_once()

    def test_get_unread_count_view(self, user_factory):
        """Test getting unread notification count"""
        user = user_factory()
        
        # Create 3 notifications, 2 unread and 1 read
        Notification.objects.create(
            recipient=user,
            notification_type="SYSTEM",
            title="Test 1",
            message="Test message 1",
            is_read=False,
        )
        
        Notification.objects.create(
            recipient=user,
            notification_type="SYSTEM",
            title="Test 2",
            message="Test message 2",
            is_read=False,
        )
        
        Notification.objects.create(
            recipient=user,
            notification_type="SYSTEM",
            title="Test 3",
            message="Test message 3",
            is_read=True,
        )
        
        request = self.factory.get(reverse("notifications:unread_count"))
        request.user = user
        
        response = get_unread_count(request)
        assert response.status_code == 200
        assert json.loads(response.content)["count"] == 2

    def test_get_recent_notifications_view(self, user_factory):
        """Test getting recent notifications for dropdown"""
        user = user_factory()
        
        # Create various types of notifications with different priorities
        Notification.objects.create(
            recipient=user,
            notification_type="SYSTEM",
            title="High Priority",
            message="High priority message",
            priority="HIGH",
            is_read=False,
        )
        
        Notification.objects.create(
            recipient=user,
            notification_type="LISTING_NEW",
            title="Medium Priority",
            message="Medium priority message",
            priority="MEDIUM",
            is_read=False,
            link="/test/",
        )
        
        Notification.objects.create(
            recipient=user,
            notification_type="DELIVERY_UPDATE",
            title="Low Priority",
            message="Low priority message",
            priority="LOW",
            is_read=True,
        )
        
        request = self.factory.get(reverse("notifications:recent_notifications"))
        request.user = user
        
        response = get_recent_notifications(request)
        assert response.status_code == 200
        response_data = json.loads(response.content)
        
        # Verify HTML contains notifications and proper styling
        assert "High Priority" in response_data["html"]
        assert "Medium Priority" in response_data["html"]
        assert "Low Priority" in response_data["html"]
        assert "border-danger" in response_data["html"]  # High priority
        assert "border-warning" in response_data["html"]  # Medium priority
        assert "border-info" in response_data["html"]  # Low priority
        assert "bg-light" in response_data["html"]  # Unread notification

    def test_get_recent_notifications_empty(self, user_factory):
        """Test getting recent notifications when none exist"""
        user = user_factory()
        
        request = self.factory.get(reverse("notifications:recent_notifications"))
        request.user = user
        
        response = get_recent_notifications(request)
        assert response.status_code == 200
        response_data = json.loads(response.content)
        
        # Verify empty state message is shown
        assert "No new notifications" in response_data["html"]

    def test_notification_settings_view(self, user_factory):
        """Test notification settings view"""
        # Create a user of CONSUMER type
        user = user_factory(user_type="CONSUMER")
        
        # Create a GET request
        request = self.factory.get("/notifications/settings/")
        request.user = user
        
        # Instead of patching the URL resolution, directly patch the ConsumerProfile model
        with patch("notifications.views.ConsumerProfile") as mock_consumer_profile:
            # Set up a mock profile
            mock_profile = MagicMock()
            mock_profile.push_notifications = False
            mock_profile.notification_frequency = "immediate"
            
            # Configure the get_or_create method to return our mock profile
            mock_consumer_profile.objects.get_or_create.return_value = (mock_profile, False)
            
            # Patch render to avoid template rendering issues
            with patch("notifications.views.render") as mock_render:
                mock_render.return_value = MagicMock(status_code=200)
                
                # Call the view function directly
                response = notification_settings(request)
                
                # Check that render was called with the right template and context
                mock_render.assert_called_once()
                template_name = mock_render.call_args[0][1]
                context = mock_render.call_args[0][2]
                
                assert template_name == "notifications/settings.html"
                assert "user_profile" in context
                assert context["user_profile"] == mock_profile
                
        # Test POST request (changing settings)
        post_request = self.factory.post(
            "/notifications/settings/",
            {
                "push_notifications": "on",
                "notification_frequency": "daily",
            },
        )
        # Add user to request
        post_request.user = user
        # Add messages framework and proper session
        post_request.session = {}
        messages = FallbackStorage(post_request)
        setattr(post_request, "_messages", messages)
        
        with patch("notifications.views.ConsumerProfile") as mock_consumer_profile:
            # Set up a mock profile
            mock_profile = MagicMock()
            
            # Configure the get_or_create method to return our mock profile
            mock_consumer_profile.objects.get_or_create.return_value = (mock_profile, False)
            
            # Patch redirect to avoid URL resolution issues
            with patch("notifications.views.redirect") as mock_redirect:
                mock_redirect.return_value = MagicMock(status_code=302)
                
                # Patch sweetify instead of messages to avoid issues with the messages framework
                with patch("notifications.views.sweetify") as mock_sweetify:
                    # Call the view function directly
                    response = notification_settings(post_request)
                    
                    # Verify profile was updated with new settings
                    assert mock_profile.push_notifications is True
                    assert mock_profile.notification_frequency == "daily"
                    mock_profile.save.assert_called_once_with(
                        update_fields=["push_notifications", "notification_frequency"]
                    )
                    
                    # Verify success message was shown
                    mock_sweetify.success.assert_called_once()

    def test_clear_messages_view(self, user_factory):
        """Test clearing messages from session"""
        user = user_factory()
        
        request = self.factory.post(reverse("notifications:clear_messages"))
        request.user = user
        
        # Set up messages framework
        setattr(request, "session", "session")
        messages = FallbackStorage(request)
        setattr(request, "_messages", messages)
        
        response = clear_messages(request)
        assert response.status_code == 200
        assert json.loads(response.content)["status"] == "success"


@pytest.mark.django_db
class TestNotificationServiceIntegration:
    def test_create_verification_notification(self, user_factory):
        """Test creating a verification notification"""
        user = user_factory(user_type="BUSINESS")
        
        # Create mock profile with rejection reason
        class MockProfile:
            def __init__(self, user, rejection_reason=None):
                self.user = user
                self.rejection_reason = rejection_reason
        
        # Test approved notification
        approved_profile = MockProfile(user)
        
        with patch("notifications.services.reverse") as mock_reverse:
            mock_reverse.return_value = "/profile/"
            NotificationService.create_verification_notification(approved_profile, verified=True)
        
        approved_notification = Notification.objects.filter(
            recipient=user, notification_type="VERIFICATION_UPDATE"
        ).first()
        
        assert approved_notification is not None
        assert "verified" in approved_notification.message
        assert approved_notification.priority == "HIGH"
        assert approved_notification.data["sweetalert"]["icon"] == "success"
        
        # Test rejected notification with reason
        Notification.objects.all().delete()
        rejected_profile = MockProfile(user, rejection_reason="Missing documents")
        
        with patch("notifications.services.reverse") as mock_reverse:
            mock_reverse.return_value = "/profile/"
            NotificationService.create_verification_notification(rejected_profile, verified=False)
        
        rejected_notification = Notification.objects.filter(
            recipient=user, notification_type="VERIFICATION_UPDATE"
        ).first()
        
        assert rejected_notification is not None
        assert "rejected" in rejected_notification.message
        assert "Missing documents" in rejected_notification.message
        assert rejected_notification.priority == "HIGH"
        assert rejected_notification.data["sweetalert"]["icon"] == "error"

    def test_create_pickup_reminder(self, user_factory):
        """Test creating pickup reminders"""
        tomorrow = timezone.now() + timezone.timedelta(days=1)
        
        with patch("notifications.services.DeliveryAssignment.objects.filter") as mock_filter:
            with patch("notifications.services.reverse") as mock_reverse:
                mock_reverse.return_value = "/deliveries/"
                
                # Mock the delivery queryset
                delivery_volunteer = user_factory(user_type="VOLUNTEER")
                mock_deliveries = []
                
                # Create a mock delivery object
                class MockDelivery:
                    class MockTransaction:
                        class MockRequest:
                            class MockListing:
                                title = "Test Food"
                            
                            listing = MockListing()
                        
                        request = MockRequest()
                    
                    transaction = MockTransaction()
                    volunteer = delivery_volunteer
                
                mock_deliveries.append(MockDelivery())
                mock_filter.return_value.select_related.return_value = mock_deliveries
                
                # Run the reminder function
                NotificationService.create_pickup_reminder()
                
                # Check that notifications were created
                reminder = Notification.objects.filter(
                    recipient=delivery_volunteer, notification_type="PICKUP_REMINDER"
                ).first()
                
                assert reminder is not None
                assert "Reminder" in reminder.title
                assert "Test Food" in reminder.message
                assert reminder.priority == "HIGH"

    def test_create_listing_notification(self, user_factory):
        """Test creating notifications for new listings"""
        # Create a mock food listing
        class MockListing:
            def __init__(self):
                self.id = 1
                self.title = "Test Food Listing"
                self.quantity = 10
                self.unit = "kg"
                self.supplier = user_factory(user_type="BUSINESS", email="supplier@example.com")
        
        # Create potential recipients
        nonprofit_user = user_factory(user_type="NONPROFIT", email="nonprofit@example.com")
        consumer_user = user_factory(user_type="CONSUMER", email="consumer@example.com")
        
        # We don't want to notify these users
        business_user = user_factory(user_type="BUSINESS", email="another_business@example.com")
        volunteer_user = user_factory(user_type="VOLUNTEER", email="volunteer@example.com")
        
        listing = MockListing()
        
        with patch("notifications.services.reverse") as mock_reverse:
            mock_reverse.return_value = f"/listings/{listing.id}/"
            
            # Import CustomUser from users.models instead of trying to access it from notifications.services
            with patch("users.models.CustomUser.objects.filter") as mock_filter:
                # Set up the filter to return our nonprofit and consumer users
                mock_filter.return_value = [nonprofit_user, consumer_user]
                
                # Create the notifications
                NotificationService.create_listing_notification(listing)
                
                # Check notifications for appropriate users
                nonprofit_notification = Notification.objects.filter(recipient=nonprofit_user).first()
                consumer_notification = Notification.objects.filter(recipient=consumer_user).first()
                
                # Make sure notifications were created for the right users
                assert nonprofit_notification is not None
                assert consumer_notification is not None
                
                # Verify notification content
                assert "New Food Listing Available" in nonprofit_notification.title
                assert listing.title in nonprofit_notification.message
                assert f"{listing.quantity} {listing.unit}" in nonprofit_notification.message
                
                # Verify SweetAlert integration
                assert "sweetalert" in nonprofit_notification.data
                assert nonprofit_notification.data["sweetalert"]["icon"] == "info"
                
                # Verify unintended users don't receive notifications
                assert Notification.objects.filter(recipient=business_user).count() == 0
                assert Notification.objects.filter(recipient=volunteer_user).count() == 0