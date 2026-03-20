"""
JMAP client for Fastmail.

Session info (apiUrl, accountId, primary identity) is fetched on first use and
cached for the lifetime of the process. Single-worker uvicorn makes this safe.
"""

import logging
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)

_session_cache: dict[str, Any] = {}

_JMAP_USING = [
    "urn:ietf:params:jmap:core",
    "urn:ietf:params:jmap:mail",
    "urn:ietf:params:jmap:submission",
]


async def get_session() -> dict[str, Any]:
    """
    Fetch and cache the JMAP session and primary sending identity.
    Safe to call repeatedly; result is cached after the first successful call.
    """
    if _session_cache.get("ready"):
        return _session_cache

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. JMAP session endpoint
        resp = await client.get(
            settings.fastmail_jmap_session_url,
            headers={"Authorization": f"Bearer {settings.fastmail_token}"},
        )
        resp.raise_for_status()
        data = resp.json()

        api_url: str = data["apiUrl"]
        primary_accounts: dict = data.get("primaryAccounts", {})
        account_id: str = primary_accounts["urn:ietf:params:jmap:mail"]
        submit_account_id: str = primary_accounts.get(
            "urn:ietf:params:jmap:submission", account_id
        )

        # 2. Discover the primary sending identity
        ir = await client.post(
            api_url,
            headers={
                "Authorization": f"Bearer {settings.fastmail_token}",
                "Content-Type": "application/json",
            },
            json={
                "using": _JMAP_USING,
                "methodCalls": [
                    [
                        "Identity/get",
                        {"accountId": submit_account_id, "ids": None},
                        "c1",
                    ]
                ],
            },
        )
        ir.raise_for_status()
        identities: list = ir.json()["methodResponses"][0][1].get("list", [])

        # The primary identity is typically the one that cannot be deleted.
        primary = next(
            (i for i in identities if i.get("mayDelete") is False),
            identities[0] if identities else None,
        )

    _session_cache.update(
        {
            "api_url": api_url,
            "account_id": account_id,
            "submit_account_id": submit_account_id,
            "from_email": primary["email"] if primary else None,
            "from_name": primary.get("name", "") if primary else "",
            "ready": True,
        }
    )
    return _session_cache


async def jmap_call(method_calls: list[list[Any]]) -> dict:
    """Send a raw JMAP request to Fastmail and return the full response dict."""
    session = await get_session()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            session["api_url"],
            headers={
                "Authorization": f"Bearer {settings.fastmail_token}",
                "Content-Type": "application/json",
            },
            json={
                "using": _JMAP_USING,
                "methodCalls": method_calls,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def move_to_folder(message_id: str, folder_id: str) -> None:
    """Move *message_id* into *folder_id* using Email/set (never Email/destroy)."""
    session = await get_session()
    result = await jmap_call(
        [
            [
                "Email/set",
                {
                    "accountId": session["account_id"],
                    "update": {message_id: {"mailboxIds": {folder_id: True}}},
                },
                "c1",
            ]
        ]
    )
    _raise_on_jmap_error(result, "c1")
    not_updated: dict = result["methodResponses"][0][1].get("notUpdated", {})
    if message_id in not_updated:
        raise RuntimeError(f"JMAP notUpdated: {not_updated[message_id]}")


async def create_draft(to: str, subject: str, body: str, pin: str) -> str:
    """
    Create a draft in ai_outgoing with the PIN stored as a JMAP keyword.
    Returns the new message ID.
    """
    session = await get_session()
    from_addr = (
        [{"email": session["from_email"], "name": session["from_name"]}]
        if session["from_email"]
        else []
    )

    result = await jmap_call(
        [
            [
                "Email/set",
                {
                    "accountId": session["account_id"],
                    "create": {
                        "draft1": {
                            "from": from_addr,
                            "to": [{"email": to}],
                            "subject": subject,
                            "keywords": {
                                f"ai-pin-{pin}": True,
                                "$draft": True,
                            },
                            "mailboxIds": {settings.ai_outgoing_id: True},
                            "bodyStructure": {
                                "type": "text/plain",
                                "partId": "body",
                            },
                            "bodyValues": {
                                "body": {
                                    "value": body,
                                    "charset": "utf-8",
                                }
                            },
                        }
                    },
                },
                "c1",
            ]
        ]
    )
    _raise_on_jmap_error(result, "c1")

    resp_args = result["methodResponses"][0][1]
    created = resp_args.get("created", {})
    if "draft1" not in created:
        not_created = resp_args.get("notCreated", {})
        raise RuntimeError(
            f"Draft creation failed: {not_created.get('draft1', resp_args)}"
        )
    return created["draft1"]["id"]


async def find_draft_by_pin(pin: str) -> str | None:
    """
    Search ai_outgoing for a draft whose keywords include ai-pin-{pin}.
    Returns the message ID, or None if not found.
    """
    session = await get_session()
    keyword = f"ai-pin-{pin}"

    result = await jmap_call(
        [
            [
                "Email/query",
                {
                    "accountId": session["account_id"],
                    "filter": {
                        "inMailbox": settings.ai_outgoing_id,
                        "hasKeyword": keyword,
                    },
                    "limit": 1,
                },
                "c1",
            ],
            [
                "Email/get",
                {
                    "accountId": session["account_id"],
                    "#ids": {
                        "resultOf": "c1",
                        "name": "Email/query",
                        "path": "/ids",
                    },
                    "properties": ["id"],
                },
                "c2",
            ],
        ]
    )

    by_id = {r[2]: r for r in result.get("methodResponses", [])}
    if "c2" not in by_id:
        return None
    emails: list = by_id["c2"][1].get("list", [])
    return emails[0]["id"] if emails else None


async def submit_email(message_id: str) -> None:
    """Submit a draft via EmailSubmission/set (actual send)."""
    session = await get_session()
    result = await jmap_call(
        [
            [
                "EmailSubmission/set",
                {
                    "accountId": session["submit_account_id"],
                    "create": {
                        "sub1": {
                            "emailId": message_id,
                            "envelope": None,  # derived from email From/To headers
                        }
                    },
                },
                "c1",
            ]
        ]
    )
    _raise_on_jmap_error(result, "c1")
    not_created: dict = result["methodResponses"][0][1].get("notCreated", {})
    if "sub1" in not_created:
        raise RuntimeError(f"Email submission failed: {not_created['sub1']}")


# ── Internal helpers ──────────────────────────────────────────────────────────


def _raise_on_jmap_error(result: dict, call_id: str) -> None:
    """Raise RuntimeError if the JMAP response for *call_id* is an error."""
    for method, args, cid in result.get("methodResponses", []):
        if cid == call_id and method == "error":
            raise RuntimeError(f"JMAP error ({args.get('type', 'unknown')}): {args}")
