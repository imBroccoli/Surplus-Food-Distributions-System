from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.formats import date_format

from .models import ComplianceCheck, FoodImage, FoodListing


class FoodListingForm(forms.ModelForm):
    expiry_date = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={
                "type": "datetime-local",
                "class": "form-control",
                "min": date_format(
                    timezone.now(), r"Y-m-d\TH:i"
                ),  # Added r prefix for raw string
            }
        ),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
    )

    class Meta:
        model = FoodListing
        fields = [
            "title",
            "description",
            "quantity",
            "unit",
            "expiry_date",
            "storage_requirements",
            "handling_instructions",
            "listing_type",
            "price",
            "address",
            "city",
            "postal_code",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "storage_requirements": forms.Textarea(attrs={"rows": 3}),
            "handling_instructions": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "expiry_date": "Expiry Date",
            "listing_type": "Type",
            "unit": "Unit of Measure",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add Bootstrap classes
        for field in self.fields:
            if field != "expiry_date":  # Skip expiry_date as it's already configured
                self.fields[field].widget.attrs.update({"class": "form-control"})

        # Required fields
        self.fields["title"].required = True
        self.fields["description"].required = True
        self.fields["quantity"].required = True
        self.fields["unit"].required = True
        self.fields["expiry_date"].required = True
        self.fields["listing_type"].required = True

        # Optional fields
        self.fields["price"].required = False
        self.fields["storage_requirements"].required = False
        self.fields["handling_instructions"].required = False
        self.fields["address"].required = False
        self.fields["city"].required = False
        self.fields["postal_code"].required = False

    def clean_expiry_date(self):
        expiry_date = self.cleaned_data.get("expiry_date")
        if expiry_date:
            # Ensure the date is timezone aware
            if timezone.is_naive(expiry_date):
                expiry_date = timezone.make_aware(expiry_date)

            # Compare with current time using timezone-aware comparison
            if expiry_date < timezone.now():
                raise ValidationError("Expiry date cannot be in the past")
        return expiry_date

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        if quantity is not None and quantity <= 0:
            raise ValidationError("Quantity must be a positive number.")
        return quantity

    def clean(self):
        cleaned_data = super().clean()
        listing_type = cleaned_data.get("listing_type")
        price = cleaned_data.get("price")

        if listing_type == "COMMERCIAL" and not price:
            raise ValidationError(
                {"price": "Price is required for commercial listings"}
            )
        elif listing_type == "DONATION" and price:
            cleaned_data["price"] = None

        return cleaned_data


class FoodImageForm(forms.ModelForm):
    class Meta:
        model = FoodImage
        fields = ["image", "is_primary"]
        widgets = {
            "image": forms.FileInput(
                attrs={"class": "form-control", "accept": "image/*"}
            )
        }

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image:
            # Check file type
            valid_types = ["image/jpeg", "image/png", "image/gif"]
            if hasattr(image, "content_type") and image.content_type not in valid_types:
                raise ValidationError("Only JPEG, PNG, and GIF images are allowed.")

            # Check file size
            if hasattr(image, "size") and image.size > 5 * 1024 * 1024:  # 5MB limit
                raise ValidationError("Image file size must be under 5MB.")
        return image


class ComplianceCheckForm(forms.ModelForm):
    COMPLIANCE_CHOICES = [
        (True, "Mark as Compliant"),
        (False, "Mark as Non-Compliant"),
    ]

    is_compliant = forms.ChoiceField(
        choices=COMPLIANCE_CHOICES,
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
        required=True,
    )

    class Meta:
        model = ComplianceCheck
        fields = ["is_compliant", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["notes"].required = True

    def clean_is_compliant(self):
        # Convert string 'True'/'False' to boolean
        return self.cleaned_data["is_compliant"] == "True"
