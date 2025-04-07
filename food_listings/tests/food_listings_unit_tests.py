import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from food_listings.models import FoodListing, FoodImage, ComplianceCheck
from django.contrib.auth import get_user_model
from decimal import Decimal

User = get_user_model()

@pytest.fixture
def user():
    return User.objects.create_user(
        email='test@example.com',
        password='testpass123',
        first_name='Test',
        last_name='User',
        user_type='BUSINESS'
    )

@pytest.fixture
def food_listing(user):
    return FoodListing.objects.create(
        title='Test Food',
        description='Test Description',
        quantity=Decimal('10.00'),
        unit='kg',
        expiry_date=timezone.now() + timezone.timedelta(days=7),
        listing_type='COMMERCIAL',
        price=Decimal('15.00'),
        supplier=user,
        status='ACTIVE'
    )

@pytest.mark.django_db
class TestFoodListing:
    def test_create_food_listing(self, food_listing):
        assert food_listing.title == 'Test Food'
        assert food_listing.quantity == Decimal('10.00')
        assert food_listing.status == 'ACTIVE'

    def test_listing_str_representation(self, food_listing):
        expected = f"{food_listing.title} - Active"
        assert str(food_listing) == expected

    def test_remaining_quantity(self, food_listing):
        assert food_listing.remaining_quantity == food_listing.quantity

    def test_invalid_quantity(self, user):
        with pytest.raises(ValidationError):
            listing = FoodListing(
                title='Invalid Food',
                description='Test',
                quantity=Decimal('-1.00'),
                unit='kg',
                expiry_date=timezone.now() + timezone.timedelta(days=7),
                listing_type='COMMERCIAL',
                price=Decimal('15.00'),
                supplier=user
            )
            listing.full_clean()

    def test_commercial_listing_requires_price(self, user):
        with pytest.raises(ValidationError):
            listing = FoodListing(
                title='Commercial Food',
                description='Test',
                quantity=Decimal('10.00'),
                unit='kg',
                expiry_date=timezone.now() + timezone.timedelta(days=7),
                listing_type='COMMERCIAL',
                supplier=user
            )
            listing.full_clean()

    def test_update_status_based_on_quantity(self, food_listing):
        food_listing.quantity = Decimal('0.00')
        food_listing.save()
        food_listing.refresh_from_db()
        assert food_listing.status == 'INACTIVE'

@pytest.mark.django_db
class TestFoodImage:
    def test_create_food_image(self, food_listing):
        image = FoodImage.objects.create(
            listing=food_listing,
            image='test_image.jpg',
            is_primary=True
        )
        assert image.listing == food_listing
        assert image.is_primary is True

    def test_food_image_ordering(self, food_listing):
        FoodImage.objects.create(listing=food_listing, image='secondary.jpg', is_primary=False)
        primary = FoodImage.objects.create(listing=food_listing, image='primary.jpg', is_primary=True)
        
        first_image = FoodImage.objects.filter(listing=food_listing).first()
        assert first_image == primary

@pytest.mark.django_db
class TestComplianceCheck:
    def test_create_compliance_check(self, food_listing, user):
        check = ComplianceCheck.objects.create(
            listing=food_listing,
            checked_by=user,
            is_compliant=True,
            notes='Compliance verified'
        )
        assert check.listing == food_listing
        assert check.is_compliant is True
        assert check.notes == 'Compliance verified'