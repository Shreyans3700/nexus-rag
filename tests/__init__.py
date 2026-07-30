"""Test configuration shared before application modules are imported."""
import os

# Configuration is read while src.config.config is imported. These values keep
# unit tests independent of a developer's local .env file and external services.
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
