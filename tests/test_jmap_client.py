"""Tests for JMAP client helpers."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("FASTMAIL_TOKEN", "test-token")
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")


@pytest.fixture
def jmap(clear_module_cache):
    from jmap_client import JMAPClient
    return JMAPClient()


class TestJMAPClientSession:
    def test_get_session_sets_account_id(self, jmap):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "apiUrl": "https://api.fastmail.com/jmap/api/",
            "primaryAccounts": {
                "urn:ietf:params:jmap:mail": "acct-001"
            },
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_resp):
            session = jmap._get_session()
        assert jmap._account_id == "acct-001"

    def test_get_session_cached(self, jmap):
        jmap._session = {"apiUrl": "x", "primaryAccounts": {"urn:ietf:params:jmap:mail": "a"}}
        jmap._account_id = "a"
        with patch("httpx.get") as mock_get:
            jmap._get_session()
            mock_get.assert_not_called()


class TestShadowDelete:
    def _setup_jmap(self, jmap):
        jmap._session = {
            "apiUrl": "https://api.fastmail.com/jmap/api/",
            "primaryAccounts": {"urn:ietf:params:jmap:mail": "acct-001"},
        }
        jmap._account_id = "acct-001"

    def test_shadow_delete_calls_email_set(self, jmap):
        self._setup_jmap(jmap)

        # We'll mock _get_mailbox_id and _get_email and _call
        jmap._get_mailbox_id = MagicMock(return_value="trash-mb-id")
        jmap._get_email = MagicMock(return_value={"id": "email-1", "mailboxIds": {"inbox-id": True}})

        update_response = {
            "methodResponses": [
                ["Email/set", {"updated": {"email-1": {}}}, "0"]
            ]
        }
        jmap._call = MagicMock(return_value=update_response)

        jmap.shadow_delete("email-1")

        jmap._call.assert_called_once()
        call_args = jmap._call.call_args[0][0]
        method, args, _ = call_args[0]
        assert method == "Email/set"
        assert "email-1" in args["update"]

    def test_shadow_delete_raises_on_not_updated(self, jmap):
        from jmap_client import JMAPError
        self._setup_jmap(jmap)
        jmap._get_mailbox_id = MagicMock(return_value="trash-id")
        jmap._get_email = MagicMock(return_value={"id": "e1", "mailboxIds": {}})
        jmap._call = MagicMock(return_value={
            "methodResponses": [
                ["Email/set", {"updated": {}, "notUpdated": {"e1": "some error"}}, "0"]
            ]
        })
        with pytest.raises(JMAPError):
            jmap.shadow_delete("e1")


class TestCreateOutgoingDraft:
    def _setup_jmap(self, jmap):
        jmap._session = {
            "apiUrl": "https://api.fastmail.com/jmap/api/",
            "primaryAccounts": {"urn:ietf:params:jmap:mail": "acct-001"},
        }
        jmap._account_id = "acct-001"

    def test_create_draft_returns_id(self, jmap):
        self._setup_jmap(jmap)
        jmap._get_mailbox_id = MagicMock(return_value="outgoing-mb-id")
        jmap._get_identity = MagicMock(return_value="me@fastmail.com")
        jmap._call = MagicMock(return_value={
            "methodResponses": [
                ["Email/set", {"created": {"draft": {"id": "new-draft-id"}}}, "0"]
            ]
        })
        draft_id = jmap.create_outgoing_draft("bob@example.com", "Subj", "Body", "7890")
        assert draft_id == "new-draft-id"

    def test_create_draft_embeds_pin_keyword(self, jmap):
        self._setup_jmap(jmap)
        jmap._get_mailbox_id = MagicMock(return_value="outgoing-mb-id")
        jmap._get_identity = MagicMock(return_value="me@fastmail.com")
        captured = {}
        def _capture_call(method_calls):
            captured["calls"] = method_calls
            return {"methodResponses": [["Email/set", {"created": {"draft": {"id": "d1"}}}, "0"]]}
        jmap._call = _capture_call

        jmap.create_outgoing_draft("a@b.com", "S", "B", "1234")

        _, args, _ = captured["calls"][0]
        keywords = args["create"]["draft"]["keywords"]
        assert "$ai_pin_1234" in keywords
        # Timestamp keyword present
        ts_keys = [k for k in keywords if k.startswith("$ai_ts_")]
        assert len(ts_keys) == 1


class TestFindDraftByPin:
    def _setup_jmap(self, jmap):
        jmap._session = {
            "apiUrl": "https://api.fastmail.com/jmap/api/",
            "primaryAccounts": {"urn:ietf:params:jmap:mail": "acct-001"},
        }
        jmap._account_id = "acct-001"

    def test_returns_none_when_not_found(self, jmap):
        self._setup_jmap(jmap)
        jmap._get_mailbox_id = MagicMock(return_value="outgoing-id")
        jmap._call = MagicMock(return_value={
            "methodResponses": [
                ["Email/query", {"ids": []}, "0"],
                ["Email/get", {"list": []}, "1"],
            ]
        })
        result = jmap.find_draft_by_pin("9999")
        assert result is None

    def test_returns_draft_when_found(self, jmap):
        self._setup_jmap(jmap)
        jmap._get_mailbox_id = MagicMock(return_value="outgoing-id")
        draft = {"id": "d42", "keywords": {"$ai_pin_1111": True}, "to": [], "subject": "S"}
        jmap._call = MagicMock(return_value={
            "methodResponses": [
                ["Email/query", {"ids": ["d42"]}, "0"],
                ["Email/get", {"list": [draft]}, "1"],
            ]
        })
        result = jmap.find_draft_by_pin("1111")
        assert result is not None
        assert result["id"] == "d42"
