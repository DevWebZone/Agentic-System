import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.errors import (
    ErrorResponse,
    http_exception_handler,
    unhandled_exception_handler,
)
from app.core.logging import configure_logging
from app.orchestration.api import metrics_router
from app.orchestration.api import router as workflows_router
from app.shortener.api import redirect_router
from app.shortener.api import router as links_router

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    description=(
        "Foundation API for a governed agentic software-engineering system and URL shortener."
    ),
)
app.include_router(health_router)
app.include_router(links_router)
app.include_router(redirect_router)
app.include_router(workflows_router)
app.include_router(metrics_router)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return validation failures through the standard API error contract."""

    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="validation_error",
            detail=jsonable_encoder(exc.errors()),
            request_id=getattr(request.state, "request_id", None),
        ).model_dump(),
    )


@app.middleware("http")
async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach a correlation ID and emit a structured request-completion log event."""

    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    started_at = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed",
        extra={"request_id": request_id},
    )
    logger.debug(
        "request_details method=%s path=%s status=%s duration_ms=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        extra={"request_id": request_id},
    )
    return response
