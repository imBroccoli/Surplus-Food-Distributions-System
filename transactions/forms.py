from django import forms
from django.utils import timezone

from .models import FoodRequest


class FoodRequestForm(forms.ModelForm):
    class Meta:
        model = FoodRequest
        fields = [
            "quantity_requested",
            "pickup_date",
            "preferred_time",
            "notes",
            "intended_use",
            "beneficiary_count",
        ]
        widgets = {
            "pickup_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "intended_use": forms.Textarea(attrs={"rows": 3}),
        }
        error_messages = {
            "quantity_requested": {
                "min_value": "Quantity must be greater than 0",
            }
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.listing = kwargs.pop("listing", None)
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({"class": "form-control"})

        # Set required fields based on user type
        if (
            self.user
            and hasattr(self.user, "user_type")
            and self.user.user_type == "NONPROFIT"
        ):
            self.fields["intended_use"].required = True
            self.fields["beneficiary_count"].required = True
        else:
            self.fields["intended_use"].widget = forms.HiddenInput()
            self.fields["beneficiary_count"].widget = forms.HiddenInput()

        # Add help text for minimum quantity and remaining quantity
        if self.listing:
            help_text = []
            if self.listing.minimum_quantity:
                help_text.append(
                    f"Minimum quantity: {self.listing.minimum_quantity} {self.listing.unit}"
                )
            help_text.append(
                f"Available quantity: {self.listing.remaining_quantity} {self.listing.unit}"
            )
            self.fields["quantity_requested"].help_text = " | ".join(help_text)

    def clean_pickup_date(self):
        pickup_date = self.cleaned_data.get("pickup_date")
        if pickup_date and pickup_date < timezone.now():
            raise forms.ValidationError("Pickup date cannot be in the past")
        return pickup_date

    def clean_quantity_requested(self):
        quantity = self.cleaned_data.get("quantity_requested")
        if quantity <= 0:
            raise forms.ValidationError("Quantity must be greater than 0")

        if self.listing:
            remaining = self.listing.remaining_quantity
            if quantity > remaining:
                raise forms.ValidationError(
                    f"Requested quantity exceeds available quantity ({remaining} {self.listing.unit})"
                )
            if (
                self.listing.minimum_quantity
                and quantity < self.listing.minimum_quantity
            ):
                raise forms.ValidationError(
                    f"Minimum quantity for this listing is {self.listing.minimum_quantity} {self.listing.unit}"
                )

        return quantity

    def clean(self):
        cleaned_data = super().clean()
        if not self.user or not self.listing:
            return cleaned_data

        # Check nonprofit-specific validations
        if (
            self.listing.listing_type == "NONPROFIT_ONLY"
            and self.user.user_type != "NONPROFIT"
        ):
            raise forms.ValidationError(
                "This listing is only available to nonprofit organizations"
            )

        if self.user.user_type == "NONPROFIT":
            if (
                self.listing.requires_verification
                and not self.user.nonprofitprofile.verified_nonprofit
            ):
                raise forms.ValidationError(
                    "This listing requires verified nonprofit status"
                )

            if not cleaned_data.get("intended_use"):
                raise forms.ValidationError(
                    "Intended use is required for nonprofit requests"
                )

            if not cleaned_data.get("beneficiary_count"):
                raise forms.ValidationError(
                    "Beneficiary count is required for nonprofit requests"
                )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.requester = self.user
        if self.listing:
            instance.listing = self.listing

        if commit:
            instance.save()
        return instance
