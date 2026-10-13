"""Fixture-backed activity retrieval and bounded itinerary agent loop."""

import json
from collections.abc import Callable
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field


class Activity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activity_id: str
    city_id: str
    name: str
    neighborhood: str
    tags: list[str]
    open_weekdays: list[int]  # Monday=0; illustrative fixture schedule.
    duration_minutes: int = Field(gt=0)
    price_usd: int = Field(ge=0)
    source_url: str
    fixture_only: bool = True


class ActivitySearch(BaseModel):
    city_id: str
    weekday: int = Field(ge=0, le=6)
    tags: list[str] = Field(default_factory=list)
    neighborhood: str | None = None
    max_price_usd: int | None = Field(default=None, ge=0)


def search_activities(query: ActivitySearch) -> list[Activity]:
    """Filter a small catalog deterministically; no semantic claims or live hours."""
    catalog = json.loads(
        files("travel_ai").joinpath("fixtures/activities.json").read_text()
    )
    matches = []
    for item in catalog:
        activity = Activity.model_validate(item)
        if (
            activity.city_id != query.city_id
            or query.weekday not in activity.open_weekdays
        ):
            continue
        if query.tags and not set(query.tags).intersection(activity.tags):
            continue
        if (
            query.neighborhood
            and query.neighborhood.casefold() != activity.neighborhood.casefold()
        ):
            continue
        if query.max_price_usd is not None and activity.price_usd > query.max_price_usd:
            continue
        matches.append(activity)
    return sorted(matches, key=lambda item: item.activity_id)


class ItineraryDraft(BaseModel):
    activity_ids: list[str] = Field(min_length=1, max_length=8)


class ItineraryResult(BaseModel):
    status: str
    activity_ids: list[str]
    issues: list[str]
    attempts: int
    fixture_only: bool = True


def verify_itinerary(
    draft: ItineraryDraft, available: list[Activity], max_total_usd: int
) -> list[str]:
    """Reject unsupported IDs, duplicate visits, and excess activity spend."""
    by_id = {item.activity_id: item for item in available}
    issues = []
    if len(set(draft.activity_ids)) != len(draft.activity_ids):
        issues.append("duplicate_activity")
    if any(activity_id not in by_id for activity_id in draft.activity_ids):
        issues.append("unknown_or_unavailable_activity")
    if (
        sum(by_id[item].price_usd for item in set(draft.activity_ids) if item in by_id)
        > max_total_usd
    ):
        issues.append("activity_budget_exceeded")
    return issues


def run_itinerary_agent_loop(
    available: list[Activity],
    max_total_usd: int,
    draft_and_revise: Callable[[list[Activity], list[str]], ItineraryDraft],
    max_attempts: int = 3,
) -> ItineraryResult:
    """Ask a planner to draft/revise, then verify each result before returning it."""
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between 1 and 3")
    issues: list[str] = []
    for attempt in range(1, max_attempts + 1):
        draft = draft_and_revise(available, issues)
        issues = verify_itinerary(draft, available, max_total_usd)
        if not issues:
            return ItineraryResult(
                status="verified",
                activity_ids=draft.activity_ids,
                issues=[],
                attempts=attempt,
            )
    return ItineraryResult(
        status="rejected", activity_ids=[], issues=issues, attempts=max_attempts
    )
