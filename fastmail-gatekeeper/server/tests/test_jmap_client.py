"""Unit tests for jmap_client helpers."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_move_to_folder_succeeds_when_not_updated_is_null():
    """Regression: JMAP notUpdated=null must not raise TypeError."""
    null_response = {
        "methodResponses": [[
            "Email/set",
            {
                "accountId": "acct-1",
                "updated": {"msg-1": None},
                "notUpdated": None,  # Fastmail may return explicit null
            },
            "c1",
        ]]
    }
    mock_session = {"account_id": "acct-1", "api_url": "https://example.com", "ready": True}
    with (
        patch("app.jmap_client.get_session", new_callable=AsyncMock, return_value=mock_session),
        patch("app.jmap_client.jmap_call", new_callable=AsyncMock, return_value=null_response),
    ):
        from app.jmap_client import move_to_folder
        # Should not raise TypeError
        await move_to_folder("msg-1", "folder-id")


@pytest.mark.asyncio
async def test_move_to_folder_raises_on_not_updated():
    """JMAP notUpdated containing the message ID must raise RuntimeError."""
    not_updated_response = {
        "methodResponses": [[
            "Email/set",
            {
                "accountId": "acct-1",
                "notUpdated": {"msg-bad": {"type": "notFound", "description": "No such message"}},
            },
            "c1",
        ]]
    }
    mock_session = {"account_id": "acct-1", "api_url": "https://example.com", "ready": True}
    with (
        patch("app.jmap_client.get_session", new_callable=AsyncMock, return_value=mock_session),
        patch("app.jmap_client.jmap_call", new_callable=AsyncMock, return_value=not_updated_response),
    ):
        from app.jmap_client import move_to_folder
        with pytest.raises(RuntimeError, match="notUpdated"):
            await move_to_folder("msg-bad", "folder-id")
