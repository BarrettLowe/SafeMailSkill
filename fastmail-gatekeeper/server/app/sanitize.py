import re

from fastapi import HTTPException

_MAX_SUBJECT = 998   # RFC 5322 practical maximum
_MAX_BODY = 200_000  # 200 KB of plain text

# Control characters to strip: NUL–BS, VT, FF, SO–US, DEL.
# Keeps TAB (\x09), LF (\x0a), CR (\x0d) which are legitimate in plain text.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_subject(value: str) -> str:
    value = _CTRL_RE.sub("", value).strip()
    if not value:
        raise HTTPException(status_code=422, detail="subject cannot be empty")
    if len(value) > _MAX_SUBJECT:
        raise HTTPException(status_code=422, detail=f"subject exceeds {_MAX_SUBJECT} characters")
    return value


def sanitize_body(value: str) -> str:
    value = _CTRL_RE.sub("", value)
    if len(value) > _MAX_BODY:
        raise HTTPException(status_code=422, detail=f"body exceeds {_MAX_BODY} characters")
    return value
