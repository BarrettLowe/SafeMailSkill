"""Unit tests for Pydantic request schema validation."""

import pytest
from pydantic import ValidationError

from app.schemas import ApproveRequest, DeleteRequest, JMAPProxyRequest, SendRequest


# ── ApproveRequest ────────────────────────────────────────────────────────────


def test_approve_valid_pin():
    req = ApproveRequest(pin="1234")
    assert req.pin == "1234"


def test_approve_rejects_non_digit_pin():
    with pytest.raises(ValidationError):
        ApproveRequest(pin="12ab")


def test_approve_rejects_too_short_pin():
    with pytest.raises(ValidationError):
        ApproveRequest(pin="123")


def test_approve_rejects_too_long_pin():
    with pytest.raises(ValidationError):
        ApproveRequest(pin="12345")


def test_approve_rejects_empty_pin():
    with pytest.raises(ValidationError):
        ApproveRequest(pin="")


# ── DeleteRequest ─────────────────────────────────────────────────────────────


def test_delete_valid():
    req = DeleteRequest(message_id="M001")
    assert req.message_id == "M001"


def test_delete_requires_message_id():
    with pytest.raises(ValidationError):
        DeleteRequest()


# ── SendRequest ───────────────────────────────────────────────────────────────


def test_send_valid():
    req = SendRequest(to="user@example.com", subject="Hi", body="Hello")
    assert req.to == "user@example.com"


def test_send_rejects_invalid_email():
    with pytest.raises(ValidationError):
        SendRequest(to="not-an-email", subject="Hi", body="Hello")


def test_send_requires_all_fields():
    with pytest.raises(ValidationError):
        SendRequest(to="user@example.com", subject="Hi")


# ── JMAPProxyRequest ──────────────────────────────────────────────────────────


def test_jmap_valid_single_call():
    req = JMAPProxyRequest(methodCalls=[["Mailbox/get", {}, "c1"]])
    assert len(req.methodCalls) == 1


def test_jmap_valid_multiple_calls():
    req = JMAPProxyRequest(
        methodCalls=[
            ["Mailbox/get", {}, "c1"],
            ["Email/query", {"inMailbox": "abc"}, "c2"],
        ]
    )
    assert len(req.methodCalls) == 2


def test_jmap_rejects_wrong_element_count():
    with pytest.raises(ValidationError):
        JMAPProxyRequest(methodCalls=[["Mailbox/get", {}]])  # only 2 elements


def test_jmap_rejects_non_string_method():
    with pytest.raises(ValidationError):
        JMAPProxyRequest(methodCalls=[[123, {}, "c1"]])


def test_jmap_rejects_non_dict_args():
    with pytest.raises(ValidationError):
        JMAPProxyRequest(methodCalls=[["Mailbox/get", "not-a-dict", "c1"]])


def test_jmap_rejects_non_string_correlation_id():
    with pytest.raises(ValidationError):
        JMAPProxyRequest(methodCalls=[["Mailbox/get", {}, 99]])


def test_jmap_rejects_empty_list():
    with pytest.raises(ValidationError):
        JMAPProxyRequest(methodCalls=[])
