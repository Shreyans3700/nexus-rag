import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")

from fastapi import HTTPException

from src.auth import (
    _extract_bearer_token,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class AuthenticationTests(unittest.TestCase):
    def test_password_hash_verifies_only_the_original_password(self):
        password_hash = hash_password("correct horse battery staple")

        self.assertTrue(verify_password("correct horse battery staple", password_hash))
        self.assertFalse(verify_password("not the password", password_hash))

    def test_valid_token_round_trips_claims(self):
        token = create_access_token("user-123", "user@example.com")

        payload = decode_access_token(token)

        self.assertEqual(payload["sub"], "user-123")
        self.assertEqual(payload["email"], "user@example.com")

    def test_malformed_signature_returns_unauthorized(self):
        token = create_access_token("user-123", "user@example.com")
        malformed = token.rsplit(".", 1)[0] + ".%%%"

        with self.assertRaises(HTTPException) as error:
            decode_access_token(malformed)

        self.assertEqual(error.exception.status_code, 401)

    def test_expired_token_returns_unauthorized(self):
        with patch("src.auth.time.time", return_value=1_000):
            token = create_access_token("user-123", "user@example.com")

        with patch("src.auth.time.time", return_value=4_601), self.assertRaises(HTTPException) as error:
            decode_access_token(token)

        self.assertEqual(error.exception.status_code, 401)

    def test_bearer_header_requires_the_expected_scheme(self):
        self.assertEqual(_extract_bearer_token("Bearer abc"), "abc")
        with self.assertRaises(HTTPException):
            _extract_bearer_token("Basic abc")
