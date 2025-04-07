import os
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from users.forms import (
    BusinessProfileForm,
    ConsumerProfileForm,
    CustomUserCreationForm,
    NonprofitProfileForm,
    VolunteerProfileForm,
)
from users.models import (
    AdminProfile,
    BusinessProfile,
    ConsumerProfile,
    NonprofitProfile,
    VolunteerProfile,
)

User = get_user_model()


# Model Tests
class CustomUserModelTest(TestCase):
    def setUp(self):
        self.user_data = {
            "email": "test@example.com",
            "password": "testpassword123",
            "first_name": "Test",
            "last_name": "User",
        }

    def test_create_user(self):
        """Test creating a regular user"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(user.email, self.user_data["email"])
        self.assertEqual(user.first_name, self.user_data["first_name"])
        self.assertEqual(user.last_name, self.user_data["last_name"])
        self.assertTrue(user.check_password(self.user_data["password"]))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertEqual(user.user_type, "CONSUMER")  # Default type

    def test_create_user_with_type(self):
        """Test creating a user with a specific type"""
        self.user_data["user_type"] = "BUSINESS"
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(user.user_type, "BUSINESS")

    def test_create_superuser(self):
        """Test creating a superuser"""
        user = User.objects.create_superuser(**self.user_data)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertEqual(user.user_type, "ADMIN")

    def test_email_normalization(self):
        """Test that email is normalized when creating a user"""
        mixed_case_email = "TeSt@ExAmPle.cOm"
        self.user_data["email"] = mixed_case_email
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(user.email, mixed_case_email.lower())

    def test_email_required(self):
        """Test that email is required"""
        self.user_data["email"] = ""
        with self.assertRaises(ValueError):
            User.objects.create_user(**self.user_data)

    def test_get_full_name(self):
        """Test the get_full_name method"""
        user = User.objects.create_user(**self.user_data)
        expected_full_name = f"{self.user_data['first_name']} {self.user_data['last_name']}"
        self.assertEqual(user.get_full_name(), expected_full_name)

    def test_get_short_name(self):
        """Test the get_short_name method"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(user.get_short_name(), self.user_data["first_name"])

    def test_permissions_assigned_for_business(self):
        """Test that appropriate permissions are assigned for business users"""
        self.user_data["user_type"] = "BUSINESS"
        user = User.objects.create_user(**self.user_data)
        self.assertTrue(user.has_perm("users.can_approve_listings"))

    def test_permissions_assigned_for_nonprofit(self):
        """Test that appropriate permissions are assigned for nonprofit users"""
        self.user_data["user_type"] = "NONPROFIT"
        user = User.objects.create_user(**self.user_data)
        self.assertTrue(user.has_perm("users.can_request_food"))

    def test_permissions_assigned_for_volunteer(self):
        """Test that appropriate permissions are assigned for volunteer users"""
        self.user_data["user_type"] = "VOLUNTEER"
        user = User.objects.create_user(**self.user_data)
        self.assertTrue(user.has_perm("users.can_deliver_food"))

    def test_permissions_assigned_for_admin(self):
        """Test that appropriate permissions are assigned for admin users"""
        self.user_data["user_type"] = "ADMIN"
        user = User.objects.create_user(**self.user_data)
        self.assertTrue(user.has_perm("users.can_manage_users"))
        self.assertTrue(user.has_perm("users.can_generate_reports"))


class BusinessProfileModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="business@example.com",
            password="testpassword123",
            first_name="Business",
            last_name="User",
            user_type="BUSINESS",
        )

    def test_create_business_profile(self):
        """Test creating a business profile"""
        profile = BusinessProfile.objects.create(
            user=self.user, company_name="Test Company"
        )

        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.company_name, "Test Company")
        self.assertEqual(profile.notification_frequency, "immediate")
        self.assertFalse(profile.push_notifications)

    def test_string_representation(self):
        """Test the string representation of a business profile"""
        profile = BusinessProfile.objects.create(
            user=self.user, company_name="Test Company"
        )
        self.assertEqual(str(profile), "Test Company - business@example.com")


class NonprofitProfileModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="nonprofit@example.com",
            password="testpassword123",
            first_name="Nonprofit",
            last_name="User",
            user_type="NONPROFIT",
        )

    def test_create_nonprofit_profile(self):
        """Test creating a nonprofit profile"""
        profile = NonprofitProfile.objects.create(
            user=self.user,
            organization_name="Test Nonprofit",
            organization_type="CHARITY",
            primary_contact="John Doe",
        )

        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.organization_name, "Test Nonprofit")
        self.assertEqual(profile.organization_type, "CHARITY")
        self.assertEqual(profile.primary_contact, "John Doe")
        self.assertFalse(profile.verified_nonprofit)
        self.assertEqual(profile.rejection_reason, "")

    def test_get_verification_status_pending(self):
        """Test getting verification status when pending"""
        profile = NonprofitProfile.objects.create(
            user=self.user,
            organization_name="Test Nonprofit",
            organization_type="CHARITY",
            primary_contact="John Doe",
        )
        self.assertEqual(profile.get_verification_status(), "PENDING")

    def test_get_verification_status_verified(self):
        """Test getting verification status when verified"""
        profile = NonprofitProfile.objects.create(
            user=self.user,
            organization_name="Test Nonprofit",
            organization_type="CHARITY",
            primary_contact="John Doe",
            verified_nonprofit=True,
        )
        self.assertEqual(profile.get_verification_status(), "VERIFIED")

    def test_get_verification_status_rejected(self):
        """Test getting verification status when rejected"""
        profile = NonprofitProfile.objects.create(
            user=self.user,
            organization_name="Test Nonprofit",
            organization_type="CHARITY",
            primary_contact="John Doe",
            verified_nonprofit=False,
            rejection_reason="Missing documentation",
        )
        self.assertEqual(profile.get_verification_status(), "REJECTED")

    def test_can_access_verified_listings(self):
        """Test can_access_verified_listings method"""
        profile = NonprofitProfile.objects.create(
            user=self.user,
            organization_name="Test Nonprofit",
            organization_type="CHARITY",
            primary_contact="John Doe",
        )
        
        self.assertFalse(profile.can_access_verified_listings())
        
        profile.verified_nonprofit = True
        profile.save()
        self.assertTrue(profile.can_access_verified_listings())

    def test_clear_rejection_reason_when_verified(self):
        """Test that rejection reason is cleared when nonprofit is verified"""
        profile = NonprofitProfile.objects.create(
            user=self.user,
            organization_name="Test Nonprofit",
            organization_type="CHARITY",
            primary_contact="John Doe",
            verified_nonprofit=False,
            rejection_reason="Missing documentation",
        )
        
        self.assertEqual(profile.rejection_reason, "Missing documentation")
        
        profile.verified_nonprofit = True
        profile.save()
        
        self.assertEqual(profile.rejection_reason, "")

    def test_string_representation(self):
        """Test the string representation of a nonprofit profile"""
        profile = NonprofitProfile.objects.create(
            user=self.user,
            organization_name="Test Nonprofit",
            organization_type="CHARITY",
            primary_contact="John Doe",
        )
        self.assertEqual(str(profile), "Test Nonprofit - nonprofit@example.com")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class NonprofitProfileUploadTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="nonprofit@example.com",
            password="testpassword123",
            first_name="Nonprofit",
            last_name="User",
            user_type="NONPROFIT",
        )
        
        # Create a temporary file
        self.document = SimpleUploadedFile(
            "test_doc.pdf", b"file_content", content_type="application/pdf"
        )

    def test_upload_verification_document(self):
        """Test uploading a verification document"""
        profile = NonprofitProfile.objects.create(
            user=self.user,
            organization_name="Test Nonprofit",
            organization_type="CHARITY",
            primary_contact="John Doe",
            verification_documents=self.document,
        )
        
        self.assertTrue(profile.verification_documents)
        self.assertIn("test_doc", profile.verification_documents.name)

    def tearDown(self):
        # Clean up uploaded files
        for profile in NonprofitProfile.objects.all():
            if profile.verification_documents:
                if os.path.isfile(profile.verification_documents.path):
                    os.remove(profile.verification_documents.path)


class VolunteerProfileModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="volunteer@example.com",
            password="testpassword123",
            first_name="Volunteer",
            last_name="User",
            user_type="VOLUNTEER",
        )

    def test_create_volunteer_profile(self):
        """Test creating a volunteer profile"""
        profile = VolunteerProfile.objects.create(
            user=self.user,
            availability="FLEXIBLE",
            transportation_method="CAR",
            service_area="Local Area",
            has_valid_license=True,
            vehicle_type="Sedan",
            max_delivery_weight=Decimal("50.00"),
        )

        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.availability, "FLEXIBLE")
        self.assertEqual(profile.transportation_method, "CAR")
        self.assertEqual(profile.service_area, "Local Area")
        self.assertTrue(profile.has_valid_license)
        self.assertEqual(profile.vehicle_type, "Sedan")
        self.assertEqual(profile.max_delivery_weight, Decimal("50.00"))
        self.assertEqual(profile.completed_deliveries, 0)
        self.assertEqual(profile.total_impact, Decimal("0.00"))
        self.assertTrue(profile.active)

    def test_string_representation(self):
        """Test the string representation of a volunteer profile"""
        profile = VolunteerProfile.objects.create(
            user=self.user,
            availability="FLEXIBLE",
            transportation_method="CAR",
            service_area="Local Area",
        )
        self.assertEqual(str(profile), f"Volunteer Profile - {self.user.get_full_name()}")


class AdminProfileModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            email="admin@example.com",
            password="testpassword123",
            first_name="Admin",
            last_name="User",
        )
        # Get the admin profile that was automatically created
        self.admin_profile = self.user.admin_profile

    def test_admin_profile_created_automatically(self):
        """Test that admin profile is created automatically for superuser"""
        self.assertIsNotNone(self.admin_profile)
        self.assertEqual(self.admin_profile.user, self.user)
        self.assertEqual(self.admin_profile.department, "GENERAL")

    def test_update_admin_profile(self):
        """Test updating an admin profile"""
        self.admin_profile.department = "ANALYTICS"
        self.admin_profile.email_notifications = True
        self.admin_profile.push_notifications = False
        self.admin_profile.notification_frequency = "weekly"
        self.admin_profile.modules_accessed = "users,listings"
        self.admin_profile.notes = "Test admin"
        self.admin_profile.save()

        # Refresh from database
        self.admin_profile.refresh_from_db()
        
        self.assertEqual(self.admin_profile.department, "ANALYTICS")
        self.assertTrue(self.admin_profile.email_notifications)
        self.assertFalse(self.admin_profile.push_notifications)
        self.assertEqual(self.admin_profile.notification_frequency, "weekly")
        self.assertEqual(self.admin_profile.modules_accessed, "users,listings")
        self.assertEqual(self.admin_profile.notes, "Test admin")

    def test_string_representation(self):
        """Test the string representation of an admin profile"""
        self.assertEqual(str(self.admin_profile), f"Admin Profile - {self.user.get_full_name()}")


class ConsumerProfileModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="consumer@example.com",
            password="testpassword123",
            first_name="Consumer",
            last_name="User",
            user_type="CONSUMER",
        )

    def test_create_consumer_profile(self):
        """Test creating a consumer profile"""
        profile = ConsumerProfile.objects.create(
            user=self.user,
            preferred_radius=Decimal("10.00"),
            dietary_preferences="Vegetarian, gluten-free",
            push_notifications=True,
            notification_frequency="daily",
        )

        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.preferred_radius, Decimal("10.00"))
        self.assertEqual(profile.dietary_preferences, "Vegetarian, gluten-free")
        self.assertTrue(profile.push_notifications)
        self.assertEqual(profile.notification_frequency, "daily")

    def test_string_representation(self):
        """Test the string representation of a consumer profile"""
        profile = ConsumerProfile.objects.create(
            user=self.user,
            preferred_radius=Decimal("10.00"),
        )
        self.assertEqual(str(profile), f"Consumer Profile - {self.user.get_full_name()}")


