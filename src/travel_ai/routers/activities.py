"""Search illustrative activity fixtures for itinerary prototyping."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from travel_ai.services.activity_itinerary import (
    Activity,
    ActivitySearch,
    ItineraryDraft,
    ItineraryResult,
    run_itinerary_agent_loop,
    search_activities,
)

router = APIRouter(tags=["activities"])


@router.post("/activities/search", response_model=list[Activity])
def search(query: ActivitySearch) -> list[Activity]:
    return search_activities(query)


class PreviewRequest(BaseModel):
    search: ActivitySearch
    max_activity_spend_usd: int = Field(ge=0)


@router.post("/itineraries/preview", response_model=ItineraryResult)
def preview(request: PreviewRequest) -> ItineraryResult:
    """Run a fixture-only planner through the bounded verifier loop."""
    available = search_activities(request.search)
    if not available:
        return ItineraryResult(
            status="rejected",
            activity_ids=[],
            issues=["no_matching_activities"],
            attempts=0,
        )

    def fixture_planner(items: list[Activity], _issues: list[str]) -> ItineraryDraft:
        selected = [
            item.activity_id
            for item in items
            if item.price_usd <= request.max_activity_spend_usd
        ]
        return ItineraryDraft(activity_ids=selected[:8] or [items[0].activity_id])

    return run_itinerary_agent_loop(
        available, request.max_activity_spend_usd, fixture_planner
    )
