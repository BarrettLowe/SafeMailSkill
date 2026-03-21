"""
Config startup validation tests.

- FASTMAIL_TOKEN is required by pydantic (Settings() raises ValidationError).
- AI_TRASH_ID, AI_OUTGOING_ID, NTFY_TOPIC, GATEKEEPER_API_KEY are validated by
  check_startup_config() so that the container can print a helpful setup guide
  rather than crashing with a raw pydantic traceback.
"""

import importlib
import os

import pytest
from pydantic import ValidationError


def test_settings_requires_fastmail_token(monkeypatch):
    """FASTMAIL_TOKEN is the only field enforced at model level (module-level Settings() call)."""
    monkeypatch.delenv("FASTMAIL_TOKEN", raising=False)
    import app.config as config_module
    # reload() re-executes `settings = Settings()` at module level, which raises
    with pytest.raises(ValidationError) as exc_info:
        importlib.reload(config_module)
    assert "fastmail_token" in str(exc_info.value).lower()


@pytest.mark.parametrize("missing_var", [
    "AI_TRASH_ID",
    "AI_OUTGOING_ID",
    "NTFY_TOPIC",
    "GATEKEEPER_API_KEY",
])
def test_check_startup_config_detects_missing_var(missing_var, monkeypatch):
    """check_startup_config() must report every operator var that is absent."""
    monkeypatch.delenv(missing_var, raising=False)
    import app.config as config_module
    importlib.reload(config_module)
    s = config_module.Settings()
    missing = config_module.check_startup_config(s)
    assert missing_var in missing, f"Expected {missing_var} in {missing}"


def test_check_startup_config_passes_when_all_set():
    """check_startup_config() returns an empty list when all vars are present."""
    import app.config as config_module
    importlib.reload(config_module)
    s = config_module.Settings()
    assert config_module.check_startup_config(s) == []
