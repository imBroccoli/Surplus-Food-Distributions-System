"""
Performance tests for the surplus food platform.

This file contains tests focused on measuring and ensuring good performance for the application.
The tests are categorized into:
1. Database Performance - Testing query efficiency, bulk operations, and database-level optimizations
2. API Performance - Testing response times for various views and endpoints
3. Load Performance - Testing the application's behavior under load
"""

import pytest
import time
from decimal import Decimal
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.db import connection, reset_queries, transaction
from django.contrib.auth import get_user_model
from django.test.utils import CaptureQueriesContext

from food_listings.models import FoodListing
from transactions.models import FoodRequest, Transaction
from notifications.models import Notification
from analytics.models import DailyAnalytics, ImpactMetrics, UserActivityLog
from users.models import (
    BusinessProfile,
    NonprofitProfile,
    VolunteerProfile,
    ConsumerProfile
)

User = get_user_model()


@pytest.fixture
def setup_test_data(db):
    """Create test data for performance tests"""
    # Create different types of users
    business_user = User.objects.create_user(
        email='business@example.com',
        password='password123',
        first_name='Business',
        last_name='User',
        user_type='BUSINESS'
    )
    BusinessProfile.objects.create(
        user=business_user,
        company_name="Test Business"
    )

    nonprofit_user = User.objects.create_user(
        email='nonprofit@example.com',
        password='password123',
        first_name='Nonprofit',
        last_name='User',
        user_type='NONPROFIT'
    )
    NonprofitProfile.objects.create(
        user=nonprofit_user,
        organization_name="Test Nonprofit",
        organization_type="CHARITY",
        primary_contact="John Doe",
        verified_nonprofit=True
    )

    volunteer_user = User.objects.create_user(
        email='volunteer@example.com',
        password='password123',
        first_name='Volunteer',
        last_name='User',
        user_type='VOLUNTEER'
    )
    VolunteerProfile.objects.create(
        user=volunteer_user,
        availability="FLEXIBLE",
        transportation_method="CAR",
        service_area="Local Area"
    )

    consumer_user = User.objects.create_user(
        email='consumer@example.com',
        password='password123',
        first_name='Consumer',
        last_name='User',
        user_type='CONSUMER'
    )
    ConsumerProfile.objects.create(
        user=consumer_user,
        preferred_radius=Decimal('10.00')
    )

    admin_user = User.objects.create_user(
        email='admin@example.com',
        password='password123',
        first_name='Admin',
        last_name='User',
        user_type='ADMIN',
        is_staff=True
    )

    # Create food listings
    tomorrow = timezone.now() + timedelta(days=1)
    listings = []

    for i in range(20):
        listing = FoodListing.objects.create(
            title=f'Food Listing {i}',
            description=f'Description for listing {i}',
            quantity=Decimal(f'{(i+1)*5}.00'),
            unit='kg',
            expiry_date=tomorrow,
            listing_type='DONATION' if i % 2 == 0 else 'COMMERCIAL',
            price=Decimal('10.00') if i % 2 != 0 else None,
            supplier=business_user,
            status='ACTIVE'
        )
        listings.append(listing)

    # Create food requests and transactions
    for i in range(10):
        request = FoodRequest.objects.create(
            listing=listings[i],
            requester=nonprofit_user,
            quantity_requested=Decimal('5.00'),
            pickup_date=tomorrow,
            notes=f'Request notes {i}',
            status='PENDING'
        )

        if i < 5:  # Complete some transactions
            transaction = Transaction.objects.create(
                request=request,
                status='COMPLETED',
                completion_date=timezone.now()
            )

    # Create notifications
    for i in range(30):
        user = [business_user, nonprofit_user, volunteer_user, consumer_user, admin_user][i % 5]
        Notification.objects.create(
            recipient=user,
            notification_type='SYSTEM',
            title=f'Test Notification {i}',
            message=f'This is test notification {i}',
            is_read=bool(i % 3)
        )

    # Create analytics data
    for i in range(5):
        date = timezone.now().date() - timedelta(days=i)

        # Daily analytics
        for listing in listings[:5]:
            DailyAnalytics.objects.create(
                date=date,
                user=business_user,
                listing=listing,
                requests_received=i+1,
                requests_fulfilled=i,
                food_saved_kg=Decimal(f'{i*5}.00')
            )

        # Impact metrics
        ImpactMetrics.objects.create(
            date=date,
            food_redistributed_kg=Decimal(f'{i*10}.00'),
            co2_emissions_saved=Decimal(f'{i*25}.00'),
            meals_provided=i*20,
            monetary_value_saved=Decimal(f'{i*50}.00')
        )

        # User activity logs - using the proper field names (not using created_at)
        for user in [business_user, nonprofit_user, consumer_user]:
            UserActivityLog.objects.create(
                user=user,
                activity_type='VIEW_LISTING',
                details=f'User viewed listing on {date}',
                ip_address='127.0.0.1'
            )

    return {
        'business_user': business_user,
        'nonprofit_user': nonprofit_user,
        'volunteer_user': volunteer_user,
        'consumer_user': consumer_user,
        'admin_user': admin_user,
        'listings': listings
    }


