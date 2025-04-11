"""
Test COMP-01 - Analytics Data Constraints
This test verifies that unique constraints on analytics data models function correctly 
across various database systems to uphold data integrity.
"""

import pytest
from django.utils import timezone
from django.db.utils import IntegrityError
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from decimal import Decimal
from django.db import transaction

from analytics.models import ImpactMetrics, DailyAnalytics, SystemMetrics
from food_listings.models import FoodListing

User = get_user_model()

@pytest.mark.django_db
class TestAnalyticsDataConstraints:
    """
    Test case ID: COMP-01 - Analytics Data Constraints
    
    This test case verifies that unique constraints on analytics data models function correctly
    across various database systems to uphold data integrity.
    """
    
    def test_daily_analytics_unique_constraint(self):
        """Test unique constraint for DailyAnalytics (date, user, listing)"""
        # Create a test user
        user = User.objects.create_user(
            email='test_analytics@example.com',
            password='testpass123',
            user_type='BUSINESS'
        )
        
        # Create a test listing
        listing = FoodListing.objects.create(
            title='Test Listing',
            description='Test Description',
            quantity=Decimal('10.00'),
            unit='KG',
            expiry_date=timezone.now() + timezone.timedelta(days=7),
            listing_type='COMMERCIAL',
            price=Decimal('15.00'),
            supplier=user,
            status='ACTIVE'
        )
        
        # Create first daily analytics entry
        today = timezone.now().date()
        analytics1 = DailyAnalytics.objects.create(
            date=today,
            user=user,
            listing=listing,
            requests_received=5,
            requests_fulfilled=2,
            food_saved_kg=Decimal('8.50')
        )
        
        # Try to create a duplicate entry with the same date, user, and listing
        # This should raise an IntegrityError due to unique constraint violation
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DailyAnalytics.objects.create(
                    date=today,
                    user=user,
                    listing=listing,
                    requests_received=3,
                    requests_fulfilled=1,
                    food_saved_kg=Decimal('5.00')
                )
        
        # Verify only one entry exists
        assert DailyAnalytics.objects.filter(date=today, user=user, listing=listing).count() == 1
        
        # Test that different date allows for new entry
        tomorrow = today + timezone.timedelta(days=1)
        analytics2 = DailyAnalytics.objects.create(
            date=tomorrow,
            user=user,
            listing=listing,
            requests_received=3,
            requests_fulfilled=1,
            food_saved_kg=Decimal('5.00')
        )
        
        # Verify two entries exist now - one for each date
        assert DailyAnalytics.objects.filter(user=user, listing=listing).count() == 2
    
    def test_system_metrics_unique_constraint(self):
        """Test unique constraint for SystemMetrics date field"""
        # Create system metrics for today
        today = timezone.now().date()
        metrics1 = SystemMetrics.objects.create(
            date=today,
            active_users=100,
            new_users=10,
            business_users_active=40,
            nonprofit_users_active=30,
            volunteer_users_active=20,
            consumer_users_active=10,
            new_listings_count=15,
            request_count=25,
            transaction_completion_rate=75.0
        )
        
        # Try to create another SystemMetrics entry for the same date
        # This should raise an IntegrityError due to unique constraint violation
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                SystemMetrics.objects.create(
                    date=today,
                    active_users=120,
                    new_users=15,
                    business_users_active=45,
                    nonprofit_users_active=35,
                    volunteer_users_active=25,
                    consumer_users_active=15,
                    new_listings_count=20,
                    request_count=30,
                    transaction_completion_rate=80.0
                )
        
        # Verify only one entry exists for today
        assert SystemMetrics.objects.filter(date=today).count() == 1
        
        # Test that different date allows for new entry
        tomorrow = today + timezone.timedelta(days=1)
        metrics2 = SystemMetrics.objects.create(
            date=tomorrow,
            active_users=120,
            new_users=15,
            business_users_active=45,
            nonprofit_users_active=35,
            volunteer_users_active=25,
            consumer_users_active=15,
            new_listings_count=20,
            request_count=30,
            transaction_completion_rate=80.0
        )
        
        # Verify two entries exist now - one for each date
        assert SystemMetrics.objects.count() == 2
    
    def test_impact_metrics_update_constraints(self):
        """Test updating impact metrics with constraints"""
        # Create impact metrics for today
        today = timezone.now().date()
        metrics = ImpactMetrics.objects.create(
            date=today,
            food_redistributed_kg=Decimal('100.00'),
            co2_emissions_saved=Decimal('250.00'),
            meals_provided=200,
            monetary_value_saved=Decimal('500.00')
        )
        
        # Update with valid values
        metrics.food_redistributed_kg = Decimal('150.00')
        metrics.co2_emissions_saved = Decimal('375.00')
        metrics.meals_provided = 300
        metrics.monetary_value_saved = Decimal('750.00')
        metrics.save()
        
        # Verify the update was successful
        refreshed_metrics = ImpactMetrics.objects.get(date=today)
        assert refreshed_metrics.food_redistributed_kg == Decimal('150.00')
        assert refreshed_metrics.co2_emissions_saved == Decimal('375.00')
        assert refreshed_metrics.meals_provided == 300
        assert refreshed_metrics.monetary_value_saved == Decimal('750.00')
        
        # Create impact metrics for yesterday and today, then verify we can have metrics for both days
        yesterday = today - timezone.timedelta(days=1)
        yesterday_metrics = ImpactMetrics.objects.create(
            date=yesterday,
            food_redistributed_kg=Decimal('90.00'),
            co2_emissions_saved=Decimal('225.00'),
            meals_provided=180,
            monetary_value_saved=Decimal('450.00')
        )
        
        # Verify both entries exist
        assert ImpactMetrics.objects.count() == 2
        assert ImpactMetrics.objects.filter(date=today).count() == 1
        assert ImpactMetrics.objects.filter(date=yesterday).count() == 1

    def test_model_validation_constraints(self):
        """Test validation constraints on analytics models"""
        today = timezone.now().date()
        
        # Test SystemMetrics validation for percentage fields
        with pytest.raises(ValidationError):
            metrics = SystemMetrics(
                date=today,
                active_users=100,
                new_users=10,
                transaction_completion_rate=120.0  # Invalid: over 100%
            )
            metrics.full_clean()
        
        # Test SystemMetrics validation for negative counts
        with pytest.raises(ValidationError):
            metrics = SystemMetrics(
                date=today,
                active_users=-10,  # Invalid: negative count
                new_users=10
            )
            metrics.full_clean()
        
        # Test DailyAnalytics validation constraints
        test_user = User.objects.create_user(
            email='test_validation@example.com',
            password='testpass123',
            user_type='BUSINESS'
        )
        
        test_listing = FoodListing.objects.create(
            title='Validation Test',
            description='Test Description',
            quantity=Decimal('10.00'),
            unit='KG',
            expiry_date=timezone.now() + timezone.timedelta(days=7),
            listing_type='COMMERCIAL',
            price=Decimal('15.00'),
            supplier=test_user,
            status='ACTIVE'
        )
        
        # Test validation for requests_fulfilled > requests_received
        with pytest.raises(ValidationError):
            analytics = DailyAnalytics(
                date=today,
                user=test_user,
                listing=test_listing,
                requests_received=5,
                requests_fulfilled=10,  # Invalid: more fulfilled than received
                food_saved_kg=Decimal('15.00')
            )
            analytics.full_clean()
