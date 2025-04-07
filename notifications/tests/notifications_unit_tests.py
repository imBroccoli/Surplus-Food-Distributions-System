"""
Unit tests for the notifications app.

This file contains unit tests for individual components of the notifications app,
focusing on testing each component in isolation.
"""

import pytest
from unittest.mock import patch, MagicMock

from django.utils import timezone

from notifications.models import Notification
from notifications.services import NotificationService


@pytest.mark.django_db
class TestNotificationModel:
    """Tests for the Notification model"""

    def test_str_representation(self, user_factory):
        """Test the string representation of a notification"""
        user = user_factory()
        notification = Notification.objects.create(
            recipient=user,
            notification_type="LISTING_NEW",
            title="Test Notification",
            message="This is a test notification",
        )
        assert str(notification) == f"LISTING_NEW - {user.email}"

    def test_mark_as_read(self, user_factory):
        """Test marking a notification as read"""
        user = user_factory()
        notification = Notification.objects.create(
            recipient=user,
            notification_type="LISTING_NEW",
            title="Test Notification",
            message="This is a test notification",
            is_read=False,
        )

        assert notification.is_read is False
        assert notification.read_at is None

        notification.mark_as_read()
        
        # Refresh from database to verify changes were saved
        notification.refresh_from_db()
        assert notification.is_read is True
        assert notification.read_at is not None

    def test_to_sweetalert_config(self, user_factory):
        """Test converting a notification to SweetAlert2 config"""
        user = user_factory()
        
        # Test notification with custom sweetalert data
        custom_notification = Notification.objects.create(
            recipient=user,
            notification_type="LISTING_NEW",
            title="Test Notification",
            message="This is a test notification",
            data={
                "sweetalert": {
                    "icon": "success",
                    "toast": False,
                    "timer": 5000,
                }
            },
        )
        
        config = custom_notification.to_sweetalert_config()
        assert config["icon"] == "success"
        assert config["toast"] is False
        assert config["timer"] == 5000
        assert "position" in config  # Should have default position
        
        # Test notification without custom sweetalert data
        basic_notification = Notification.objects.create(
            recipient=user,
            notification_type="ERROR",
            title="Error Notification",
            message="This is an error notification",
        )
        
        config = basic_notification.to_sweetalert_config()
        assert config["toast"] is True  # Default value
        assert config["position"] == "top-end"  # Default value
        assert "timer" in config  # Should have default timer
        assert config["icon"] == "error"  # ERROR type maps to error icon


@pytest.mark.django_db
class TestNotificationService:
    """Tests for the NotificationService class"""

    def test_create_notification(self, user_factory):
        """Test creating a notification"""
        user = user_factory()
        
        notification = NotificationService.create_notification(
            recipient=user,
            notification_type="LISTING_NEW",
            title="Test Notification",
            message="This is a test notification",
            priority="HIGH",
            link="/test/",
            data={"test_key": "test_value"},
        )
        
        assert notification is not None
        assert notification.recipient == user
        assert notification.notification_type == "LISTING_NEW"
        assert notification.title == "Test Notification"
        assert notification.message == "This is a test notification"
        assert notification.priority == "HIGH"
        assert notification.link == "/test/"
        assert notification.data["test_key"] == "test_value"
        assert notification.is_read is False

    def test_create_notification_error_handling(self, user_factory):
        """Test error handling in create_notification"""
        user = user_factory()
        
        # Test with invalid notification type
        with patch("notifications.models.Notification.objects.create") as mock_create:
            mock_create.side_effect = Exception("Test exception")
            
            with pytest.raises(Exception) as excinfo:
                NotificationService.create_notification(
                    recipient=user,
                    notification_type="INVALID_TYPE",
                    title="Test Notification",
                    message="This is a test notification",
                )
            
            assert "Test exception" in str(excinfo.value)

    def test_get_unread_count(self, user_factory):
        """Test getting unread notification count"""
        user = user_factory()
        
        # Create 2 unread and 1 read notification
        Notification.objects.create(
            recipient=user,
            notification_type="LISTING_NEW",
            title="Unread 1",
            message="Unread notification 1",
            is_read=False,
        )
        
        Notification.objects.create(
            recipient=user,
            notification_type="LISTING_UPDATE",
            title="Unread 2",
            message="Unread notification 2",
            is_read=False,
        )
        
        Notification.objects.create(
            recipient=user,
            notification_type="DELIVERY_UPDATE",
            title="Read 1",
            message="Read notification 1",
            is_read=True,
        )
        
        # Create notifications for another user (should not be counted)
        other_user = user_factory(email="other@example.com")
        Notification.objects.create(
            recipient=other_user,
            notification_type="LISTING_NEW",
            title="Other User",
            message="Notification for other user",
            is_read=False,
        )
        
        count = NotificationService.get_unread_count(user)
        assert count == 2