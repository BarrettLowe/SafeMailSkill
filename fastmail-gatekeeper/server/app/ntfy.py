import logging

import httpx

from .config import settings

logger = logging.getLogger(__name__)


async def send_ntfy_notification(to: str, pin: str) -> None:
    """POST a push notification to ntfy.sh. PIN is intentionally not logged."""
    url = f"https://ntfy.sh/{settings.ntfy_topic}"
    message = f"AI wants to send email to {to}. PIN: {pin}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                content=message.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        # Log only the exception type — never the message (contains the PIN).
        logger.error("ntfy notification failed (%s)", type(exc).__name__)
        raise
