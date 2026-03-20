"""Unit tests for input sanitization helpers."""

import pytest
from fastapi import HTTPException

from app.sanitize import sanitize_body, sanitize_subject


# ── sanitize_subject ──────────────────────────────────────────────────────────


def test_subject_passes_through_normally():
    assert sanitize_subject("Hello world") == "Hello world"


def test_subject_strips_control_characters():
    assert sanitize_subject("Bad\x00chars\x07here") == "Badcharshere"


def test_subject_strips_leading_trailing_whitespace():
    assert sanitize_subject("  trimmed  ") == "trimmed"


def test_subject_raises_on_empty_after_strip():
    with pytest.raises(HTTPException) as exc_info:
        sanitize_subject("   ")
    assert exc_info.value.status_code == 422


def test_subject_raises_on_too_long():
    with pytest.raises(HTTPException) as exc_info:
        sanitize_subject("x" * 999)
    assert exc_info.value.status_code == 422


def test_subject_allows_unicode():
    assert sanitize_subject("Héllo wörld 🌍") == "Héllo wörld 🌍"


def test_subject_allows_tab_in_header():
    # TAB is legitimate in header folding
    result = sanitize_subject("subject\twith tab")
    assert "tab" in result


# ── sanitize_body ─────────────────────────────────────────────────────────────


def test_body_passes_through_normally():
    assert sanitize_body("Hello world") == "Hello world"


def test_body_strips_nul_bytes():
    assert sanitize_body("text\x00here") == "texthere"


def test_body_preserves_newlines():
    text = "line one\nline two\r\nline three"
    assert sanitize_body(text) == text


def test_body_preserves_tabs():
    text = "col1\tcol2"
    assert sanitize_body(text) == text


def test_body_raises_on_too_long():
    with pytest.raises(HTTPException) as exc_info:
        sanitize_body("x" * 200_001)
    assert exc_info.value.status_code == 422


def test_body_allows_empty_string():
    assert sanitize_body("") == ""
