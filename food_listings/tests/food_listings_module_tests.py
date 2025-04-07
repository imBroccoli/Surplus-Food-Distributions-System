import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from food_listings.models import FoodListing, FoodImage, ComplianceCheck
from food_listings.forms import FoodListingForm, FoodImageForm, ComplianceCheckForm
from decimal import Decimal

User = get_user_model()

@pytest.fixture
def business_user():
    return User.objects.create_user(
        email='business@example.com',
        password='testpass123',
        first_name='Business',
        last_name='User',
        user_type='BUSINESS'
    )

@pytest.fixture
def admin_user():
    return User.objects.create_user(
        email='admin@example.com',
        password='testpass123',
        first_name='Admin',
        last_name='User',
        is_staff=True,
        user_type='ADMIN'
    )

@pytest.fixture
def client():
    return Client()

@pytest.mark.django_db
class TestFoodListingViews:
    def test_listing_create_view(self, client, business_user):
        client.force_login(business_user)
        url = reverse('listings:create')
        
        data = {
            'title': 'New Food Listing',
            'description': 'Test Description',
            'quantity': '10.00',
            'unit': 'kg',
            'expiry_date': (timezone.now() + timezone.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M'),
            'listing_type': 'COMMERCIAL',
            'price': '15.00',
        }
        
        response = client.post(url, data)
        assert response.status_code == 302  # Redirect after successful creation
        assert FoodListing.objects.filter(title='New Food Listing').exists()

    def test_listing_list_view(self, client, business_user, food_listing):
        client.force_login(business_user)
        url = reverse('listings:list')
        response = client.get(url)
        
        assert response.status_code == 200
        assert 'page_obj' in response.context

    def test_listing_detail_view(self, client, business_user, food_listing):
        client.force_login(business_user)
        url = reverse('listings:detail', kwargs={'pk': food_listing.pk})
        response = client.get(url)
        
        assert response.status_code == 200
        assert response.context['listing'] == food_listing

@pytest.mark.django_db
class TestFoodListingForms:
    def test_valid_food_listing_form(self):
        form_data = {
            'title': 'Test Food',
            'description': 'Description',
            'quantity': '10.00',
            'unit': 'kg',
            'expiry_date': (timezone.now() + timezone.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M'),
            'listing_type': 'COMMERCIAL',
            'price': '15.00',
        }
        form = FoodListingForm(data=form_data)
        assert form.is_valid()

    def test_invalid_expiry_date(self):
        form_data = {
            'title': 'Test Food',
            'description': 'Description',
            'quantity': '10.00',
            'unit': 'kg',
            'expiry_date': (timezone.now() - timezone.timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'listing_type': 'COMMERCIAL',
            'price': '15.00',
        }
        form = FoodListingForm(data=form_data)
        assert not form.is_valid()
        assert 'expiry_date' in form.errors

    def test_food_image_form(self):
        image_content = b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        image = SimpleUploadedFile(
            "test.gif", 
            image_content, 
            content_type="image/gif"
        )
        
        form = FoodImageForm(files={'image': image}, data={'is_primary': True})
        assert form.is_valid()

@pytest.mark.django_db
class TestComplianceViews:
    def test_compliance_check_view(self, client, admin_user, food_listing):
        client.force_login(admin_user)
        url = reverse('listings:compliance_check', kwargs={'pk': food_listing.pk})
        
        data = {
            'is_compliant': 'True',
            'notes': 'Compliance verified'
        }
        
        response = client.post(url, data)
        assert response.status_code == 302
        
        check = ComplianceCheck.objects.get(listing=food_listing)
        assert check.is_compliant
        assert check.notes == 'Compliance verified'

    def test_compliance_list_view(self, client, admin_user):
        client.force_login(admin_user)
        url = reverse('listings:compliance_list')
        response = client.get(url)
        
        assert response.status_code == 200
        assert 'page_obj' in response.context

@pytest.fixture
def food_listing(business_user):
    return FoodListing.objects.create(
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