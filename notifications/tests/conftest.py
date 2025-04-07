import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User

@pytest.fixture
def user_factory():
    """Factory to create users with different types for testing."""
    def create_user(email="test@example.com", password="testpassword", user_type="CONSUMER"):
        User = get_user_model()
        user = User.objects.create_user(
            email=email,
            password=password,
            user_type=user_type,
            first_name="Test",
            last_name="User",
            is_active=True,
        )
        return user
    return create_user