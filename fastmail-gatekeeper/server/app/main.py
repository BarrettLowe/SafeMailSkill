import logging
import os
import random
import sys
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .auth import require_api_key
from .config import check_startup_config, settings
from .jmap_client import (
    create_draft,
    find_draft_by_pin,
    get_session,
    jmap_call,
    move_to_folder,
    submit_email,
)
from .ntfy import send_ntfy_notification
from .policy import enforce_policy
from .sanitize import sanitize_body, sanitize_subject
from .schemas import ApproveRequest, DeleteRequest, JMAPProxyRequest, SendRequest

logger = logging.getLogger(__name__)

_SEP = "=" * 70


async def _print_mailbox_setup_help() -> None:
    """Fetch the user's Fastmail mailbox list and print setup instructions."""
    headers = {
        "Authorization": f"Bearer {settings.fastmail_token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(settings.fastmail_jmap_session_url, headers=headers)
            r.raise_for_status()
            session = r.json()
            api_url = session["apiUrl"]
            account_id = session["primaryAccounts"]["urn:ietf:params:jmap:mail"]

            r = await client.post(api_url, headers=headers, json={
                "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
                "methodCalls": [["Mailbox/get", {"accountId": account_id, "ids": None}, "c1"]],
            })
            r.raise_for_status()
            mailboxes: list = r.json()["methodResponses"][0][1]["list"]
            mailboxes.sort(key=lambda m: (m.get("role") or "z", m["name"].lower()))

        print(f"\n{_SEP}")
        print(" SETUP REQUIRED — AI_TRASH_ID or AI_OUTGOING_ID is not set")
        print(f"{_SEP}\n")
        print(f"  Account ID : {account_id}\n")
        print(f"  {'NAME':<35} {'ROLE':<15} ID")
        print(f"  {'-'*80}")
        for mb in mailboxes:
            role = mb.get("role") or ""
            note = "  ← AI_TRASH_ID?" if role == "trash" else ""
            print(f"  {mb['name']:<35} {role:<15} {mb['id']}{note}")
        print()
        print("  Create 'ai_trash' and 'ai_outgoing' folders in Fastmail if they")
        print("  don't exist, then set these in your .env file (or -e flags):\n")
        print("    AI_TRASH_ID=<id of your ai_trash mailbox>")
        print("    AI_OUTGOING_ID=<id of your ai_outgoing mailbox>")
        print(f"\n{_SEP}\n", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"\n{_SEP}")
        print(" SETUP REQUIRED — AI_TRASH_ID or AI_OUTGOING_ID is not set")
        print(f"{_SEP}\n")
        print(f"  Could not fetch mailbox list automatically: {exc}")
        print("  Run:  FASTMAIL_TOKEN=<token> python scripts/list_mailboxes.py")
        print("  Then set AI_TRASH_ID and AI_OUTGOING_ID in your .env file.")
        print(f"\n{_SEP}\n", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Eagerly validate credentials and cache JMAP session at startup."""
    if os.getenv("SKIP_STARTUP_VALIDATION"):
        logger.info("Startup credential validation skipped (SKIP_STARTUP_VALIDATION is set)")
        yield
        return

    # ── Check for missing operator config before hitting Fastmail ────────────
    missing = check_startup_config(settings)
    if "AI_TRASH_ID" in missing or "AI_OUTGOING_ID" in missing:
        await _print_mailbox_setup_help()
        sys.exit(0)
    if missing:
        for var in missing:
            logger.error("Required env var %s is not set — add it to your .env file.", var)
        sys.exit(1)

    try:
        session = await get_session()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Fastmail authentication failed (HTTP {exc.response.status_code}). "
            "Check FASTMAIL_TOKEN."
        ) from exc

    if not session.get("account_id"):
        raise RuntimeError(
            "Could not determine Fastmail mail account ID. Check FASTMAIL_TOKEN."
        )

    if not session.get("from_email"):
        logger.warning(
            "No Fastmail sending identity found — /v1/send and /v1/approve will fail."
        )

    yield


app = FastAPI(
    title="Fastmail Gatekeeper",
    version="1.0.0",
    description=(
        "Safe JMAP proxy for Fastmail. "
        "Enforces no-destroy policy and PIN-gated sending."
    ),
    lifespan=lifespan,
)


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}


# ── Side-effect endpoints (explicit safe actions) ─────────────────────────────


@app.post("/v1/delete", dependencies=[Depends(require_api_key)])
async def trash_email(req: DeleteRequest):
    """
    Move a message to ai_trash.
    This is the 'trash_email' action — it NEVER permanently deletes mail.
    """
    try:
        await move_to_folder(req.message_id, settings.ai_trash_id)
    except (httpx.HTTPStatusError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "success", "message": "Email moved to ai_trash"}


@app.post("/v1/send", dependencies=[Depends(require_api_key)])
async def send_email(req: SendRequest):
    """
    Create a pending draft in ai_outgoing and push a PIN notification via ntfy.
    The email is NOT sent until /v1/approve is called with the correct PIN.
    """
    subject = sanitize_subject(req.subject)
    body = sanitize_body(req.body)
    pin = f"{random.SystemRandom().randint(0, 9999):04d}"

    try:
        await create_draft(str(req.to), subject, body, pin)
        await send_ntfy_notification(str(req.to), pin)
    except (httpx.HTTPStatusError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {"status": "pending", "message": "Approval required. Check your mobile device."}


@app.post("/v1/approve", dependencies=[Depends(require_api_key)])
async def approve_email(req: ApproveRequest):
    """Find the draft with the given PIN keyword and submit it for delivery."""
    try:
        message_id = await find_draft_by_pin(req.pin)
    except (httpx.HTTPStatusError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if not message_id:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Invalid PIN"},
        )

    try:
        await submit_email(message_id)
    except (httpx.HTTPStatusError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {"status": "sent"}


# ── Generic JMAP proxy ────────────────────────────────────────────────────────


@app.post("/v1/jmap", dependencies=[Depends(require_api_key)])
async def jmap_proxy(req: JMAPProxyRequest):
    """
    Forward arbitrary JMAP method calls to Fastmail.

    **Blocked methods** (return 403):
    - Email/destroy, Mailbox/destroy, Thread/destroy
    - EmailSubmission/set  (use /v1/send + /v1/approve instead)
    - Identity/set, VacationResponse/set, SieveScript/set

    **Also blocked**: Email/set updates that set mailboxIds to {} or null
    (equivalent to deletion).

    The server automatically injects the correct accountId — callers do not
    need to know or supply it.
    """
    blocked = enforce_policy(req.methodCalls)
    if blocked:
        return JSONResponse(
            status_code=403,
            content={
                "status": "blocked",
                "reason": "One or more method calls are not permitted by gatekeeper policy",
                "blockedCalls": blocked,
            },
        )

    session = await get_session()
    account_id: str = session["account_id"]

    # Inject accountId into every method call that doesn't already supply one.
    enriched: list = []
    for call in req.methodCalls:
        method, args, call_id = call[0], dict(call[1]), call[2]
        if "accountId" not in args:
            args["accountId"] = account_id
        enriched.append([method, args, call_id])

    try:
        return await jmap_call(enriched)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Fastmail API error (HTTP {exc.response.status_code})",
        )
