"""Integration tests for FastAPI routes using TestClient."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

AUTH = {"Authorization": "Bearer test-api-key-abc123xxx"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ── /health ───────────────────────────────────────────────────────────────────


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Auth enforcement ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/v1/delete", "/v1/send", "/v1/approve", "/v1/jmap"])
def test_missing_auth_returns_401(client, path):
    resp = client.post(path, json={})
    assert resp.status_code == 401


def test_wrong_token_returns_401(client):
    resp = client.post(
        "/v1/delete",
        json={"message_id": "msg1"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


# ── /v1/delete ────────────────────────────────────────────────────────────────


def test_trash_email_success(client):
    with patch("app.main.move_to_folder", new_callable=AsyncMock) as mock_move:
        resp = client.post(
            "/v1/delete",
            json={"message_id": "msg-abc"},
            headers=AUTH,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    mock_move.assert_called_once_with("msg-abc", "mailbox-trash-id")


def test_trash_email_propagates_502_on_jmap_error(client):
    with patch(
        "app.main.move_to_folder",
        new_callable=AsyncMock,
        side_effect=RuntimeError("JMAP error"),
    ):
        resp = client.post("/v1/delete", json={"message_id": "msg-abc"}, headers=AUTH)
    assert resp.status_code == 502


def test_trash_email_succeeds_when_jmap_returns_null_not_updated(client):
    """Regression: JMAP response with notUpdated=null must not raise TypeError."""
    with patch("app.main.move_to_folder", new_callable=AsyncMock) as mock_move:
        mock_move.return_value = None
        resp = client.post(
            "/v1/delete",
            json={"message_id": "msg-null"},
            headers=AUTH,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


# ── /v1/send ──────────────────────────────────────────────────────────────────


def test_send_email_returns_pending(client):
    with (
        patch("app.main.create_draft", new_callable=AsyncMock),
        patch("app.main.send_ntfy_notification", new_callable=AsyncMock),
    ):
        resp = client.post(
            "/v1/send",
            json={"to": "recipient@example.com", "subject": "Test", "body": "Hello"},
            headers=AUTH,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_send_email_rejects_invalid_address(client):
    resp = client.post(
        "/v1/send",
        json={"to": "not-an-email", "subject": "Test", "body": "Hello"},
        headers=AUTH,
    )
    assert resp.status_code == 422


# ── /v1/approve ───────────────────────────────────────────────────────────────


def test_approve_valid_pin_sends_draft(client):
    with (
        patch(
            "app.main.find_draft_by_pin",
            new_callable=AsyncMock,
            return_value="draft-msg-001",
        ),
        patch("app.main.submit_email", new_callable=AsyncMock),
    ):
        resp = client.post("/v1/approve", json={"pin": "4321"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"


def test_approve_unknown_pin_returns_404(client):
    with patch(
        "app.main.find_draft_by_pin",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.post("/v1/approve", json={"pin": "0000"}, headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["status"] == "error"


def test_approve_rejects_non_digit_pin(client):
    resp = client.post("/v1/approve", json={"pin": "abcd"}, headers=AUTH)
    assert resp.status_code == 422


# ── /v1/jmap — policy enforcement ────────────────────────────────────────────


def test_jmap_blocks_email_destroy(client):
    resp = client.post(
        "/v1/jmap",
        json={"methodCalls": [["Email/destroy", {"ids": ["m1"]}, "c1"]]},
        headers=AUTH,
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["status"] == "blocked"
    assert any(c["method"] == "Email/destroy" for c in body["blockedCalls"])


def test_jmap_blocks_email_submission_set(client):
    resp = client.post(
        "/v1/jmap",
        json={"methodCalls": [["EmailSubmission/set", {}, "c1"]]},
        headers=AUTH,
    )
    assert resp.status_code == 403


def test_jmap_blocks_mixed_batch_with_one_forbidden(client):
    resp = client.post(
        "/v1/jmap",
        json={
            "methodCalls": [
                ["Mailbox/get", {}, "c1"],
                ["Email/destroy", {"ids": ["m1"]}, "c2"],
            ]
        },
        headers=AUTH,
    )
    assert resp.status_code == 403


# ── /v1/jmap — forwarding ─────────────────────────────────────────────────────


def test_jmap_forwards_allowed_method(client):
    mock_session = {
        "api_url": "https://api.example.com/jmap",
        "account_id": "account-123",
        "ready": True,
    }
    mock_response = {"methodResponses": [["Mailbox/get", {"list": []}, "c1"]]}

    with (
        patch("app.main.get_session", new_callable=AsyncMock, return_value=mock_session),
        patch("app.main.jmap_call", new_callable=AsyncMock, return_value=mock_response),
    ):
        resp = client.post(
            "/v1/jmap",
            json={"methodCalls": [["Mailbox/get", {}, "c1"]]},
            headers=AUTH,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["methodResponses"][0][0] == "Mailbox/get"


def test_jmap_injects_account_id(client):
    """accountId must be inserted into method args that omit it."""
    mock_session = {
        "api_url": "https://api.example.com/jmap",
        "account_id": "injected-account",
        "ready": True,
    }
    captured = {}

    async def capture_calls(method_calls):
        captured["calls"] = method_calls
        return {"methodResponses": []}

    with (
        patch("app.main.get_session", new_callable=AsyncMock, return_value=mock_session),
        patch("app.main.jmap_call", side_effect=capture_calls),
    ):
        client.post(
            "/v1/jmap",
            json={"methodCalls": [["Email/query", {}, "c1"]]},
            headers=AUTH,
        )

    injected_args = captured["calls"][0][1]
    assert injected_args["accountId"] == "injected-account"


# ── /v1/jmap — blocked mailbox redaction ─────────────────────────────────────────


def test_jmap_filters_blocked_mailboxes_from_mailbox_get(client):
    """Mailboxes in AGENT_BLOCKED_MAILBOX_IDS must be stripped from Mailbox/get responses."""
    mock_session = {
        "api_url": "https://api.example.com/jmap",
        "account_id": "acct-1",
        "ready": True,
    }
    mock_response = {
        "methodResponses": [[
            "Mailbox/get",
            {"list": [
                {"id": "inbox-id", "name": "Inbox", "role": "inbox"},
                {"id": "trash-real-id", "name": "Trash", "role": "trash"},
            ]},
            "c1",
        ]]
    }
    with (
        patch("app.main.get_session", new_callable=AsyncMock, return_value=mock_session),
        patch("app.main.jmap_call", new_callable=AsyncMock, return_value=mock_response),
        patch.object(type(settings), "blocked_mailbox_id_set", return_value=frozenset(["trash-real-id"])),
    ):
        resp = client.post(
            "/v1/jmap",
            json={"methodCalls": [["Mailbox/get", {}, "c1"]]},
            headers=AUTH,
        )
    assert resp.status_code == 200
    mb_list = resp.json()["methodResponses"][0][1]["list"]
    ids = [m["id"] for m in mb_list]
    assert "trash-real-id" not in ids
    assert "inbox-id" in ids


def test_jmap_blocks_email_set_move_to_blocked_mailbox(client):
    """Email/set targeting a blocked mailbox ID must return 403."""
    mock_session = {"api_url": "https://api.example.com/jmap", "account_id": "acct-1", "ready": True}
    with (
        patch("app.main.get_session", new_callable=AsyncMock, return_value=mock_session),
        patch.object(type(settings), "blocked_mailbox_id_set", return_value=frozenset(["blocked-mb"])),
    ):
        resp = client.post(
            "/v1/jmap",
            json={"methodCalls": [[
                "Email/set",
                {"update": {"msg-1": {"mailboxIds": {"blocked-mb": True}}}},
                "c1",
            ]]},
            headers=AUTH,
        )
    assert resp.status_code == 403
    body = resp.json()
    assert body["status"] == "blocked"
    assert any(c["method"] == "Email/set" for c in body["blockedCalls"])


def test_jmap_always_hides_trash_role_from_mailbox_get(client):
    """Mailboxes with role='trash' must be filtered even without AGENT_BLOCKED_MAILBOX_IDS."""
    mock_session = {"api_url": "https://api.example.com/jmap", "account_id": "acct-1", "ready": True}
    mock_response = {
        "methodResponses": [[
            "Mailbox/get",
            {"list": [
                {"id": "inbox-id", "name": "Inbox", "role": "inbox"},
                {"id": "trash-id", "name": "Trash", "role": "trash"},
            ]},
            "c1",
        ]]
    }
    with (
        patch("app.main.get_session", new_callable=AsyncMock, return_value=mock_session),
        patch("app.main.jmap_call", new_callable=AsyncMock, return_value=mock_response),
        patch.object(type(settings), "blocked_mailbox_id_set", return_value=frozenset()),
    ):
        resp = client.post(
            "/v1/jmap",
            json={"methodCalls": [["Mailbox/get", {}, "c1"]]},
            headers=AUTH,
        )
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()["methodResponses"][0][1]["list"]]
    assert "trash-id" not in ids
    assert "inbox-id" in ids


def test_jmap_always_hides_snoozed_name_from_mailbox_get(client):
    """Mailboxes named 'Snoozed' must be filtered even without AGENT_BLOCKED_MAILBOX_IDS."""
    mock_session = {"api_url": "https://api.example.com/jmap", "account_id": "acct-1", "ready": True}
    mock_response = {
        "methodResponses": [[
            "Mailbox/get",
            {"list": [
                {"id": "inbox-id", "name": "Inbox", "role": "inbox"},
                {"id": "snoozed-id", "name": "Snoozed", "role": None},
            ]},
            "c1",
        ]]
    }
    with (
        patch("app.main.get_session", new_callable=AsyncMock, return_value=mock_session),
        patch("app.main.jmap_call", new_callable=AsyncMock, return_value=mock_response),
        patch.object(type(settings), "blocked_mailbox_id_set", return_value=frozenset()),
    ):
        resp = client.post(
            "/v1/jmap",
            json={"methodCalls": [["Mailbox/get", {}, "c1"]]},
            headers=AUTH,
        )
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()["methodResponses"][0][1]["list"]]
    assert "snoozed-id" not in ids
    assert "inbox-id" in ids