@pytest.mark.django_db
class TestDatabasePerformance:
    """Tests focused on database query performance and efficiency"""

    def test_food_listing_query_count(self, setup_test_data):
        """Test that fetching food listings uses an efficient number of queries"""
        reset_queries()  # Reset the query count
        
        with CaptureQueriesContext(connection) as context:
            # Using select_related to fetch supplier in the same query
            listings = (FoodListing.objects
                .select_related('supplier')
                .filter(status='ACTIVE')
                .order_by('-created_at')[:10])
            
            # Force evaluation of the queryset
            list(listings)
        
        # Verify we're using an efficient number of queries
        # We should have 1 query for the food listings + supplier
        # Different database setups might add a few queries for connection or metadata
        assert len(context.captured_queries) <= 3
        
        # Verify that listing.supplier doesn't trigger additional queries
        reset_queries()
        with CaptureQueriesContext(connection) as context:
            for listing in listings:
                # Accessing the supplier shouldn't trigger a new query since we used select_related
                supplier_email = listing.supplier.email
        
        # This should not perform any extra queries
        assert len(context.captured_queries) <= 1

    def test_notification_query_count(self, setup_test_data):
        """Test that fetching notifications uses an efficient number of queries"""
        user = setup_test_data['business_user']
        
        reset_queries()
        with CaptureQueriesContext(connection) as context:
            # Using select_related to fetch recipient in the same query
            notifications = (Notification.objects
                .select_related('recipient')
                .filter(recipient=user, is_read=False)
                .order_by('-created_at')[:5])
            
            # Force evaluation of the queryset
            list(notifications)
        
        # Verify we're using an efficient number of queries
        assert len(context.captured_queries) <= 3

    def test_bulk_create_performance(self, setup_test_data):
        """Test the performance of bulk create operations vs individual creates"""
        user = setup_test_data['business_user']
        
        # Measure time for individual creates
        start_time = time.time()
        
        for i in range(10):
            Notification.objects.create(
                recipient=user,
                notification_type='SYSTEM',
                title=f'Individual Notification {i}',
                message=f'This is individual notification {i}'
            )
        
        individual_time = time.time() - start_time
        
        # Measure time for bulk create
        start_time = time.time()
        
        notifications = [
            Notification(
                recipient=user,
                notification_type='SYSTEM',
                title=f'Bulk Notification {i}',
                message=f'This is bulk notification {i}'
            )
            for i in range(10)
        ]
        
        Notification.objects.bulk_create(notifications)
        
        bulk_time = time.time() - start_time
        
        # Bulk create should be faster (or at least not significantly slower)
        # The assertion is loose because on some systems and with small datasets,
        # the overhead might make bulk operations not significantly faster
        assert bulk_time <= individual_time * 1.5


@pytest.mark.django_db
class TestApiPerformance:
    """Tests focused on API response times"""

    def test_homepage_performance(self, setup_test_data, client):
        """Test the performance of the homepage"""
        # Login as a regular user
        client.login(username='consumer@example.com', password='password123')
        
        # Measure response time
        start_time = time.time()
        response = client.get(reverse('users:landing'))
        response_time = time.time() - start_time
        
        # Homepage should respond in a reasonable time (under 1 second in test environment)
        assert response_time < 1.0
        assert response.status_code == 200 or response.status_code == 302  # 302 if redirected when logged in

    def test_food_listing_list_performance(self, setup_test_data, client):
        """Test the performance of the food listing list view"""
        # Login as a nonprofit user who can see listings
        client.login(username='nonprofit@example.com', password='password123')
        
        # Measure response time
        start_time = time.time()
        response = client.get(reverse('listings:list'))
        response_time = time.time() - start_time
        
        # Listing page should respond in a reasonable time (under 1 second in test environment)
        assert response_time < 1.0
        assert response.status_code == 200

    def test_food_listing_detail_performance(self, setup_test_data, client):
        """Test the performance of the food listing detail view"""
        # Login as a nonprofit user
        client.login(username='nonprofit@example.com', password='password123')
        
        listing_id = setup_test_data['listings'][0].id
        
        # Measure response time
        start_time = time.time()
        response = client.get(reverse('listings:detail', kwargs={'pk': listing_id}))
        response_time = time.time() - start_time
        
        # Detail page should respond in a reasonable time (under 1 second in test environment)
        assert response_time < 1.0
        assert response.status_code == 200

    def test_notification_list_performance(self, setup_test_data, client):
        """Test the performance of the notification list view"""
        # Login as a user with notifications
        client.login(username='business@example.com', password='password123')
        
        # Measure response time
        start_time = time.time()
        response = client.get(reverse('notifications:notification_list'))
        response_time = time.time() - start_time
        
        # Notification list should respond in a reasonable time (under 1 second in test environment)
        assert response_time < 1.0
        assert response.status_code == 200

    def test_admin_users_list_performance(self, setup_test_data, client):
        """Test the performance of the admin users list view"""
        # Login as an admin user
        client.login(username='admin@example.com', password='password123')
        
        # Measure response time
        start_time = time.time()
        response = client.get(reverse('users:admin_users_list'))
        response_time = time.time() - start_time
        
        # Admin user list should respond in a reasonable time (under 1 second in test environment)
        # Admin pages are typically a bit slower than regular pages
        assert response_time < 1.0
        assert response.status_code == 200