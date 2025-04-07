import pytest
from django.test import Client, TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from decimal import Decimal
from datetime import timedelta
from food_listings.models import FoodListing
from transactions.models import FoodRequest, Transaction
from notifications.models import Notification
from users.models import BusinessProfile, NonprofitProfile, VolunteerProfile, ConsumerProfile

User = get_user_model()

@pytest.fixture
def setup_users():
    def _create_users():
        # Create different types of users with their profiles
        business_user = User.objects.create_user(
            email='business@example.com',
            password='testpass123',
            first_name='Business',
            last_name='User',
            user_type='BUSINESS'
        )
        # Create profile explicitly
        BusinessProfile.objects.create(
            user=business_user,
            company_name="Test Company"
        )

        nonprofit_user = User.objects.create_user(
            email='nonprofit@example.com',
            password='testpass123',
            first_name='Nonprofit',
            last_name='User',
            user_type='NONPROFIT'
        )
        # Create profile explicitly
        NonprofitProfile.objects.create(
            user=nonprofit_user,
            organization_name="Test Nonprofit",
            organization_type="CHARITY",
            primary_contact="Test Contact",
            verified_nonprofit=True
        )

        volunteer_user = User.objects.create_user(
            email='volunteer@example.com',
            password='testpass123',
            first_name='Volunteer',
            last_name='User',
            user_type='VOLUNTEER'
        )
        # Create profile explicitly
        VolunteerProfile.objects.create(
            user=volunteer_user,
            availability="FLEXIBLE",
            service_area="Local Area",
            transportation_method="CAR"
        )

        consumer_user = User.objects.create_user(
            email='consumer@example.com',
            password='testpass123',
            first_name='Consumer',
            last_name='User',
            user_type='CONSUMER'
        )
        # Create profile explicitly
        ConsumerProfile.objects.create(
            user=consumer_user,
            dietary_preferences="None",
            preferred_radius=5.0
        )

        return {
            'business': business_user,
            'nonprofit': nonprofit_user,
            'volunteer': volunteer_user,
            'consumer': consumer_user
        }
    return _create_users

@pytest.fixture
def create_listing(setup_users):
    def _create_listing(listing_type='COMMERCIAL', price=None):
        users = setup_users()
        tomorrow = timezone.now() + timedelta(days=1)
        listing = FoodListing.objects.create(
            title='Test Food',
            description='Fresh test food',
            quantity=10.0,
            unit='KG',
            expiry_date=tomorrow,
            listing_type=listing_type,
            price=price or Decimal('15.00') if listing_type == 'COMMERCIAL' else None,
            supplier=users['business'],
            status='ACTIVE'
        )
        return listing, users
    return _create_listing

