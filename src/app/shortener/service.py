from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.shortener.code_generator import generate_short_code
from app.shortener.models import Link
from app.shortener.repository import LinkRepository
from app.shortener.schemas import CreateLinkRequest, UpdateLinkRequest
from app.shortener.validation import require_future_expiration

MAX_CODE_GENERATION_ATTEMPTS = 5


class LinkService:
    """Business rules for URL-shortening operations."""

    def __init__(self, repository: LinkRepository) -> None:
        self.repository = repository

    def create_link(self, request: CreateLinkRequest) -> Link:
        require_future_expiration(request.expires_at)
        if request.custom_alias:
            if self.repository.get_by_code(request.custom_alias):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Short code already exists.",
                )
            return self._persist_link(request, request.custom_alias)

        for _ in range(MAX_CODE_GENERATION_ATTEMPTS):
            short_code = generate_short_code()
            if not self.repository.get_by_code(short_code):
                return self._persist_link(request, short_code)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to allocate a unique short code. Please retry.",
        )

    def get_link(self, short_code: str) -> Link:
        link = self.repository.get_by_code(short_code)
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Short link was not found.",
            )
        return link

    def update_link(self, short_code: str, request: UpdateLinkRequest) -> Link:
        link = self.get_link(short_code)
        if request.expires_at is not None:
            require_future_expiration(request.expires_at)
            link.expires_at = request.expires_at
        if request.original_url is not None:
            link.original_url = request.original_url
        if request.is_enabled is not None:
            link.is_enabled = request.is_enabled
        self.repository.session.commit()
        self.repository.session.refresh(link)
        return link

    def disable_link(self, short_code: str) -> Link:
        return self.update_link(short_code, UpdateLinkRequest(is_enabled=False))

    def resolve_redirect(self, short_code: str) -> Link:
        link = self.get_link(short_code)
        if not link.is_enabled:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Short link is disabled.")
        if link.expires_at and self._as_utc(link.expires_at) <= datetime.now(UTC):
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Short link has expired.")
        return link

    def record_click(self, link: Link, referrer: str | None, user_agent: str | None) -> None:
        """Record analytics independently so callers can intentionally degrade gracefully."""

        self.repository.add_click_event(link, referrer, user_agent)
        self.repository.session.commit()

    def get_analytics(self, short_code: str) -> tuple[Link, int, list[tuple[str, int]]]:
        link = self.get_link(short_code)
        total_clicks = self.repository.click_count(link.id)
        clicks_by_day = list(self.repository.analytics_by_day(link.id))
        return link, total_clicks, clicks_by_day

    def _persist_link(self, request: CreateLinkRequest, short_code: str) -> Link:
        link = Link(
            short_code=short_code,
            original_url=request.original_url,
            expires_at=request.expires_at,
        )
        try:
            saved_link = self.repository.add_link(link)
            self.repository.session.commit()
            return saved_link
        except IntegrityError as exc:
            self.repository.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Short code already exists.",
            ) from exc

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        """Normalize SQLite's timezone-naive values before comparing them to UTC timestamps."""

        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
