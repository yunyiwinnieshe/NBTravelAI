"""System-health HTTP routes."""

from fastapi import APIRouter

from travel_ai.schemas.health import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return a simple liveness response for local use and deployment checks."""
    return HealthResponse(status="ok")
