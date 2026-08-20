"""FastAPI application entry point."""

from fastapi import FastAPI

from travel_ai.schemas import HealthResponse, RecommendationResponse, TripRequest


def create_app() -> FastAPI:
    """Create the Travel AI HTTP application."""
    app = FastAPI(
        title="Travel AI API",
        version="0.1.0",
        description="An explainable service for fair two-traveler destination choices.",
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health_check() -> HealthResponse:
        """Return a simple liveness response for local use and deployment checks."""
        return HealthResponse(status="ok")

    @app.post(
        "/recommendations",
        response_model=RecommendationResponse,
        tags=["recommendations"],
    )
    def create_recommendations(_trip_request: TripRequest) -> RecommendationResponse:
        """Validate a trip request until the deterministic ranking engine is ready."""
        return RecommendationResponse(
            status="not_implemented",
            recommendations=[],
            message=(
                "Trip request is valid. Deterministic destination ranking "
                "will be added in Week 2."
            ),
        )

    return app


app = create_app()
