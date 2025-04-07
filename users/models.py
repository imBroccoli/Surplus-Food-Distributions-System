from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    Permission,
    PermissionsMixin,
)
from django.contrib.auth.tokens import default_token_generator
from django.contrib.contenttypes.models import ContentType
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("user_type", "ADMIN")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        user = self.create_user(email, password, **extra_fields)

        # Create admin profile
        from .models import AdminProfile

        AdminProfile.objects.get_or_create(
            user=user, defaults={"department": "GENERAL"}
        )
        return user


class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(_("email address"), unique=True)
    first_name = models.CharField(_("first name"), max_length=30)
    last_name = models.CharField(_("last name"), max_length=30)

    class UserType(models.TextChoices):
        ADMIN = "ADMIN", _("Admin")
        BUSINESS = "BUSINESS", _("Business")
        NONPROFIT = "NONPROFIT", _("Non-Profit")
        CONSUMER = "CONSUMER", _("Consumer")
        VOLUNTEER = "VOLUNTEER", _("Volunteer")

    user_type = models.CharField(
        max_length=10, choices=UserType.choices, default=UserType.CONSUMER
    )
    phone_number = PhoneNumberField(blank=True)
    address = models.TextField(blank=True)
    country = CountryField(blank=True)

    # Business-specific fields
    business_address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)


    # System fields
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def __str__(self):
        return f"{self.email} - {self.get_user_type_display()}"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    def get_short_name(self):
        return self.first_name

    def save(self, *args, **kwargs):
        """Ensure email is normalized to lowercase before saving"""
        self.email = self.email.lower()
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new or self.user_type:
            self.set_permissions()

    def set_permissions(self):
        """Set user permissions based on user type while preserving custom permissions"""
        content_type = ContentType.objects.get_for_model(CustomUser)

        # Store existing custom permissions that aren't related to user types
        existing_permissions = set(self.user_permissions.all())
        role_based_permissions = set()

        # Define permissions for each user type
        if self.user_type == self.UserType.BUSINESS:
            permissions = [
                Permission.objects.get_or_create(
                    codename="can_approve_listings",
                    name="Can approve food listings",
                    content_type=content_type,
                )[0],
            ]
            role_based_permissions.update(permissions)

        elif self.user_type == self.UserType.NONPROFIT:
            permissions = [
                Permission.objects.get_or_create(
                    codename="can_request_food",
                    name="Can request food items",
                    content_type=content_type,
                )[0],
            ]
            role_based_permissions.update(permissions)

        elif self.user_type == self.UserType.VOLUNTEER:
            permissions = [
                Permission.objects.get_or_create(
                    codename="can_deliver_food",
                    name="Can deliver food items",
                    content_type=content_type,
                )[0],
            ]
            role_based_permissions.update(permissions)

        elif self.user_type == self.UserType.ADMIN:
            permissions = [
                Permission.objects.get_or_create(
                    codename="can_manage_users",
                    name="Can manage user accounts",
                    content_type=content_type,
                )[0],
                Permission.objects.get_or_create(
                    codename="can_generate_reports",
                    name="Can generate system reports",
                    content_type=content_type,
                )[0],
            ]
            role_based_permissions.update(permissions)

        # Update user permissions while preserving custom ones
        self.user_permissions.set(
            role_based_permissions
            | {
                perm
                for perm in existing_permissions
                if perm.codename not in [p.codename for p in role_based_permissions]
            }
        )

    def generate_verification_token(self):
        uid = urlsafe_base64_encode(force_bytes(self.pk))
        token = default_token_generator.make_token(self)
        return {"uidb64": uid, "token": token}

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        permissions = [
            ("can_approve_listings", "Can approve food listings"),
            ("can_manage_users", "Can manage user accounts"),
            ("can_generate_reports", "Can generate system reports"),
        ]


