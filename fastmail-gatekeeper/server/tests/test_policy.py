"""Unit tests for the JMAP policy enforcement layer."""

from app.policy import enforce_policy


# ── Blocked methods ───────────────────────────────────────────────────────────


def test_email_destroy_is_blocked():
    blocked = enforce_policy([["Email/destroy", {"ids": ["m1"]}, "c1"]])
    assert len(blocked) == 1
    assert blocked[0]["method"] == "Email/destroy"
    assert blocked[0]["callId"] == "c1"


def test_emailsubmission_set_is_blocked():
    blocked = enforce_policy([["EmailSubmission/set", {"create": {}}, "c1"]])
    assert len(blocked) == 1
    assert blocked[0]["method"] == "EmailSubmission/set"


def test_mailbox_destroy_is_blocked():
    blocked = enforce_policy([["Mailbox/destroy", {"ids": ["mb1"]}, "c1"]])
    assert len(blocked) == 1


def test_identity_set_is_blocked():
    blocked = enforce_policy([["Identity/set", {}, "c1"]])
    assert len(blocked) == 1


def test_thread_destroy_is_blocked():
    blocked = enforce_policy([["Thread/destroy", {}, "c1"]])
    assert len(blocked) == 1


def test_sieve_script_set_is_blocked():
    blocked = enforce_policy([["SieveScript/set", {}, "c1"]])
    assert len(blocked) == 1


def test_vacation_response_set_is_blocked():
    blocked = enforce_policy([["VacationResponse/set", {}, "c1"]])
    assert len(blocked) == 1


# ── Email/set delete-equivalent checks ───────────────────────────────────────


def test_email_set_empty_mailbox_ids_is_blocked():
    blocked = enforce_policy([
        ["Email/set", {"update": {"m1": {"mailboxIds": {}}}}, "c1"]
    ])
    assert len(blocked) == 1
    assert "deletion" in blocked[0]["reason"].lower()


def test_email_set_null_mailbox_ids_is_blocked():
    blocked = enforce_policy([
        ["Email/set", {"update": {"m1": {"mailboxIds": None}}}, "c1"]
    ])
    assert len(blocked) == 1


def test_email_set_with_valid_mailbox_ids_is_allowed():
    blocked = enforce_policy([
        ["Email/set", {"update": {"m1": {"mailboxIds": {"mb1": True}}}}, "c1"]
    ])
    assert blocked == []


def test_email_set_keyword_update_is_allowed():
    blocked = enforce_policy([
        ["Email/set", {"update": {"m1": {"keywords/$seen": True}}}, "c1"]
    ])
    assert blocked == []


# ── Allowed methods ───────────────────────────────────────────────────────────


def test_mailbox_get_is_allowed():
    assert enforce_policy([["Mailbox/get", {"ids": None}, "c1"]]) == []


def test_email_query_is_allowed():
    assert enforce_policy([["Email/query", {"filter": {}}, "c1"]]) == []


def test_email_get_is_allowed():
    assert enforce_policy([["Email/get", {"ids": ["m1"]}, "c1"]]) == []


def test_thread_get_is_allowed():
    assert enforce_policy([["Thread/get", {"ids": ["t1"]}, "c1"]]) == []


# ── Multi-call batches ────────────────────────────────────────────────────────


def test_mixed_batch_returns_only_blocked_calls():
    calls = [
        ["Email/query", {"filter": {}}, "c1"],        # allowed
        ["Email/destroy", {"ids": ["m1"]}, "c2"],     # blocked
        ["Email/get", {"ids": ["m1"]}, "c3"],          # allowed
        ["EmailSubmission/set", {"create": {}}, "c4"], # blocked
    ]
    blocked = enforce_policy(calls)
    assert len(blocked) == 2
    blocked_ids = {b["callId"] for b in blocked}
    assert blocked_ids == {"c2", "c4"}


def test_all_allowed_batch_returns_empty():
    calls = [
        ["Mailbox/get", {}, "c1"],
        ["Email/query", {}, "c2"],
        ["Email/get", {}, "c3"],
    ]
    assert enforce_policy(calls) == []


def test_empty_batch_returns_empty():
    assert enforce_policy([]) == []
