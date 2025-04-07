from crispy_forms.helper import FormHelper
from crispy_forms.layout import Column, Field, Layout, Row, Div
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm

from .models import (
    AdminProfile,
    BusinessProfile,
    ConsumerProfile,
    CustomUser,
    NonprofitProfile,
    VolunteerProfile,
)


class CustomUserCreationForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(
                Column("email", css_class="form-group col-md-6"),
                Column("user_type", css_class="form-group col-md-6"),
                css_class="form-row",
            ),
            Row(
                Column("first_name", css_class="form-group col-md-6"),
                Column("last_name", css_class="form-group col-md-6"),
                css_class="form-row",
            ),
            Row(
                Column("password1", css_class="form-group col-md-6"),
                Column("password2", css_class="form-group col-md-6"),
                css_class="form-row",
            ),
        )
        
        # Exclude ADMIN from user_type choices in registration form
        if 'user_type' in self.fields:
            # Get all choices except ADMIN
            choices = [choice for choice in self.fields['user_type'].choices if choice[0] != 'ADMIN']
            self.fields['user_type'].choices = choices

    class Meta:
        model = CustomUser
        fields = (
            "email",
            "first_name",
            "last_name",
            "user_type",
            "phone_number",
            "address",
            "country",
        )


class UserEditForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(
                Column("first_name", css_class="form-group col-md-6"),
                Column("last_name", css_class="form-group col-md-6"),
                css_class="form-row",
            ),
            Row(
                Column("email", css_class="form-group col-md-6"),
                Column("phone_number", css_class="form-group col-md-6"),
                css_class="form-row",
            ),
            Field("address", wrapper_class="mb-3"),
            Field("country", wrapper_class="mb-3"),
        )

    class Meta:
        model = CustomUser
        fields = (
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "address",
            "country",
        )


class BusinessProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(Field("company_name", wrapper_class="mb-3"))

    class Meta:
        model = BusinessProfile
        fields = ("company_name",)


class NonprofitProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        
        # Mark required fields
        self.fields['organization_name'].required = True
        self.fields['organization_type'].required = True
        self.fields['primary_contact'].required = True
        
        # Add data-required attribute to required fields
        for field_name in ['organization_name', 'organization_type', 'primary_contact']:
            self.fields[field_name].widget.attrs['data-required'] = 'true'
        
        self.helper.layout = Layout(
            Row(
                Column("organization_name", css_class="form-group col-md-6"),
                Column("organization_type", css_class="form-group col-md-6"),
                css_class="form-row",
            ),
            Row(
                Column("registration_number", css_class="form-group col-md-6"),
                Column("charity_number", css_class="form-group col-md-6"),
                css_class="form-row",
            ),
            Row(
                Column("focus_area", css_class="form-group col-md-6"),
                Column("service_area", css_class="form-group col-md-6"),
                css_class="form-row",
            ),
            Field("primary_contact", wrapper_class="mb-3"),
            Field("verification_documents", wrapper_class="mb-3"),
        )

    class Meta:
        model = NonprofitProfile
        fields = (
            "organization_name",
            "organization_type",
            "registration_number",
            "charity_number",
            "focus_area",
            "service_area",
            "primary_contact",
            "verification_documents",
        )


class VolunteerProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(
                Column("availability", css_class="form-group col-md-6"),
                Column("transportation_method", css_class="form-group col-md-6"),
                css_class="form-row",
            ),
            Field("service_area", wrapper_class="mb-3"),
            Row(
                Column(
                    Field("has_valid_license", template="users/custom_checkbox.html"),
                    css_class="form-group col-md-6",
                ),
                Column("vehicle_type", css_class="form-group col-md-6"),
                css_class="form-row",
            ),
            Field("max_delivery_weight", wrapper_class="mb-3"),
        )

        # Add Bootstrap classes to the checkbox
        self.fields["has_valid_license"].widget.attrs.update(
            {
                "class": "form-check-input",
            }
        )

    class Meta:
        model = VolunteerProfile
        fields = (
            "availability",
            "transportation_method",
            "service_area",
            "has_valid_license",
            "vehicle_type",
            "max_delivery_weight",
        )


class AdminProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Field("department", wrapper_class="mb-3"),
            Field("notes", wrapper_class="mb-3"),
        )

    class Meta:
        model = AdminProfile
        fields = ("department", "notes")


class ConsumerProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Field("dietary_preferences", wrapper_class="mb-3", css_class="form-control", rows=3,
                  placeholder="Enter any dietary preferences (optional)"),
            Field("preferred_radius", wrapper_class="mb-3", css_class="form-control",
                  type="number", step="0.1", min="0", placeholder="Enter preferred radius in km (optional)"),
            Div(
                Field("push_notifications", template="users/custom_checkbox.html"),
                css_class="mb-3"
            ),
            Field("notification_frequency", wrapper_class="mb-3", css_class="form-select")
        )
        
        # Add Bootstrap classes and help text
        self.fields["dietary_preferences"].required = False
        self.fields["preferred_radius"].required = False
        
    class Meta:
        model = ConsumerProfile
        fields = (
            "dietary_preferences",
            "preferred_radius",
            "push_notifications",
            "notification_frequency",
        )


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Field("username", wrapper_class="mb-3", css_class="form-control",
                  placeholder="Enter your email address"),
            Field("password", wrapper_class="mb-3", css_class="form-control",
                  placeholder="Enter your password")
        )

        # Update field properties
        self.fields["username"].label = "Email address"
        self.fields["username"].widget.attrs.update({
            "autocomplete": "email",
            "aria-describedby": "emailHelp"
        })
        self.fields["password"].widget.attrs.update({
            "autocomplete": "current-password"
        })
