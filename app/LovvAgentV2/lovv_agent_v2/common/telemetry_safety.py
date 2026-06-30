from __future__ import annotations

import re
from typing import Final

_AWS_ACCESS_KEY_RE: Final = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_EMAIL_RE: Final = re.compile(r"\b[^@\s]+@[^@\s]+\.[^@\s]+\b")
_PHONE_RE: Final = re.compile(r"\b(?:\+?\d[\d .-]{7,}\d)\b")
_SECRET_PAIR_RE: Final = re.compile(
    r"(?i)\b(?:aws_secret_access_key|aws_session_token|api[_-]?key|secret)"
    r"\b\s*[:=]\s*[^\s,;]+",
)


def sanitize_text(value: str) -> str:
    redacted = _AWS_ACCESS_KEY_RE.sub("[REDACTED_AWS_ACCESS_KEY]", value)
    redacted = _SECRET_PAIR_RE.sub("[REDACTED_SECRET]", redacted)
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", redacted)
    return _PHONE_RE.sub("[REDACTED_PHONE]", redacted)


__all__ = ["sanitize_text"]
