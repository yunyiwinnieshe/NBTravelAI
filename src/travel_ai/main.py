"""FastAPI application entry point."""

from fastapi import FastAPI

from travel_ai.routers import health, recommendations, trip_sessions


def create_app() -> FastAPI:
    """Create the Travel AI HTTP application."""
    app = FastAPI(
        title="Travel AI API",
        version="0.1.0",
        description="An explainable service for fair two-traveler destination choices.",
    )

    app.include_router(health.router)
    app.include_router(recommendations.router)
    app.include_router(trip_sessions.router)

    return app


app = create_app()
