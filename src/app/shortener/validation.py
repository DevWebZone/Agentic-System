import re
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, status

SHORT_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
RESERVED_SHORT_CODES = {"api", "docs", "health", "openapi.json", "redoc", "favicon.ico"}


def normalize_destination_url(value: str) -> str:
    """Accept only absolute HTTP(S) destinations and return a normalized representation."""

    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("original_url must be an absolute HTTP or HTTPS URL.")
    if parsed.username or parsed.password:
        raise ValueError("original_url must not contain embedded credentials.")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, ""))


def validate_short_code(value: str) -> str:
    """Validate aliases and block collisions with application-owned routes."""

    candidate = value.strip()
    if not SHORT_CODE_PATTERN.fullmatch(candidate):
        raise ValueError(
            "custom_alias must contain 3-32 letters, numbers, hyphens, or underscores."
        )
    if candidate.lower() in RESERVED_SHORT_CODES:
        raise ValueError("custom_alias is reserved by the application.")
    return candidate


def require_future_expiration(expires_at: object) -> None:
    """Convert expiration validation into a client-safe HTTP response in the service layer."""

    from datetime import UTC, datetime

    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expires_at must be in the future.",
        )
