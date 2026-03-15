"""
TicketForge — Tests for Settings env var parsing.

Validates that api_keys and api_key_roles can be set via environment
variables using both JSON and plain-text formats without raising
pydantic_settings.SettingsError.
"""
from __future__ import annotations

import json
import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove any stale env vars that could interfere."""
    for key in ("API_KEYS", "API_KEY_ROLES"):
        monkeypatch.delenv(key, raising=False)


def _make_settings(**env_overrides):
    """Create a fresh Settings instance with the given env overrides."""
    for k, v in env_overrides.items():
        os.environ[k] = v
    try:
        # Reload to pick up new env vars
        import importlib
        import config as cfg
        importlib.reload(cfg)
        return cfg.settings
    finally:
        for k in env_overrides:
            os.environ.pop(k, None)


class TestApiKeysParsing:
    """api_keys must accept comma-separated strings and JSON arrays."""

    def test_comma_separated_single_key(self):
        s = _make_settings(API_KEYS="changeme")
        assert s.api_keys == ["changeme"]

    def test_comma_separated_multiple_keys(self):
        s = _make_settings(API_KEYS="key1,key2,key3")
        assert s.api_keys == ["key1", "key2", "key3"]

    def test_comma_separated_with_spaces(self):
        s = _make_settings(API_KEYS=" key1 , key2 , key3 ")
        assert s.api_keys == ["key1", "key2", "key3"]

    def test_json_array(self):
        s = _make_settings(API_KEYS='["key1","key2"]')
        assert s.api_keys == ["key1", "key2"]

    def test_default_value(self):
        s = _make_settings()
        assert s.api_keys == ["changeme"]


class TestApiKeyRolesParsing:
    """api_key_roles must accept JSON strings and degrade gracefully."""

    def test_valid_json(self):
        roles = {"admin-key": "admin", "viewer-key": "viewer"}
        s = _make_settings(API_KEY_ROLES=json.dumps(roles))
        assert s.api_key_roles == roles

    def test_invalid_json_returns_empty(self):
        s = _make_settings(API_KEY_ROLES="not-json")
        assert s.api_key_roles == {}

    def test_default_value(self):
        s = _make_settings()
        assert s.api_key_roles == {}
