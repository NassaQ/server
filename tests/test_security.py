"""
Unit tests for security utilities (password hashing and JWT).
"""

import pytest
from datetime import timedelta

# Import after environment variables are set in conftest.py
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password_returns_different_hash(self):
        """Hash should be different from plain password."""
        password = "MySecurePassword123!"
        hashed = hash_password(password)

        assert hashed != password
        assert len(hashed) > 0

    def test_hash_password_different_for_same_input(self):
        """Same password should produce different hashes (due to salt)."""
        password = "MySecurePassword123!"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Verify should return True for correct password."""
        password = "MySecurePassword123!"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Verify should return False for incorrect password."""
        password = "MySecurePassword123!"
        wrong_password = "WrongPassword456!"
        hashed = hash_password(password)

        assert verify_password(wrong_password, hashed) is False

    def test_verify_password_empty_password(self):
        """Verify should handle empty password."""
        password = "MySecurePassword123!"
        hashed = hash_password(password)

        assert verify_password("", hashed) is False

    def test_hash_password_special_characters(self):
        """Hash should work with special characters."""
        password = "P@$$w0rd!#$%^&*()"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_hash_password_unicode(self):
        """Hash should work with unicode characters."""
        password = "مرحبا123!@#"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True


class TestJWTTokens:
    """Tests for JWT token functions."""

    def test_create_access_token(self):
        """Access token should be created successfully."""
        user_id = 123
        # Added mandatory role_id argument
        token = create_access_token(subject=user_id, role_id=1)

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_refresh_token(self):
        """Refresh token should be created successfully."""
        user_id = 123
        token = create_refresh_token(subject=user_id)

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decode_access_token(self):
        """Access token should be decodable."""
        user_id = 123
        # Added mandatory role_id argument
        token = create_access_token(subject=user_id, role_id=1)
        payload = decode_token(token)

        assert payload is not None
        assert payload["sub"] == str(user_id)
        assert payload["rid"] == 1  # Verify role_id is present
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    def test_decode_refresh_token(self):
        """Refresh token should be decodable."""
        user_id = 456
        token = create_refresh_token(subject=user_id)
        payload = decode_token(token)

        assert payload is not None
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "refresh"
        assert "exp" in payload
        assert "iat" in payload

    def test_access_token_with_custom_expiry(self):
        """Access token should respect custom expiry."""
        user_id = 123
        custom_delta = timedelta(hours=2)
        # Added mandatory role_id argument
        token = create_access_token(subject=user_id, role_id=1, expires_delta=custom_delta)
        payload = decode_token(token)

        assert payload is not None
        # Token should be valid (we can decode it)
        assert payload["sub"] == str(user_id)

    def test_decode_invalid_token(self):
        """Invalid token should return None."""
        invalid_token = "invalid.token.here"
        payload = decode_token(invalid_token)

        assert payload is None

    def test_decode_tampered_token(self):
        """Tampered token should return None."""
        user_id = 123
        # Added mandatory role_id argument
        token = create_access_token(subject=user_id, role_id=1)
        # Tamper with the token
        tampered_token = token[:-5] + "xxxxx"
        payload = decode_token(tampered_token)

        assert payload is None

    def test_decode_empty_token(self):
        """Empty token should return None."""
        payload = decode_token("")

        assert payload is None

    def test_different_users_get_different_tokens(self):
        """Different users should get different tokens."""
        # Added mandatory role_id argument
        token1 = create_access_token(subject=1, role_id=1)
        token2 = create_access_token(subject=2, role_id=1)

        assert token1 != token2

    def test_access_and_refresh_tokens_are_different(self):
        """Access and refresh tokens should be different for same user."""
        user_id = 123
        # Added mandatory role_id argument
        access_token = create_access_token(subject=user_id, role_id=1)
        refresh_token = create_refresh_token(subject=user_id)

        assert access_token != refresh_token

    def test_token_type_is_correct(self):
        """Token type should be correctly set."""
        user_id = 123

        # Added mandatory role_id argument
        access_payload = decode_token(create_access_token(subject=user_id, role_id=1))
        refresh_payload = decode_token(create_refresh_token(subject=user_id))

        assert access_payload["type"] == "access"
        assert refresh_payload["type"] == "refresh"