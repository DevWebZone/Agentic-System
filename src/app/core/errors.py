from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorResponse(BaseModel):
    """Consistent shape returned by application and HTTP errors."""

    error: str
    detail: Any
    request_id: str | None = None


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Translate framework HTTP errors into the public API error contract."""

    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error="http_error",
            detail=exc.detail,
            request_id=getattr(request.state, "request_id", None),
        ).model_dump(),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Avoid leaking internal exception details while retaining a correlation identifier."""

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_server_error",
            detail="An unexpected error occurred.",
            request_id=getattr(request.state, "request_id", None),
        ).model_dump(),
    )
