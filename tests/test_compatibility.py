"""
Compatibility tests for verifying system functionality across different user types,
operating systems, and authentication methods.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from food_listings.models import FoodListing
from transactions.models import FoodRequest, Transaction
from notifications.models import Notification
import json

User = get_user_model()

@pytest.mark.django_db
class TestDatabaseCompatibility:
    def test_transaction_atomicity(self):
        """Test database transaction atomicity"""
        # Create test user
        business_user = User.objects.create_user(
            email='business@test.com',
            password='testpass123',
            user_type='BUSINESS'
        )
        
        # Create a food listing
        listing = FoodListing.objects.create(
            title='Test Food',
            description='Test Description',
            quantity=Decimal('10.00'),
            unit='kg',
            expiry_date=timezone.now() + timezone.timedelta(days=7),
            listing_type='COMMERCIAL',
            price=Decimal('15.00'),
            supplier=business_user,
            status='ACTIVE'
        )
        
        # Attempt to create a food request with invalid data in a transaction
        with pytest.raises(ValidationError):
            with transaction.atomic():
                # Invalid: quantity requested is greater than available
                food_request = FoodRequest.objects.create(
                    listing=listing,
                    requester=business_user,
                    quantity_requested=Decimal('20.00'),  # More than available
                    pickup_date=timezone.now(),
                    status='PENDING'
                )
                food_request.full_clean()  # Force validation
                
        # Verify no request was created due to transaction rollback
        assert FoodRequest.objects.count() == 0

@pytest.mark.django_db
class TestUserCompatibility:
    def test_user_type_permissions(self, client):
        """Test access control based on user types"""
        # Create users of different types
        business_user = User.objects.create_user(
            email='business@test.com',
            password='testpass123',
            user_type='BUSINESS'
        )
        
        nonprofit_user = User.objects.create_user(
            email='nonprofit@test.com',
            password='testpass123',
            user_type='NONPROFIT'
        )
        
        # Create a food listing
        listing = FoodListing.objects.create(
            title='Test Food',
            description='Test Description',
            quantity=Decimal('10.00'),
            unit='kg',
            expiry_date=timezone.now() + timezone.timedelta(days=7),
            listing_type='COMMERCIAL',
            price=Decimal('15.00'),
            supplier=business_user,
            status='ACTIVE'
        )
        
        # Test business user permissions
        client.login(username=business_user.email, password='testpass123')
        response = client.get(reverse('transactions:make_request', args=[listing.id]))
        assert response.status_code == 302  # Redirect, not allowed to request own listing
        
        # Test nonprofit user permissions
        client.login(username=nonprofit_user.email, password='testpass123')
        response = client.get(reverse('transactions:make_request', args=[listing.id]))
        assert response.status_code == 200  # Allowed to view request form

@pytest.mark.django_db
class TestFileCompatibility:
    def test_file_upload_compatibility(self, client):
        """Test file upload compatibility"""
        # Create a business user
        business_user = User.objects.create_user(
            email='business@test.com',
            password='testpass123',
            user_type='BUSINESS'
        )
        client.login(username=business_user.email, password='testpass123')
        
        # Create test image
        image_content = b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        image = SimpleUploadedFile(
            'test_image.gif',
            image_content,
            content_type='image/gif'
        )
        
        # Test creating a listing with image
        form_data = {
            'title': 'Test Food with Image',
            'description': 'Test Description',
            'quantity': '10.00',
            'unit': 'kg',
            'expiry_date': (timezone.now() + timezone.timedelta(days=7)).strftime('%Y-%m-%d %H:%M'),
            'listing_type': 'COMMERCIAL',
            'price': '15.00',
            'image': image
        }
        
        response = client.post(reverse('listings:create'), form_data)
        assert response.status_code in [200, 302]  # Either success or redirect

@pytest.mark.django_db
class TestNotificationCompatibility:
    def test_notification_delivery(self):
        """Test notification system compatibility"""
        # Create users
        business_user = User.objects.create_user(
            email='business@test.com',
            password='testpass123',
            user_type='BUSINESS'
        )
        
        nonprofit_user = User.objects.create_user(
            email='nonprofit@test.com',
            password='testpass123',
            user_type='NONPROFIT'
        )
        
        # Create a test notification
        notification = Notification.objects.create(
            recipient=nonprofit_user,
            notification_type='SYSTEM',
            title='Test Notification',
            message='This is a test notification',
            data={'test_data': 'value'}
        )
        
        # Test notification formatting
        assert notification.to_sweetalert_config()['toast'] is True
        assert 'timer' in notification.to_sweetalert_config()

@pytest.mark.django_db
class TestApiCompatibility:
    def test_api_response_format(self, client):
        """Test API response format compatibility"""
        # Create a user
        user = User.objects.create_user(
            email='test@test.com',
            password='testpass123',
            user_type='BUSINESS'
        )
        client.login(username=user.email, password='testpass123')
        
        # Test AJAX request
        response = client.get(
            reverse('notifications:unread_count'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        assert response.status_code == 200
        # Verify response is valid JSON
        try:
            data = json.loads(response.content)
            assert 'count' in data
        except json.JSONDecodeError:
            pytest.fail("Response is not valid JSON")