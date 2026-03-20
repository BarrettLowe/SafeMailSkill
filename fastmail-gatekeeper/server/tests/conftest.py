"""
Set required environment variables before any app module is imported.
pytest loads conftest.py before collecting/importing test files, so this
runs first and pydantic-settings finds all variables in os.environ.
"""

import os

os.environ.setdefault("FASTMAIL_TOKEN", "test-token")
os.environ.setdefault("AI_TRASH_ID", "mailbox-trash-id")
os.environ.setdefault("AI_OUTGOING_ID", "mailbox-outgoing-id")
os.environ.setdefault("NTFY_TOPIC", "test-topic")
os.environ.setdefault("GATEKEEPER_API_KEY", "test-api-key-abc123xxx")
os.environ.setdefault("SKIP_STARTUP_VALIDATION", "1")
