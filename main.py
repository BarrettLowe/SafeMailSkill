"""FastAPI application for SafeMailSkill.

Endpoints
---------
POST /v1/delete   – Shadow-delete an email (moves it to ai_trash).
POST /v1/send     – Stage a draft in ai_outgoing and notify the human.
POST /v1/approve  – Verify the PIN and send the staged draft.
GET  /health      – Health check.
"""

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, field_validator

from config import settings
from jmap_client import JMAPClient, JMAPError, generate_pin, _TS_KEYWORD_PREFIX
from notifier import notify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SafeMailSkill",
    description=(
        "An OpenClaw agent skill that provides safe, human-in-the-loop "
        "access to a Fastmail account via JMAP."
    ),
    version="1.0.0",
)

_jmap = JMAPClient()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class DeleteRequest(BaseModel):
    email_id: str


class DeleteResponse(BaseModel):
    status: str
    email_id: str


class SendRequest(BaseModel):
    to: EmailStr
    subject: str
    body: str


class SendResponse(BaseModel):
    status: str
    message: str


class ApproveRequest(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def pin_must_be_numeric(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("PIN must contain only digits")
        return v


class ApproveResponse(BaseModel):
    status: str
    message: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _extract_timestamp_from_keywords(keywords: dict) -> int | None:
    """Parse the creation timestamp embedded in keyword '$ai_ts_<epoch>'."""
    for kw in keywords:
        if kw.startswith(_TS_KEYWORD_PREFIX):
            try:
                return int(kw[len(_TS_KEYWORD_PREFIX):])
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/delete", response_model=DeleteResponse)
def delete_email(req: DeleteRequest) -> DeleteResponse:
    """Move an email to the *ai_trash* folder (shadow delete)."""
    logger.info("Shadow-deleting email %s", req.email_id)
    try:
        _jmap.shadow_delete(req.email_id)
    except JMAPError as exc:
        logger.error("shadow_delete failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return DeleteResponse(status="success", email_id=req.email_id)


@app.post("/v1/send", response_model=SendResponse)
def send_email(req: SendRequest) -> SendResponse:
    """Stage a draft in *ai_outgoing* and notify the human via PIN."""
    pin = generate_pin()
    logger.info("Staging draft to %s (subject: %s)", req.to, req.subject)
    try:
        _jmap.create_outgoing_draft(
            to=str(req.to),
            subject=req.subject,
            body=req.body,
            pin=pin,
        )
    except JMAPError as exc:
        logger.error("create_outgoing_draft failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    notify(subject=req.subject, body=req.body, pin=pin)

    return SendResponse(
        status="pending",
        message=(
            "Draft staged in ai_outgoing. "
            "Human review required. "
            "A PIN notification has been sent."
        ),
    )


@app.post("/v1/approve", response_model=ApproveResponse)
def approve_send(req: ApproveRequest) -> ApproveResponse:
    """Look up the draft matching *pin* and send it if it hasn't expired."""
    logger.info("Approval request with PIN %s", req.pin)
    try:
        draft = _jmap.find_draft_by_pin(req.pin)
    except JMAPError as exc:
        logger.error("find_draft_by_pin failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    if draft is None:
        raise HTTPException(
            status_code=404,
            detail="No pending draft found for that PIN. It may have already been sent or never existed.",
        )

    # Enforce expiry
    keywords: dict = draft.get("keywords", {})
    created_ts = _extract_timestamp_from_keywords(keywords)
    if created_ts is not None:
        age_seconds = int(datetime.now(timezone.utc).timestamp()) - created_ts
        if age_seconds > settings.pin_expiry_seconds:
            # Clean up the expired draft
            try:
                _jmap._delete_email(draft["id"])
            except JMAPError:
                pass
            raise HTTPException(
                status_code=410,
                detail=(
                    f"PIN expired. Draft was created {age_seconds // 60} minutes ago "
                    f"(limit: {settings.pin_expiry_seconds // 60} minutes). "
                    "The draft has been removed."
                ),
            )

    try:
        _jmap.send_draft(draft["id"])
    except JMAPError as exc:
        logger.error("send_draft failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return ApproveResponse(
        status="success",
        message="Email sent successfully.",
    )
