"""Notification backends for SafeMailSkill."""

import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)


def notify(subject: str, body: str, pin: str) -> None:
    """Send a HITL notification using the configured backend."""
    message = (
        f"SafeMailSkill – Pending Approval\n\n"
        f"To: (see draft in ai_outgoing)\n"
        f"Subject: {subject}\n\n"
        f"Body preview:\n{body[:300]}\n\n"
        f"PIN: {pin}\n\n"
        f"Reply /approve with this PIN within 1 hour to send."
    )

    if settings.notifier.lower() == "telegram":
        _telegram(message)
    else:
        _ntfy(subject, message, pin)


def _ntfy(subject: str, message: str, pin: str) -> None:
    if not settings.ntfy_topic:
        logger.warning("ntfy_topic not configured – skipping notification")
        return
    url = f"{settings.ntfy_server.rstrip('/')}/{settings.ntfy_topic}"
    try:
        resp = httpx.post(
            url,
            content=message.encode(),
            headers={
                "Title": f"[SafeMail] Approve: {subject}",
                "Tags": "email,robot",
                "Priority": "high",
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("ntfy notification sent to topic '%s'", settings.ntfy_topic)
    except httpx.HTTPError as exc:
        logger.error("Failed to send ntfy notification: %s", exc)


def _telegram(message: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning(
            "Telegram credentials not configured – skipping notification"
        )
        return
    url = (
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    )
    try:
        resp = httpx.post(
            url,
            json={"chat_id": settings.telegram_chat_id, "text": message},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Telegram notification sent to chat '%s'", settings.telegram_chat_id)
    except httpx.HTTPError as exc:
        logger.error("Failed to send Telegram notification: %s", exc)
