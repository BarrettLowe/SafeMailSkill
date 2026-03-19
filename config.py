"""Configuration settings for SafeMailSkill."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Fastmail JMAP credentials
    fastmail_token: str
    fastmail_api_url: str = "https://api.fastmail.com/jmap/api/"
    fastmail_session_url: str = "https://api.fastmail.com/jmap/session"

    # Folder names used for HITL workflow
    ai_trash_folder: str = "ai_trash"
    ai_outgoing_folder: str = "ai_outgoing"

    # PIN expiry in seconds (default: 1 hour)
    pin_expiry_seconds: int = 3600

    # Notification settings
    # Choose "ntfy" or "telegram"
    notifier: str = "ntfy"

    # ntfy settings
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"

    # Telegram settings
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


settings = Settings()
