"""Contracts for system-health endpoints."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response returned by the liveness endpoint."""

    status: str
