import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_DB", "0")

from starlette.requests import Request

from src.auth import create_access_token
from src.rate_limit import get_user_or_ip


def make_request(authorization=None, client_host="1.2.3.4"):
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("ascii")))
    scope = {
        "type": "http",
        "headers": headers,
        "client": (client_host, 12345),
    }
    return Request(scope)


class GetUserOrIpTests(unittest.TestCase):
    def test_valid_token_returns_user_key(self):
        token = create_access_token("user-123", "user@example.com")
        request = make_request(authorization=f"Bearer {token}")

        self.assertEqual(get_user_or_ip(request), "user:user-123")

    def test_missing_authorization_header_falls_back_to_ip(self):
        request = make_request(authorization=None, client_host="9.9.9.9")

        self.assertEqual(get_user_or_ip(request), "9.9.9.9")

    def test_malformed_token_falls_back_to_ip(self):
        request = make_request(authorization="Bearer not-a-jwt", client_host="9.9.9.9")

        self.assertEqual(get_user_or_ip(request), "9.9.9.9")

    def test_expired_token_falls_back_to_ip(self):
        with patch("src.auth.time.time", return_value=1_000):
            token = create_access_token("user-123", "user@example.com")

        with patch("src.auth.time.time", return_value=4_601):
            request = make_request(authorization=f"Bearer {token}", client_host="9.9.9.9")
            self.assertEqual(get_user_or_ip(request), "9.9.9.9")

    def test_wrong_scheme_falls_back_to_ip(self):
        request = make_request(authorization="Basic abc", client_host="9.9.9.9")

        self.assertEqual(get_user_or_ip(request), "9.9.9.9")


if __name__ == "__main__":
    unittest.main()
