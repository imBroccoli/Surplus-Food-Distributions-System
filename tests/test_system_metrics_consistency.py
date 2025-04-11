"""
Test COMP-02 - System Metrics Consistency
This test verifies that system-wide metrics are consistently calculated and stored 
with appropriate unique date constraints across different environments.
"""

import pytest
from django.utils import timezone
from django.db.utils import IntegrityError
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from decimal import Decimal
from django.db import transaction
from datetime import timedelta

from analytics.models import SystemMetrics
from food_listings.models import FoodListing
from transactions.models import FoodRequest, Transaction, DeliveryAssignment
from users.models import BusinessProfile, NonprofitProfile

User = get_user_model()

@pytest.mark.django_db
class TestSystemMetricsConsistency:
    """
    Test case ID: COMP-02 - System Metrics Consistency
    
    This test case verifies that system-wide metrics are consistently calculated and stored
    with appropriate unique date constraints across different environments.
    """
    
    def setup_test_data(self):
        """Setup test data for system metrics calculation"""
        # Create users of different types
        self.business_user = User.objects.create_user(
            email='business@metrics.com',
            password='testpass123',
            user_type='BUSINESS',
            date_joined=timezone.now() - timedelta(days=1)  # Joined yesterday
        )
        BusinessProfile.objects.create(
            user=self.business_user,
            company_name="Test Business"
        )
        
        self.nonprofit_user = User.objects.create_user(
            email='nonprofit@metrics.com',
            password='testpass123',
            user_type='NONPROFIT',
            date_joined=timezone.now()  # Joined today
        )
        NonprofitProfile.objects.create(
            user=self.nonprofit_user,
            organization_name="Test Nonprofit",
            organization_type="CHARITY"
        )
        
        # Create a food listing for today
        self.listing = FoodListing.objects.create(
            title='Metrics Test Food',
            description='For testing system metrics',
            quantity=Decimal('20.00'),
            unit='KG',
            expiry_date=timezone.now() + timezone.timedelta(days=7),
            listing_type='COMMERCIAL',
            price=Decimal('15.00'),
            supplier=self.business_user,
            status='ACTIVE',
            created_at=timezone.now()  # Created today
        )
        
        # Create food request
        self.request = FoodRequest.objects.create(
            listing=self.listing,
            requester=self.nonprofit_user,
            quantity_requested=Decimal('10.00'),
            pickup_date=timezone.now() + timezone.timedelta(days=1),
            preferred_time='MORNING',
            status='APPROVED',
            created_at=timezone.now()  # Created today
        )
        
        # Create completed transaction
        self.transaction = Transaction.objects.create(
            request=self.request,
            status='COMPLETED',
            transaction_date=timezone.now().date(),
            completion_date=timezone.now()
        )
        
        # Return useful data
        return {
            'today': timezone.now().date(),
            'yesterday': timezone.now().date() - timedelta(days=1)
        }
    
    def test_system_metrics_calculation(self):
        """Test that system metrics are calculated consistently"""
        dates = self.setup_test_data()
        today = dates['today']
        
        # Calculate metrics for today
        metrics = SystemMetrics.calculate_for_date(today)
        
        # Verify calculated metrics match expected values based on our test data
        assert metrics.date == today
        assert metrics.active_users > 0, "Should have active users"
        assert metrics.new_users == 1, "Should have 1 new user today"
        assert metrics.business_users_active == 1, "Should have 1 active business user"
        assert metrics.nonprofit_users_active == 1, "Should have 1 active nonprofit user"
        assert metrics.new_listings_count == 1, "Should have 1 new listing"
        assert metrics.request_count == 1, "Should have 1 request"
        assert metrics.transaction_completion_rate > 0, "Should have completed transactions"
        
        # Recalculate metrics to test consistency
        recalculated_metrics = SystemMetrics.calculate_for_date(today)
        
        # Verify metrics are calculated consistently
        assert recalculated_metrics.active_users == metrics.active_users
        assert recalculated_metrics.new_users == metrics.new_users
        assert recalculated_metrics.new_listings_count == metrics.new_listings_count
        assert recalculated_metrics.request_count == metrics.request_count
        assert recalculated_metrics.transaction_completion_rate == metrics.transaction_completion_rate
    
    def test_system_metrics_unique_date_constraint(self):
        """Test that system metrics enforce unique date constraint"""
        dates = self.setup_test_data()
        today = dates['today']
        
        # Calculate metrics for today - this creates a record
        metrics1 = SystemMetrics.calculate_for_date(today)
        
        # Attempt to create a duplicate record for the same date through direct model creation
        # This should raise an IntegrityError
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                SystemMetrics.objects.create(
                    date=today,
                    active_users=150,
                    new_users=25,
                    business_users_active=50,
                    nonprofit_users_active=40,
                    volunteer_users_active=30,
                    consumer_users_active=30,
                    new_listings_count=20,
                    request_count=40,
                    transaction_completion_rate=85.0
                )
        
        # Verify only one record exists for today
        assert SystemMetrics.objects.filter(date=today).count() == 1
        
        # Test that the calculate_for_date method updates existing record instead of creating new one
        updated_metrics = SystemMetrics.calculate_for_date(today)
        
        # Verify still only one record exists
        assert SystemMetrics.objects.filter(date=today).count() == 1
          # Verify the record was updated (get the latest from the database)
        latest_metrics = SystemMetrics.objects.get(date=today)
        assert latest_metrics.id == metrics1.id, "Should update existing record instead of creating new one"
        
    def test_system_metrics_cross_date_consistency(self):
        """Test system metrics consistency across different dates"""
        dates = self.setup_test_data()
        today = dates['today']
        yesterday = dates['yesterday']
        
        # Calculate metrics for today and yesterday
        today_metrics = SystemMetrics.calculate_for_date(today)
        yesterday_metrics = SystemMetrics.calculate_for_date(yesterday)
        
        # Verify metrics for different dates can be different
        # (We're not asserting they must be different, just that the values are independent)
        assert today_metrics.date != yesterday_metrics.date, "Metrics should be for different dates"
        
        # Verify we can have metrics for both dates
        assert SystemMetrics.objects.filter(date=today).exists(), "Today's metrics should exist"
        assert SystemMetrics.objects.filter(date=yesterday).exists(), "Yesterday's metrics should exist"
        
        # Verify total count of metrics is 2 (one for each date)
        assert SystemMetrics.objects.count() == 2, "Should have metrics for two different dates"
    
    def test_system_metrics_validation(self):
        """Test validation of system metrics data"""
        today = timezone.now().date()
        
        # Test validation of percentage fields
        with pytest.raises(ValidationError):
            metrics = SystemMetrics(
                date=today,
                active_users=100,
                new_users=10,
                request_approval_rate=120.0,  # Invalid: over 100%
                transaction_completion_rate=75.0,
                delivery_completion_rate=80.0
            )
            metrics.full_clean()
        
        # Test validation of negative count fields
        with pytest.raises(ValidationError):
            metrics = SystemMetrics(
                date=today,
                active_users=-10,  # Invalid: negative count
                new_users=10
            )
            metrics.full_clean()
            
        # Valid data should pass validation
        valid_metrics = SystemMetrics(
            date=today,
            active_users=100,
            new_users=10,
            request_approval_rate=95.0,
            transaction_completion_rate=75.0,
            delivery_completion_rate=80.0
        )
        valid_metrics.full_clean()  # Should not raise exception
