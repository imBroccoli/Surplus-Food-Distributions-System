import pytest
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from analytics.models import DailyAnalytics, ImpactMetrics, Report, SystemMetrics, UserActivityLog
from analytics.templatetags.analytics_filters import percentage, absolute
from food_listings.models import FoodListing
from transactions.models import FoodRequest, Transaction
from datetime import datetime, timedelta

User = get_user_model()

class TestImpactMetrics(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            user_type='BUSINESS'
        )
        tomorrow = timezone.now() + timedelta(days=1)
        self.listing = FoodListing.objects.create(
            title='Test Listing',
            supplier=self.user,
            quantity=10.0,
            unit="KG",
            listing_type='COMMERCIAL',
            price=Decimal('5.00'),
            expiry_date=tomorrow
        )

    def test_calculate_metrics_for_date(self):
        # Create a completed transaction
        request = FoodRequest.objects.create(
            listing=self.listing,
            quantity_requested=5.0,
            requester=self.user,
            pickup_date=timezone.now() + timedelta(days=1)
        )
        transaction = Transaction.objects.create(
            request=request,
            status='COMPLETED',
            completion_date=timezone.now()
        )

        # Calculate metrics
        metrics = ImpactMetrics.calculate_for_date(timezone.now().date())
        
        # Verify calculations
        self.assertEqual(metrics.food_redistributed_kg, Decimal('5.0'))
        self.assertEqual(metrics.co2_emissions_saved, Decimal('12.5'))  # 5.0 * 2.5
        self.assertEqual(metrics.meals_provided, 10)  # 5.0 * 2
        self.assertTrue(metrics.monetary_value_saved > 0)

class TestDailyAnalytics(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='business@example.com',
            password='testpass123',
            user_type='BUSINESS'
        )
        tomorrow = timezone.now() + timedelta(days=1)
        self.listing = FoodListing.objects.create(
            title='Test Food',
            supplier=self.user,
            quantity=20.0,
            unit="KG",
            listing_type='COMMERCIAL',
            price=Decimal('10.00'),
            expiry_date=tomorrow
        )

    def test_daily_analytics_creation(self):
        analytics = DailyAnalytics.objects.create(
            date=timezone.now().date(),
            user=self.user,
            listing=self.listing,
            requests_received=5,
            requests_fulfilled=3,
            food_saved_kg=Decimal('10.5')
        )
        
        self.assertEqual(analytics.requests_received, 5)
        self.assertEqual(analytics.requests_fulfilled, 3)
        self.assertEqual(analytics.food_saved_kg, Decimal('10.5'))

    def test_unique_constraint(self):
        # Create a unique date for this test run
        test_date = timezone.now().date() - timedelta(days=3)
        
        # Create first analytics entry
        DailyAnalytics.objects.create(
            date=test_date,
            user=self.user,
            listing=self.listing,
            requests_received=1
        )
        
        # Attempt to create duplicate entry for same date/user/listing
        with self.assertRaises(ValidationError):
            try:
                DailyAnalytics.objects.create(
                    date=test_date,
                    user=self.user,
                    listing=self.listing,
                    requests_received=2
                )
            except Exception as e:
                # Convert database IntegrityError to ValidationError for the test
                if 'duplicate key' in str(e) or 'unique constraint' in str(e):
                    raise ValidationError("Duplicate entry")
                raise

class TestUserActivityLog(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )

    def test_activity_log_creation(self):
        log = UserActivityLog.objects.create(
            user=self.user,
            activity_type='VIEW_LISTING',
            details='Viewed food listing #123',
            ip_address='127.0.0.1'
        )
        
        self.assertEqual(log.activity_type, 'VIEW_LISTING')
        self.assertEqual(log.details, 'Viewed food listing #123')
        self.assertEqual(log.ip_address, '127.0.0.1')