# Form Tests
class CustomUserCreationFormTest(TestCase):
    def test_valid_form(self):
        """Test that a valid form passes validation"""
        form_data = {
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "user_type": "CONSUMER",
            "password1": "securepassword123",
            "password2": "securepassword123",
        }
        form = CustomUserCreationForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_passwords_dont_match(self):
        """Test that form validation fails if passwords don't match"""
        form_data = {
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "user_type": "CONSUMER",
            "password1": "securepassword123",
            "password2": "differentpassword",
        }
        form = CustomUserCreationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_email_already_exists(self):
        """Test that form validation fails if email already exists"""
        User.objects.create_user(
            email="existing@example.com",
            password="testpassword123",
            first_name="Existing",
            last_name="User",
        )
        
        form_data = {
            "email": "existing@example.com",
            "first_name": "Test",
            "last_name": "User",
            "user_type": "CONSUMER",
            "password1": "securepassword123",
            "password2": "securepassword123",
        }
        form = CustomUserCreationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_admin_user_type_excluded(self):
        """Test that ADMIN user type is excluded from the form choices"""
        form = CustomUserCreationForm()
        user_type_choices = [choice[0] for choice in form.fields["user_type"].choices]
        self.assertNotIn("ADMIN", user_type_choices)


class BusinessProfileFormTest(TestCase):
    def test_valid_form(self):
        """Test that a valid form passes validation"""
        form_data = {
            "company_name": "Test Company",
        }
        form = BusinessProfileForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_missing_required_field(self):
        """Test that form validation fails if required field is missing"""
        form_data = {
            "company_name": "",
        }
        form = BusinessProfileForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("company_name", form.errors)


class NonprofitProfileFormTest(TestCase):
    def test_valid_form(self):
        """Test that a valid form passes validation"""
        form_data = {
            "organization_name": "Test Nonprofit",
            "organization_type": "CHARITY",
            "primary_contact": "John Doe",
            "registration_number": "123456789",
            "charity_number": "ABC123",
            "focus_area": "Food Distribution",
            "service_area": "Local Community",
        }
        form = NonprofitProfileForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_missing_required_fields(self):
        """Test that form validation fails if required fields are missing"""
        form_data = {
            "organization_name": "",
            "organization_type": "",
            "primary_contact": "",
            "registration_number": "123456789",
            "charity_number": "ABC123",
        }
        form = NonprofitProfileForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("organization_name", form.errors)
        self.assertIn("organization_type", form.errors)
        self.assertIn("primary_contact", form.errors)


class VolunteerProfileFormTest(TestCase):
    def test_valid_form(self):
        """Test that a valid form passes validation"""
        form_data = {
            "availability": "FLEXIBLE",
            "transportation_method": "CAR",
            "service_area": "Local Area",
            "has_valid_license": True,
            "vehicle_type": "Sedan",
            "max_delivery_weight": "50.00",
        }
        form = VolunteerProfileForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_missing_required_fields(self):
        """Test that form validation fails if required fields are missing"""
        form_data = {
            "availability": "",
            "transportation_method": "",
            "service_area": "",
        }
        form = VolunteerProfileForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("availability", form.errors)
        self.assertIn("transportation_method", form.errors)
        self.assertIn("service_area", form.errors)


class ConsumerProfileFormTest(TestCase):
    def test_valid_form(self):
        """Test that a valid form passes validation"""
        form_data = {
            "dietary_preferences": "Vegetarian, gluten-free",
            "preferred_radius": "10.00",
            "push_notifications": True,
            "notification_frequency": "daily",
        }
        form = ConsumerProfileForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_optional_fields(self):
        """Test that form validation passes with only optional fields"""
        form_data = {
            "dietary_preferences": "",
            "preferred_radius": "",
            "push_notifications": False,
            "notification_frequency": "immediate",
        }
        form = ConsumerProfileForm(data=form_data)
        self.assertTrue(form.is_valid())