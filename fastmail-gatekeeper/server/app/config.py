from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Fastmail
    fastmail_token: str
    fastmail_jmap_session_url: str = "https://api.fastmail.com/jmap/session"

    # Mailbox IDs (discover with scripts/list_mailboxes.py)
    ai_trash_id: str
    ai_outgoing_id: str

    # ntfy.sh
    ntfy_topic: str

    # Gatekeeper auth
    gatekeeper_api_key: str


settings = Settings()