class TestReport(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='admin@example.com',
            password='testpass123',
            user_type='ADMIN'
        )

    def test_report_creation(self):
        report = Report.objects.create(
            title='Test Report',
            report_type='IMPACT',
            generated_by=self.user,
            date_range_start=timezone.now().date(),
            date_range_end=timezone.now().date(),
            data={
                'test': 'data',
                'summary': 'Test summary',
                'daily_trends': [{'date': '2025-03-28', 'value': 10}]
            },
            summary='Test summary'
        )
        
        self.assertEqual(report.title, 'Test Report')
        self.assertEqual(report.report_type, 'IMPACT')
        self.assertEqual(report.summary, 'Test summary')

    def test_schedule_report(self):
        report = Report.objects.create(
            title='Scheduled Report',
            report_type='IMPACT',
            generated_by=self.user,
            date_range_start=timezone.now().date(),
            date_range_end=timezone.now().date(),
            data={
                'test': 'data',
                'summary': 'Test summary',
                'daily_trends': [{'date': '2025-03-28', 'value': 10}]
            },
            summary='Test summary'
        )
        
        schedule_time = datetime.now().time()
        result = report.schedule_report('DAILY', schedule_time)
        
        self.assertTrue(result['status'] == 'success')
        self.assertTrue(report.is_scheduled)
        self.assertEqual(report.schedule_frequency, 'DAILY')

    def test_unschedule_report(self):
        schedule_time = timezone.now().time()
        report = Report.objects.create(
            title='Scheduled Report',
            report_type='IMPACT',
            generated_by=self.user,
            date_range_start=timezone.now().date(),
            date_range_end=timezone.now().date(),
            data={
                'test': 'data',
                'summary': 'Test summary',
                'daily_trends': [{'date': '2025-03-28', 'value': 10}]
            },
            summary='Test summary',
            is_scheduled=True,
            schedule_frequency='DAILY',
            schedule_time=schedule_time
        )
        
        result = report.unschedule_report()
        
        self.assertTrue(result['status'] == 'success')
        self.assertFalse(report.is_scheduled)
        self.assertIsNone(report.schedule_frequency)
        self.assertIsNone(report.schedule_time)

class TestAnalyticsFilters(TestCase):
    def test_percentage_filter(self):
        self.assertEqual(percentage(50, 100), '50.0')
        self.assertEqual(percentage(0, 100), '0.0')
        self.assertEqual(percentage(75, 0), 0)  # Division by zero case
        self.assertEqual(percentage(None, 100), 0)  # None value case

    def test_absolute_filter(self):
        self.assertEqual(absolute(-5.5), 5.5)
        self.assertEqual(absolute(10), 10)
        self.assertEqual(absolute(0), 0)
        self.assertEqual(absolute(None), 0)  # None value case

class TestSystemMetrics(TestCase):
    def setUp(self):
        # Use a unique date for each test run
        unique_date = timezone.now().date() - timedelta(days=1)
        self.metrics = SystemMetrics.objects.create(
            date=unique_date,
            active_users=100,
            new_users=10,
            new_listings_count=20,
            request_count=50,
            transaction_completion_rate=75.5
        )

    def test_metrics_creation(self):
        self.assertEqual(self.metrics.active_users, 100)
        self.assertEqual(self.metrics.new_users, 10)
        self.assertEqual(self.metrics.new_listings_count, 20)
        self.assertEqual(self.metrics.request_count, 50)
        self.assertEqual(float(self.metrics.transaction_completion_rate), 75.5)

    def test_unique_date_constraint(self):
        # Use a different date than setUp
        unique_date = timezone.now().date() - timedelta(days=2)
        
        # First creation should work
        metrics1 = SystemMetrics.objects.create(
            date=unique_date,
            active_users=200
        )
        
        # Second creation with same date should fail
        with self.assertRaises(ValidationError):
            try:
                SystemMetrics.objects.create(
                    date=unique_date,
                    active_users=300
                )
            except Exception as e:
                # Convert database IntegrityError to ValidationError for the test
                if 'duplicate key' in str(e) or 'unique constraint' in str(e):
                    raise ValidationError("Duplicate entry")
                raise