class BusinessProfile(models.Model):
    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="businessprofile"
    )
    company_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    push_notifications = models.BooleanField(default=False)
    notification_frequency = models.CharField(
        max_length=10,
        choices=[("immediate", "Immediate"), ("daily", "Daily"), ("weekly", "Weekly")],
        default="immediate",
    )

    def __str__(self):
        return f"{self.company_name} - {self.user.email}"

    def is_complete(self):
        """Check if the business profile is complete with meaningful information"""
        # Get user data for complete check
        user = self.user
        
        return bool(
            # Check company name
            self.company_name and
            self.company_name != "My Business" and  # Not default value
            
            # Check address information
            user.address and
            user.country and
            
            # Check phone number
            user.phone_number
        )

    class Meta:
        verbose_name = _("Business Profile")
        verbose_name_plural = _("Business Profiles")


class NonprofitProfile(models.Model):
    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="nonprofitprofile"
    )
    organization_name = models.CharField(max_length=255)
    registration_number = models.CharField(max_length=50, blank=True, null=True)
    charity_number = models.CharField(max_length=50, blank=True)
    organization_type = models.CharField(
        max_length=50,
        choices=[
            ("CHARITY", "Registered Charity"),
            ("FOUNDATION", "Foundation"),
            ("SOCIAL_ENTERPRISE", "Social Enterprise"),
            ("COMMUNITY_GROUP", "Community Group"),
            ("OTHER", "Other"),
        ],
    )
    focus_area = models.CharField(max_length=100, blank=True, null=True)
    service_area = models.TextField(null=True, blank=True)
    primary_contact = models.CharField(max_length=255)
    verified_nonprofit = models.BooleanField(default=False)
    rejection_reason = models.TextField(blank=True)
    verification_documents = models.FileField(
        upload_to="nonprofit_verification",  # Removed trailing slash for consistency
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "jpg", "jpeg", "png"],
                message="Only PDF and image files (jpg, jpeg, png) are allowed.",
            )
        ],
        help_text="Upload verification documents (PDF or images only).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    push_notifications = models.BooleanField(default=False)
    notification_frequency = models.CharField(
        max_length=10,
        choices=[("immediate", "Immediate"), ("daily", "Daily"), ("weekly", "Weekly")],
        default="immediate",
    )

    def __str__(self):
        return f"{self.organization_name} - {self.user.email}"

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields", [])

        # Handle old file deletion when a new file is uploaded
        if not self._state.adding:
            try:
                old_instance = NonprofitProfile.objects.get(pk=self.pk)
                if (
                    old_instance.verification_documents
                    and self.verification_documents
                    != old_instance.verification_documents
                ):
                    old_instance.verification_documents.delete(save=False)
            except NonprofitProfile.DoesNotExist:
                pass

        # Clear rejection reason when profile is verified
        if not update_fields or "verified_nonprofit" in update_fields:
            if self.verified_nonprofit:
                self.rejection_reason = ""
                if update_fields:
                    if isinstance(update_fields, (list, tuple)):
                        update_fields = list(update_fields)
                        if "rejection_reason" not in update_fields:
                            update_fields.append("rejection_reason")
                            kwargs["update_fields"] = update_fields

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Delete the file when the profile is deleted
        if self.verification_documents:
            self.verification_documents.delete(save=False)
        super().delete(*args, **kwargs)

    def get_verification_status(self):
        """Returns the current verification status of the nonprofit"""
        if self.verified_nonprofit:
            return "VERIFIED"
        elif self.rejection_reason:
            return "REJECTED"
        else:
            return "PENDING"

    def can_access_verified_listings(self):
        """Check if nonprofit can access verified-only listings"""
        # Only verified nonprofits can access verified-only listings
        # Both pending and rejected nonprofits cannot access
        return self.verified_nonprofit

    def is_complete(self):
        """Check if the nonprofit profile is complete with meaningful information"""
        # Get user data for complete check
        user = self.user
        
        return bool(
            # Check organization name
            self.organization_name and
            self.organization_name != "My Organization" and  # Not default value
            
            # Check primary contact name
            self.primary_contact and
            self.primary_contact != user.get_full_name() and  # Not default value
            
            # Check registration info - at least one of registration or charity number
            (self.registration_number or self.charity_number) and
            
            # Check verification documents
            self.verification_documents and
            
            # Check phone number
            user.phone_number
        )

    class Meta:
        verbose_name = _("Nonprofit Profile")
        verbose_name_plural = _("Nonprofit Profiles")


