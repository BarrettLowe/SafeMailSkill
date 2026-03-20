from typing import Any

# Methods that are unconditionally blocked regardless of arguments.
_BLOCKED_METHODS: frozenset[str] = frozenset(
    {
        # Permanent deletion
        "Email/destroy",
        "Mailbox/destroy",
        "Thread/destroy",
        # Sending must go through /v1/send + /v1/approve
        "EmailSubmission/set",
        # Modifying send-related account settings
        "Identity/set",
        "VacationResponse/set",
        "SieveScript/set",
        "SieveScript/validate",
    }
)


def _email_set_effectively_deletes(args: dict[str, Any]) -> bool:
    """Return True if this Email/set /update patch removes all mailboxes."""
    for patch in args.get("update", {}).values():
        if not isinstance(patch, dict):
            continue
        mailbox_ids = patch.get("mailboxIds")
        # Explicit replacement with empty dict  OR  null (JSON Merge Patch delete)
        if "mailboxIds" in patch and (mailbox_ids == {} or mailbox_ids is None):
            return True
    return False


def enforce_policy(method_calls: list) -> list[dict]:
    """
    Check a list of JMAP method calls against the safety policy.
    Returns a list of blocked-call descriptors; empty list means all are allowed.
    """
    blocked: list[dict] = []

    for call in method_calls:
        if not (isinstance(call, list) and len(call) >= 3):
            continue

        method: str = call[0]
        args: Any = call[1]
        call_id: str = call[2]

        if method in _BLOCKED_METHODS:
            blocked.append(
                {
                    "method": method,
                    "callId": call_id,
                    "reason": "Method not permitted by gatekeeper policy",
                }
            )
        elif (
            method == "Email/set"
            and isinstance(args, dict)
            and _email_set_effectively_deletes(args)
        ):
            blocked.append(
                {
                    "method": method,
                    "callId": call_id,
                    "reason": (
                        "Email/set with empty or null mailboxIds is equivalent "
                        "to deletion and is not permitted"
                    ),
                }
            )

    return blocked
