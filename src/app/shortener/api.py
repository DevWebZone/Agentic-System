import logging

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.shortener.models import Link
from app.shortener.repository import LinkRepository
from app.shortener.schemas import (
    AnalyticsDay,
    CreateLinkRequest,
    LinkAnalyticsResponse,
    LinkResponse,
    UpdateLinkRequest,
)
from app.shortener.service import LinkService

router = APIRouter(prefix="/api/v1/links", tags=["links"])
redirect_router = APIRouter(tags=["redirects"])
logger = logging.getLogger(__name__)


def get_link_service(session: Session = Depends(get_db_session)) -> LinkService:
    return LinkService(LinkRepository(session))


def to_link_response(link: Link, request: Request) -> LinkResponse:
    return LinkResponse(
        id=link.id,
        short_code=link.short_code,
        short_url=f"{request.base_url}{link.short_code}",
        original_url=link.original_url,
        is_enabled=link.is_enabled,
        created_at=link.created_at,
        updated_at=link.updated_at,
        expires_at=link.expires_at,
        last_accessed_at=link.last_accessed_at,
    )


@router.post("", response_model=LinkResponse, status_code=status.HTTP_201_CREATED)
def create_link(
    payload: CreateLinkRequest,
    request: Request,
    service: LinkService = Depends(get_link_service),
) -> LinkResponse:
    return to_link_response(service.create_link(payload), request)


@router.get("/{short_code}", response_model=LinkResponse)
def get_link(
    short_code: str,
    request: Request,
    service: LinkService = Depends(get_link_service),
) -> LinkResponse:
    return to_link_response(service.get_link(short_code), request)


@router.patch("/{short_code}", response_model=LinkResponse)
def update_link(
    short_code: str,
    payload: UpdateLinkRequest,
    request: Request,
    service: LinkService = Depends(get_link_service),
) -> LinkResponse:
    return to_link_response(service.update_link(short_code, payload), request)


@router.delete("/{short_code}", status_code=status.HTTP_204_NO_CONTENT)
def disable_link(short_code: str, service: LinkService = Depends(get_link_service)) -> Response:
    service.disable_link(short_code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{short_code}/analytics", response_model=LinkAnalyticsResponse)
def get_analytics(
    short_code: str, service: LinkService = Depends(get_link_service)
) -> LinkAnalyticsResponse:
    link, total_clicks, clicks_by_day = service.get_analytics(short_code)
    return LinkAnalyticsResponse(
        short_code=link.short_code,
        total_clicks=total_clicks,
        last_accessed_at=link.last_accessed_at,
        clicks_by_day=[AnalyticsDay(date=str(day), clicks=count) for day, count in clicks_by_day],
    )


@redirect_router.get("/{short_code}", include_in_schema=False)
def redirect_link(
    short_code: str,
    request: Request,
    service: LinkService = Depends(get_link_service),
) -> RedirectResponse:
    link = service.resolve_redirect(short_code)
    try:
        service.record_click(
            link, request.headers.get("referer"), request.headers.get("user-agent")
        )
    except Exception:
        logger.exception(
            "analytics_recording_failed", extra={"request_id": request.state.request_id}
        )
    return RedirectResponse(url=link.original_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
