"""
Unit tests for Pydantic schema validation.
"""

import pytest
from pydantic import ValidationError

from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserUpdate,
    UserAdminUpdate,
    UserResponse,
)
from app.schemas.auth import Token, TokenPayload


class TestUserCreateSchema:
    """Tests for UserCreate schema validation."""

    def test_valid_user_create(self):
        """Valid user data should pass validation."""
        user = UserCreate(
            email="test@example.com",
            username="testuser",
            password="Test@123456",
        )

        assert user.email == "test@example.com"
        assert user.username == "testuser"
        assert user.password == "Test@123456"

    def test_user_create_requires_username(self):
        """
        Username should be required by the schema.
        Note: While the API endpoint might generate it, the schema currently enforces it.
        """
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="test@example.com",
                password="Test@123456",
            )
        assert "username" in str(exc_info.value).lower()

    def test_invalid_email(self):
        """Invalid email should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="not-an-email",
                password="Test@123456",
            )

        assert "email" in str(exc_info.value).lower()

    def test_password_too_short(self):
        """Password less than 8 chars should fail."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="test@example.com",
                password="Test@1",  # Only 6 chars
            )

        assert "password" in str(exc_info.value).lower()

    def test_password_too_long(self):
        """Password more than 64 chars should fail."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="test@example.com",
                password="Test@123" + "x" * 60,  # 68 chars
            )

        assert "password" in str(exc_info.value).lower()

    def test_password_without_digit(self):
        """Password without digit should fail."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="test@example.com",
                password="Test@Password!",  # No digits
            )

        assert "digit" in str(exc_info.value).lower()

    def test_password_without_special_char(self):
        """Password without special character should fail."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="test@example.com",
                password="TestPassword123",  # No special chars
            )

        assert "special" in str(exc_info.value).lower()

    def test_username_too_short(self):
        """Username less than 3 chars should fail."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="test@example.com",
                username="ab",  # Only 2 chars
                password="Test@123456",
            )

        assert "username" in str(exc_info.value).lower()

    def test_username_too_long(self):
        """Username more than 50 chars should fail."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="test@example.com",
                username="a" * 51,  # 51 chars
                password="Test@123456",
            )

        assert "username" in str(exc_info.value).lower()

    def test_extra_fields_forbidden(self):
        """Extra fields should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="test@example.com",
                password="Test@123456",
                extra_field="not allowed",
            )

        assert "extra" in str(exc_info.value).lower()


class TestUserLoginSchema:
    """Tests for UserLogin schema validation."""

    def test_valid_login(self):
        """Valid login data should pass validation."""
        login = UserLogin(
            email="test@example.com",
            password="anypassword",
        )

        assert login.email == "test@example.com"
        assert login.password == "anypassword"

    def test_invalid_email(self):
        """Invalid email should fail validation."""
        with pytest.raises(ValidationError):
            UserLogin(
                email="not-an-email",
                password="anypassword",
            )

    def test_missing_password(self):
        """Missing password should fail validation."""
        with pytest.raises(ValidationError):
            UserLogin(email="test@example.com")


class TestUserUpdateSchema:
    """Tests for UserUpdate schema validation."""

    def test_valid_update_all_fields(self):
        """Valid update with all fields should pass."""
        update = UserUpdate(
            email="new@example.com",
            username="newusername",
            password="New@123456",
        )

        assert update.email == "new@example.com"
        assert update.username == "newusername"
        assert update.password == "New@123456"

    def test_valid_update_partial(self):
        """Partial update should pass."""
        update = UserUpdate(email="new@example.com")

        assert update.email == "new@example.com"
        assert update.username is None
        assert update.password is None

    def test_update_empty(self):
        """Empty update should pass (validation happens in endpoint)."""
        update = UserUpdate()

        assert update.email is None
        assert update.username is None
        assert update.password is None

    def test_update_password_validation(self):
        """Password validation should apply to updates."""
        with pytest.raises(ValidationError) as exc_info:
            UserUpdate(password="weak")  # Too short, no digit, no special

        # Should fail on length first
        assert "password" in str(exc_info.value).lower()


class TestUserAdminUpdateSchema:
    """Tests for UserAdminUpdate schema validation."""

    def test_valid_admin_update_with_role(self):
        """Admin can update role_id."""
        update = UserAdminUpdate(
            role_id=2,
        )

        assert update.role_id == 2

    def test_valid_admin_update_all_fields(self):
        """Admin can update all fields including role."""
        update = UserAdminUpdate(
            email="new@example.com",
            username="newusername",
            # password="New@123456",  <-- Removed because schema forbids it
            role_id=1,
        )

        assert update.email == "new@example.com"
        assert update.role_id == 1


class TestTokenSchemas:
    """Tests for token-related schemas."""

    def test_token_schema(self):
        """Token schema should work correctly."""
        token = Token(
            access_token="access123",
            refresh_token="refresh456",
        )

        assert token.access_token == "access123"
        assert token.refresh_token == "refresh456"
        assert token.token_type == "bearer"

    def test_token_custom_type(self):
        """Token type can be customized."""
        token = Token(
            access_token="access123",
            refresh_token="refresh456",
            token_type="custom",
        )

        assert token.token_type == "custom"
