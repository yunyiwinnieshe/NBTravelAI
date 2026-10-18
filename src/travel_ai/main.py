"""FastAPI application entry point."""

import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from travel_ai.clients.duffel import DuffelConfigurationError, DuffelError
from travel_ai.routers import (
    activities,
    health,
    observability,
    recommendations,
    trip_sessions,
)
from travel_ai.services.deepseek_preference_extraction import (
    DeepSeekConfigurationError,
    DeepSeekExtractionError,
    DeepSeekResponseError,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate explicit configuration at startup; never silently fall back.
    trip_sessions.get_trip_session_service()
    try:
        yield
    finally:
        if trip_sessions.get_trip_session_service.cache_info().currsize:
            trip_sessions.get_trip_session_service().close()
            trip_sessions.get_trip_session_service.cache_clear()


def create_app() -> FastAPI:
    """Create the Travel AI HTTP application."""
    app = FastAPI(
        lifespan=lifespan,
        title="Travel AI API",
        version="0.1.0",
        description="An explainable service for fair two-traveler destination choices.",
    )

    @app.exception_handler(DeepSeekExtractionError)
    async def extraction_error(request: Request, error: DeepSeekExtractionError):
        configuration = isinstance(error, DeepSeekConfigurationError)
        invalid_output = isinstance(error, DeepSeekResponseError)
        return JSONResponse(
            status_code=503 if configuration or not invalid_output else 502,
            content={
                "detail": {
                    "code": "extraction_configuration"
                    if configuration
                    else (
                        "extraction_invalid_response"
                        if invalid_output
                        else "extraction_unavailable"
                    ),
                    "message": (
                        (
                            "Trip processing is not configured correctly. "
                            "Please contact support."
                        )
                        if configuration
                        else (
                            "We couldn't process your message. "
                            "Your saved trip is unchanged. "
                            "Please try again."
                        )
                    ),
                    "retryable": not configuration,
                }
            },
        )

    @app.exception_handler(DuffelError)
    async def duffel_error(request: Request, error: DuffelError):
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "origin_resolution_unavailable",
                    "message": (
                        "We couldn't verify the departure location. "
                        "Your saved trip is unchanged. Please try again."
                    ),
                    "retryable": not isinstance(error, DuffelConfigurationError),
                }
            },
        )

    @app.exception_handler(sqlite3.Error)
    async def origin_storage_error(request: Request, error: sqlite3.Error):
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "origin_storage_unavailable",
                    "message": (
                        "We couldn't save the departure location. "
                        "Your saved trip is unchanged. Please try again."
                    ),
                    "retryable": True,
                }
            },
        )

    app.include_router(health.router)
    app.include_router(recommendations.router)
    app.include_router(trip_sessions.router)
    app.include_router(activities.router)
    app.include_router(observability.router)

    return app


app = create_app()