class VolunteerProfile(models.Model):
    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="volunteer_profile"
    )
    availability = models.CharField(
        max_length=20,
        choices=[
            ("WEEKDAYS", "Weekdays"),
            ("WEEKENDS", "Weekends"),
            ("BOTH", "Both Weekdays and Weekends"),
            ("FLEXIBLE", "Flexible"),
        ],
        default="FLEXIBLE",
    )
    transportation_method = models.CharField(
        max_length=20,
        choices=[
            ("CAR", "Personal Car"),
            ("BIKE", "Bicycle"),
            ("PUBLIC", "Public Transport"),
            ("WALK", "Walking"),
            ("OTHER", "Other"),
        ],
    )
    service_area = models.TextField(
        help_text="Areas where you can provide delivery service"
    )
    has_valid_license = models.BooleanField(default=False)
    vehicle_type = models.CharField(max_length=100, blank=True)
    max_delivery_weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum weight (kg) you can deliver",
    )
    completed_deliveries = models.IntegerField(default=0)
    total_impact = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total kg of food delivered",
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    push_notifications = models.BooleanField(default=False)
    notification_frequency = models.CharField(
        max_length=10,
        choices=[("immediate", "Immediate"), ("daily", "Daily"), ("weekly", "Weekly")],
        default="immediate",
    )

    def __str__(self):
        return f"Volunteer Profile - {self.user.get_full_name()}"

    def is_complete(self):
        """Check if the volunteer profile is complete with meaningful information"""
        return bool(
            self.service_area and
            self.service_area != "Local Area" and  # Check if it's not the default value
            self.transportation_method and
            self.transportation_method != "OTHER" and  # Check if user has selected a specific method
            self.max_delivery_weight  # Check if max delivery weight is set
        )

    class Meta:
        verbose_name = _("Volunteer Profile")
        verbose_name_plural = _("Volunteer Profiles")


class AdminProfile(models.Model):
    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="admin_profile"
    )
    department = models.CharField(
        max_length=50,
        choices=[
            ("GENERAL", "General Administration"),
            ("SUPPORT", "User Support"),
            ("COMPLIANCE", "Compliance"),
            ("ANALYTICS", "Analytics"),
        ],
        default="GENERAL",
    )
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=False)
    notification_frequency = models.CharField(
        max_length=10,
        choices=[("immediate", "Immediate"), ("daily", "Daily"), ("weekly", "Weekly")],
        default="immediate",
    )
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    modules_accessed = models.TextField(
        blank=True, help_text="Comma-separated list of accessed admin modules"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Admin Profile - {self.user.get_full_name()}"

    class Meta:
        verbose_name = _("Admin Profile")
        verbose_name_plural = _("Admin Profiles")


class ConsumerProfile(models.Model):
    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="consumer_profile"
    )
    preferred_radius = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Preferred radius for food listings (km)",
    )
    dietary_preferences = models.TextField(
        blank=True, help_text="Any dietary preferences"
    )
    # Notification fields
    push_notifications = models.BooleanField(default=False)
    notification_frequency = models.CharField(
        max_length=10,
        choices=[("immediate", "Immediate"), ("daily", "Daily"), ("weekly", "Weekly")],
        default="immediate",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Consumer Profile - {self.user.get_full_name()}"

    def is_complete(self):
        """Check if the consumer profile has preferences set"""
        return bool(
            self.dietary_preferences or  # Either dietary preferences
            self.preferred_radius  # Or preferred radius should be set
        )

    class Meta:
        verbose_name = _("Consumer Profile")
        verbose_name_plural = _("Consumer Profiles")
