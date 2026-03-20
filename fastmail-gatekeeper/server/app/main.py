import logging
import os
import random
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .auth import require_api_key
from .config import settings
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Eagerly validate credentials and cache JMAP session at startup."""
    if os.getenv("SKIP_STARTUP_VALIDATION"):
        logger.info("Startup credential validation skipped (SKIP_STARTUP_VALIDATION is set)")
        yield
        return

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
