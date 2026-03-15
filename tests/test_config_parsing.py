"""
TicketForge - Tests for Settings env var parsing.

Validates that api_keys and api_key_roles can be set via environment
variables using both JSON and plain-text formats without raising
pydantic_settings.SettingsError.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove any stale env vars that could interfere."""
    for key in ("API_KEYS", "API_KEY_ROLES"):
        monkeypatch.delenv(key, raising=False)


def _make_settings(monkeypatch, **env_overrides):
    """Create a fresh Settings instance with the given env overrides."""
    for k, v in env_overrides.items():
        monkeypatch.setenv(k, v)
    import config as cfg
    importlib.reload(cfg)
    return cfg.settings


class TestApiKeysParsing:
    """api_keys must accept comma-separated strings and JSON arrays."""

    def test_comma_separated_single_key(self, monkeypatch):
        s = _make_settings(monkeypatch, API_KEYS="changeme")
        assert s.api_keys == ["changeme"]

    def test_comma_separated_multiple_keys(self, monkeypatch):
        s = _make_settings(monkeypatch, API_KEYS="key1,key2,key3")
        assert s.api_keys == ["key1", "key2", "key3"]

    def test_comma_separated_with_spaces(self, monkeypatch):
        s = _make_settings(monkeypatch, API_KEYS=" key1 , key2 , key3 ")
        assert s.api_keys == ["key1", "key2", "key3"]

    def test_json_array(self, monkeypatch):
        s = _make_settings(monkeypatch, API_KEYS='["key1","key2"]')
        assert s.api_keys == ["key1", "key2"]

    def test_default_value(self, monkeypatch):
        s = _make_settings(monkeypatch)
        assert s.api_keys == ["changeme"]


class TestApiKeyRolesParsing:
    """api_key_roles must accept JSON strings and degrade gracefully."""

    def test_valid_json(self, monkeypatch):
        roles = {"admin-key": "admin", "viewer-key": "viewer"}
        s = _make_settings(monkeypatch, API_KEY_ROLES=json.dumps(roles))
        assert s.api_key_roles == roles

    def test_invalid_json_returns_empty(self, monkeypatch):
        s = _make_settings(monkeypatch, API_KEY_ROLES="not-json")
        assert s.api_key_roles == {}

    def test_default_value(self, monkeypatch):
        s = _make_settings(monkeypatch)
        assert s.api_key_roles == {}
