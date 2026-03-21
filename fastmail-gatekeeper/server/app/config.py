from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Fastmail (required — everything else depends on this)
    fastmail_token: str
    fastmail_jmap_session_url: str = "https://api.fastmail.com/jmap/session"

    # Mailbox IDs — validated at startup; missing values trigger the setup helper
    ai_trash_id: Optional[str] = None
    ai_outgoing_id: Optional[str] = None

    # ntfy.sh
    ntfy_topic: Optional[str] = None

    # Gatekeeper auth
    gatekeeper_api_key: Optional[str] = None


settings = Settings()


def check_startup_config(s: Settings) -> list[str]:
    """Return names of operator-configured env vars that are not yet set."""
    missing = []
    for var, val in [
        ("AI_TRASH_ID", s.ai_trash_id),
        ("AI_OUTGOING_ID", s.ai_outgoing_id),
        ("NTFY_TOPIC", s.ntfy_topic),
        ("GATEKEEPER_API_KEY", s.gatekeeper_api_key),
    ]:
        if not val:
            missing.append(var)
    return missing
