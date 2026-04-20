"""Unit tests for scripts/gatekeeper.py mailbox resolution behavior."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace


def _load_gatekeeper_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "gatekeeper.py"
    spec = spec_from_file_location("gatekeeper_cli", path)
    module = module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_resolve_mailbox_name_to_id_uses_mailboxes_endpoint(monkeypatch):
    gatekeeper = _load_gatekeeper_module()
    gatekeeper._mailbox_lookup_cache = None

    def fake_request(method, path, body=None):
        assert method == "GET"
        assert path == "/v1/mailboxes"
        return [{"id": "mbx-123", "name": "Receipts"}]

    monkeypatch.setattr(gatekeeper, "_request", fake_request)
    assert gatekeeper._resolve_mailbox_id("Receipts") == "mbx-123"
    assert gatekeeper._resolve_mailbox_id("receipts") == "mbx-123"


def test_resolve_mailbox_name_to_id_falls_back_to_input(monkeypatch):
    gatekeeper = _load_gatekeeper_module()
    gatekeeper._mailbox_lookup_cache = None
    monkeypatch.setattr(gatekeeper, "_request", lambda *_args, **_kwargs: [{"name": "Receipts"}])
    assert gatekeeper._resolve_mailbox_id("Receipts") == "Receipts"


def test_cmd_list_emails_resolves_mailbox_name_before_query(monkeypatch):
    gatekeeper = _load_gatekeeper_module()
    jmap_calls: dict = {}
    monkeypatch.setattr(gatekeeper, "_resolve_mailbox_id", lambda name: "mbx-456")

    def fake_jmap(method_calls):
        jmap_calls["method_calls"] = method_calls
        return {"methodResponses": [["Email/query", {"ids": []}, "c1"], ["Email/get", {"list": []}, "c2"]]}

    monkeypatch.setattr(gatekeeper, "_jmap", fake_jmap)
    args = SimpleNamespace(
        mailbox_name="Receipts",
        search=None,
        from_=None,
        subject=None,
        unread=False,
        after=None,
        before=None,
        limit=20,
    )
    gatekeeper.cmd_list_emails(args)

    forwarded_filter = jmap_calls["method_calls"][0][1]["filter"]
    assert forwarded_filter["inMailbox"] == "mbx-456"


def test_cmd_move_resolves_mailbox_name_before_update(monkeypatch):
    gatekeeper = _load_gatekeeper_module()
    jmap_calls: dict = {}
    monkeypatch.setattr(gatekeeper, "_resolve_mailbox_id", lambda name: "mbx-789")

    def fake_jmap(method_calls):
        jmap_calls["method_calls"] = method_calls
        return {"methodResponses": [["Email/set", {"updated": {"msg-1": None}}, "c1"]]}

    monkeypatch.setattr(gatekeeper, "_jmap", fake_jmap)
    args = SimpleNamespace(message_id="msg-1", mailbox_name="Receipts")
    gatekeeper.cmd_move(args)

    mailbox_ids = jmap_calls["method_calls"][0][1]["update"]["msg-1"]["mailboxIds"]
    assert mailbox_ids == {"mbx-789": True}
