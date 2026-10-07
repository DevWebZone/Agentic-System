from fastapi import APIRouter, status
from pydantic import BaseModel

from app.core.database import check_database_connection

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/live", response_model=HealthResponse, summary="Check process liveness")
def liveness() -> HealthResponse:
    """Return success if the API process can receive requests."""

    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse, summary="Check application readiness")
def readiness() -> HealthResponse:
    """Return success only when the configured database is available."""

    if not check_database_connection():
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        )
    return HealthResponse(status="ok")
