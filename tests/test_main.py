"""Tests for SafeMailSkill FastAPI application."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Patch settings before importing app so we don't need a real .env file
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch):
    monkeypatch.setenv("FASTMAIL_TOKEN", "test-token")
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")


# We import app lazily inside tests (after env patching) to keep it clean.
@pytest.fixture
def client(clear_module_cache):
    # Import inside the fixture so settings are already patched
    from main import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /v1/delete
# ---------------------------------------------------------------------------

class TestDeleteEndpoint:
    def test_delete_success(self, client):
        with patch("main._jmap") as mock_jmap:
            mock_jmap.shadow_delete.return_value = None
            resp = client.post("/v1/delete", json={"email_id": "abc123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["email_id"] == "abc123"

    def test_delete_missing_email_id(self, client):
        resp = client.post("/v1/delete", json={})
        assert resp.status_code == 422  # Unprocessable Entity

    def test_delete_jmap_error_returns_500(self, client):
        from jmap_client import JMAPError
        with patch("main._jmap") as mock_jmap:
            mock_jmap.shadow_delete.side_effect = JMAPError("JMAP failure")
            resp = client.post("/v1/delete", json={"email_id": "bad-id"})
        assert resp.status_code == 500
        assert "JMAP failure" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# /v1/send
# ---------------------------------------------------------------------------

class TestSendEndpoint:
    def test_send_success(self, client):
        with patch("main._jmap") as mock_jmap, patch("main.notify") as mock_notify:
            mock_jmap.create_outgoing_draft.return_value = "draft-id-1"
            resp = client.post(
                "/v1/send",
                json={"to": "alice@example.com", "subject": "Hello", "body": "World"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert "pending" in data["message"].lower() or "review" in data["message"].lower()
        mock_notify.assert_called_once()

    def test_send_invalid_email(self, client):
        resp = client.post(
            "/v1/send",
            json={"to": "not-an-email", "subject": "Oops", "body": "Body"},
        )
        assert resp.status_code == 422

    def test_send_missing_fields(self, client):
        resp = client.post("/v1/send", json={"to": "alice@example.com"})
        assert resp.status_code == 422

    def test_send_jmap_error_returns_500(self, client):
        from jmap_client import JMAPError
        with patch("main._jmap") as mock_jmap, patch("main.notify"):
            mock_jmap.create_outgoing_draft.side_effect = JMAPError("Draft failed")
            resp = client.post(
                "/v1/send",
                json={"to": "bob@example.com", "subject": "Test", "body": "Test body"},
            )
        assert resp.status_code == 500

    def test_send_generates_pin_and_notifies(self, client):
        """Verify that generate_pin is called and the PIN is passed to notify."""
        with patch("main._jmap") as mock_jmap, \
             patch("main.notify") as mock_notify, \
             patch("main.generate_pin", return_value="1234"):
            mock_jmap.create_outgoing_draft.return_value = "draft-id"
            client.post(
                "/v1/send",
                json={"to": "carol@example.com", "subject": "Hi", "body": "Hi there"},
            )
        mock_notify.assert_called_once_with(subject="Hi", body="Hi there", pin="1234")
        # PIN is also forwarded to create_outgoing_draft
        mock_jmap.create_outgoing_draft.assert_called_once_with(
            to="carol@example.com", subject="Hi", body="Hi there", pin="1234"
        )


# ---------------------------------------------------------------------------
# /v1/approve
# ---------------------------------------------------------------------------

class TestApproveEndpoint:
    def _make_draft(self, pin: str, age_seconds: int = 0) -> dict:
        ts = int(datetime.now(timezone.utc).timestamp()) - age_seconds
        return {
            "id": "draft-xyz",
            "keywords": {
                f"$ai_pin_{pin}": True,
                f"$ai_ts_{ts}": True,
                "$draft": True,
            },
            "to": [{"email": "alice@example.com"}],
            "subject": "Test",
            "bodyValues": {},
            "textBody": [],
        }

    def test_approve_success(self, client):
        draft = self._make_draft("5678", age_seconds=30)
        with patch("main._jmap") as mock_jmap:
            mock_jmap.find_draft_by_pin.return_value = draft
            mock_jmap.send_draft.return_value = None
            resp = client.post("/v1/approve", json={"pin": "5678"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_approve_wrong_pin(self, client):
        with patch("main._jmap") as mock_jmap:
            mock_jmap.find_draft_by_pin.return_value = None
            resp = client.post("/v1/approve", json={"pin": "0000"})
        assert resp.status_code == 404

    def test_approve_expired_pin(self, client):
        # Draft is 2 hours old
        draft = self._make_draft("9999", age_seconds=7201)
        with patch("main._jmap") as mock_jmap:
            mock_jmap.find_draft_by_pin.return_value = draft
            resp = client.post("/v1/approve", json={"pin": "9999"})
        assert resp.status_code == 410
        assert "expired" in resp.json()["detail"].lower()

    def test_approve_non_numeric_pin(self, client):
        resp = client.post("/v1/approve", json={"pin": "abcd"})
        assert resp.status_code == 422

    def test_approve_jmap_error_returns_500(self, client):
        from jmap_client import JMAPError
        with patch("main._jmap") as mock_jmap:
            mock_jmap.find_draft_by_pin.side_effect = JMAPError("Query failed")
            resp = client.post("/v1/approve", json={"pin": "1234"})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# generate_pin helper
# ---------------------------------------------------------------------------

def test_generate_pin_length():
    from jmap_client import generate_pin
    pin = generate_pin()
    assert len(pin) == 4
    assert pin.isdigit()


def test_generate_pin_custom_length():
    from jmap_client import generate_pin
    pin = generate_pin(6)
    assert len(pin) == 6


# ---------------------------------------------------------------------------
# _extract_timestamp_from_keywords helper
# ---------------------------------------------------------------------------

def test_extract_timestamp():
    from main import _extract_timestamp_from_keywords
    ts = 1700000000
    keywords = {f"$ai_ts_{ts}": True, "$draft": True}
    assert _extract_timestamp_from_keywords(keywords) == ts


def test_extract_timestamp_missing():
    from main import _extract_timestamp_from_keywords
    assert _extract_timestamp_from_keywords({"$draft": True}) is None
