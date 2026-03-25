"""Tests for TRMNL marketplace webhook security (SOK-172)."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _make_client(client_secret: str) -> TestClient:
    """Return a TestClient with marketplace module patched to use the given secret."""
    import emergent_atelier.api.marketplace as mp

    with patch.object(mp, "_CLIENT_SECRET", client_secret):
        # Re-import server with fresh state to avoid stale module cache issues
        from emergent_atelier.api import server as srv
        return TestClient(srv.app, raise_server_exceptions=False)


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# _verify_trmnl_signature unit tests
# ---------------------------------------------------------------------------

class TestVerifyTrmnlSignature:
    def test_missing_secret_raises_runtime_error(self):
        import emergent_atelier.api.marketplace as mp
        with patch.object(mp, "_CLIENT_SECRET", ""):
            with pytest.raises(RuntimeError, match="TRMNL_CLIENT_SECRET is not configured"):
                mp._verify_trmnl_signature(b"body", "any-sig")

    def test_valid_signature_returns_true(self):
        import emergent_atelier.api.marketplace as mp
        secret = "supersecret"
        body = b'{"event": "test"}'
        sig = _sign(body, secret)
        with patch.object(mp, "_CLIENT_SECRET", secret):
            assert mp._verify_trmnl_signature(body, sig) is True

    def test_invalid_signature_returns_false(self):
        import emergent_atelier.api.marketplace as mp
        with patch.object(mp, "_CLIENT_SECRET", "supersecret"):
            assert mp._verify_trmnl_signature(b"body", "badhex") is False


# ---------------------------------------------------------------------------
# validate_marketplace_config
# ---------------------------------------------------------------------------

class TestValidateMarketplaceConfig:
    def test_raises_when_secret_missing(self):
        import emergent_atelier.api.marketplace as mp
        with patch.object(mp, "_CLIENT_SECRET", ""):
            with pytest.raises(RuntimeError, match="TRMNL_CLIENT_SECRET is not set"):
                mp.validate_marketplace_config()

    def test_passes_when_secret_present(self):
        import emergent_atelier.api.marketplace as mp
        with patch.object(mp, "_CLIENT_SECRET", "mysecret"):
            mp.validate_marketplace_config()  # should not raise


# ---------------------------------------------------------------------------
# Webhook endpoint integration tests: secret missing → 500
# ---------------------------------------------------------------------------

class TestWebhookRejectsWhenSecretMissing:
    """When TRMNL_CLIENT_SECRET is not configured, webhook endpoints must return 500."""

    def _client_no_secret(self) -> TestClient:
        import emergent_atelier.api.marketplace as mp
        from emergent_atelier.api.server import app
        with patch.object(mp, "_CLIENT_SECRET", ""):
            return TestClient(app, raise_server_exceptions=False)

    def test_install_success_returns_500_without_secret(self):
        client = self._client_no_secret()
        resp = client.post(
            "/install/success",
            content=b'{"plugin_setting_id":"x","uuid":"y"}',
            headers={"x-trmnl-signature": "any", "Authorization": "Bearer tok"},
        )
        assert resp.status_code == 500

    def test_markup_returns_500_without_secret(self):
        client = self._client_no_secret()
        resp = client.post(
            "/markup",
            content=b"",
            headers={"x-trmnl-signature": "any", "Authorization": "Bearer tok"},
        )
        assert resp.status_code == 500

    def test_uninstall_returns_500_without_secret(self):
        client = self._client_no_secret()
        resp = client.post(
            "/uninstall",
            content=b'{"plugin_setting_id":"x","uuid":"y"}',
            headers={"x-trmnl-signature": "any", "Authorization": "Bearer tok"},
        )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Webhook endpoint integration tests: bad signature → 401
# ---------------------------------------------------------------------------

class TestWebhookRejectsBadSignature:
    """When secret is configured but signature is wrong, endpoints return 401."""

    def test_install_success_rejects_bad_sig(self):
        import emergent_atelier.api.marketplace as mp
        from emergent_atelier.api.server import app
        with patch.object(mp, "_CLIENT_SECRET", "testsecret"):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/install/success",
                content=b'{"plugin_setting_id":"x","uuid":"y"}',
                headers={"x-trmnl-signature": "badsig", "Authorization": "Bearer tok"},
            )
        assert resp.status_code == 401

    def test_markup_rejects_bad_sig(self):
        import emergent_atelier.api.marketplace as mp
        from emergent_atelier.api.server import app
        with patch.object(mp, "_CLIENT_SECRET", "testsecret"):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/markup",
                content=b"",
                headers={"x-trmnl-signature": "badsig", "Authorization": "Bearer tok"},
            )
        assert resp.status_code == 401

    def test_uninstall_rejects_bad_sig(self):
        import emergent_atelier.api.marketplace as mp
        from emergent_atelier.api.server import app
        with patch.object(mp, "_CLIENT_SECRET", "testsecret"):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/uninstall",
                content=b'{"plugin_setting_id":"x","uuid":"y"}',
                headers={"x-trmnl-signature": "badsig", "Authorization": "Bearer tok"},
            )
        assert resp.status_code == 401