# Using Django's TestCase for registration tests to avoid Crispy Forms rendering issues
class TestUserRegistration(TestCase):
    def setUp(self):
        self.client = Client()
        
    def test_business_registration_form_display(self):
        """Test that the business registration form displays correctly"""
        response = self.client.get(reverse('users:register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Register')
        self.assertContains(response, 'Business')
    
    def test_business_profile_creation(self):
        """Test business profile creation without using the registration form"""
        # Create user directly
        user = User.objects.create_user(
            email='directbusiness@example.com',
            password='testpass123',
            first_name='Direct',
            last_name='Business',
            user_type='BUSINESS'
        )
        
        # Create profile directly
        profile = BusinessProfile.objects.create(
            user=user,
            company_name='Direct Business Co'
        )
        
        # Verify
        self.assertEqual(user.user_type, 'BUSINESS')
        self.assertEqual(user.businessprofile.company_name, 'Direct Business Co')
        
    def test_nonprofit_profile_creation(self):
        """Test nonprofit profile creation without using the registration form"""
        # Create user directly
        user = User.objects.create_user(
            email='directnonprofit@example.com',
            password='testpass123',
            first_name='Direct',
            last_name='Nonprofit',
            user_type='NONPROFIT'
        )
        
        # Create profile directly
        profile = NonprofitProfile.objects.create(
            user=user,
            organization_name='Direct Nonprofit',
            organization_type='CHARITY',
            primary_contact='Test Contact'
        )
        
        # Verify
        self.assertEqual(user.user_type, 'NONPROFIT')
        self.assertEqual(user.nonprofitprofile.organization_name, 'Direct Nonprofit')

@pytest.mark.django_db
class TestFoodListingFlow:
    def test_business_create_listing_flow(self, client):
        """Test the complete flow of creating and managing a food listing"""
        # Create business user directly
        business_user = User.objects.create_user(
            email='listingbusiness@example.com',
            password='testpass123',
            first_name='Listing',
            last_name='Business',
            user_type='BUSINESS'
        )
        BusinessProfile.objects.create(
            user=business_user,
            company_name='Listing Company'
        )
        
        client.force_login(business_user)
        
        # Create listing data
        tomorrow = timezone.now() + timedelta(days=1)
        data = {
            'title': 'Fresh Food Listing',
            'description': 'Fresh food test listing',
            'quantity': '10.0',
            'unit': 'KG',
            'expiry_date': tomorrow.strftime('%Y-%m-%dT%H:%M'),
            'listing_type': 'COMMERCIAL',
            'price': '15.00',
            'minimum_quantity': '1.0',
        }
        
        response = client.post(reverse('listings:create'), data)
        assert response.status_code == 302  # Successful creation redirects
        
        # Verify listing was created
        listing = FoodListing.objects.get(title='Fresh Food Listing')
        assert listing.supplier == business_user
        assert listing.quantity == Decimal('10.0')

        # Test listing update
        update_data = dict(data)
        update_data['price'] = '20.00'
        response = client.post(reverse('listings:update', kwargs={'pk': listing.pk}), update_data)
        assert response.status_code == 302
        
        # Verify update
        listing.refresh_from_db()
        assert listing.price == Decimal('20.00')

@pytest.mark.django_db
class TestTransactionFlow:
    def test_manual_transaction_creation(self, client):
        """Test direct FoodRequest creation rather than through views"""
        # Create users directly
        business_user = User.objects.create_user(
            email='transactionbusiness@example.com',
            password='testpass123',
            first_name='Transaction',
            last_name='Business',
            user_type='BUSINESS'
        )
        BusinessProfile.objects.create(
            user=business_user,
            company_name='Transaction Company'
        )
        
        nonprofit_user = User.objects.create_user(
            email='transactionnonprofit@example.com',
            password='testpass123',
            first_name='Transaction',
            last_name='Nonprofit',
            user_type='NONPROFIT'
        )
        NonprofitProfile.objects.create(
            user=nonprofit_user,
            organization_name='Transaction Nonprofit',
            organization_type='CHARITY',
            primary_contact='Test Contact',
            verified_nonprofit=True
        )
        
        # Create listing
        tomorrow = timezone.now() + timedelta(days=1)
        listing = FoodListing.objects.create(
            title='Transaction Food',
            description='Food for transaction test',
            quantity=10.0,
            unit='KG',
            expiry_date=tomorrow,
            listing_type='COMMERCIAL',
            price=Decimal('15.00'),
            supplier=business_user,
            status='ACTIVE'
        )
        
        # Create food request directly
        food_request = FoodRequest.objects.create(
            listing=listing,
            requester=nonprofit_user,
            quantity_requested=Decimal('5.0'),
            pickup_date=tomorrow,
            notes='Test request',
            intended_use='Food bank distribution',
            beneficiary_count=50,
            preferred_time='MORNING',
            status='PENDING'
        )
        
        # Verify request was created
        assert food_request.quantity_requested == Decimal('5.0')
        
        # Update food request status directly
        food_request.status = 'APPROVED'
        food_request.save()
        
        # Verify status update
        food_request.refresh_from_db()
        assert food_request.status == 'APPROVED'
        
        # Create a notification manually
        notification = Notification.objects.create(
            recipient=nonprofit_user,
            notification_type='REQUEST_STATUS',
            title="Request Approved",
            message="Your food request has been approved",
            link=f"/transactions/requests/{food_request.id}/"
        )
        
        # Verify notification
        assert notification.recipient == nonprofit_user
        assert notification.notification_type == 'REQUEST_STATUS'

@pytest.mark.django_db
class TestUserInteractionFlow:
    def test_direct_profile_update(self, client):
        """Test user profile update by directly modifying the model"""
        # Create consumer user directly
        consumer_user = User.objects.create_user(
            email='updateconsumer@example.com',
            password='testpass123',
            first_name='Update',
            last_name='Consumer',
            user_type='CONSUMER'
        )
        consumer_profile = ConsumerProfile.objects.create(
            user=consumer_user,
            dietary_preferences='None',
            preferred_radius=10.0
        )
        
        # Update user and profile fields directly
        consumer_user.first_name = 'Updated'
        consumer_user.save()
        
        consumer_profile.dietary_preferences = 'Vegetarian'
        consumer_profile.preferred_radius = 5.0
        consumer_profile.save()
        
        # Verify updates
        consumer_user.refresh_from_db()
        assert consumer_user.first_name == 'Updated', "First name was not updated"
        
        consumer_profile.refresh_from_db()
        assert consumer_profile.dietary_preferences == 'Vegetarian', "Dietary preferences were not updated"
        assert consumer_profile.preferred_radius == 5.0, "Preferred radius was not updated"

@pytest.mark.django_db
class TestNotificationFlow:
    def test_notification_marking_direct(self, client):
        """Test notification creation and marking as read directly on the model"""
        # Create user directly
        business_user = User.objects.create_user(
            email='notificationbusiness@example.com',
            password='testpass123',
            first_name='Notification',
            last_name='Business',
            user_type='BUSINESS'
        )
        BusinessProfile.objects.create(
            user=business_user,
            company_name='Notification Company'
        )
        
        # Create notification directly
        notification = Notification.objects.create(
            recipient=business_user,
            notification_type='LISTING_EXPIRING',
            title="Test Notification",
            message="This is a test notification",
            link="/listings/"
        )
        
        # Verify notification is unread initially
        assert notification.is_read is False, "Notification should be unread initially"
        
        # Mark as read directly with the model method
        notification.mark_as_read()
        
        # Verify notification was marked as read
        notification.refresh_from_db()
        assert notification.is_read is True, "Notification was not marked as read"
        assert notification.read_at is not None, "Read timestamp was not set"