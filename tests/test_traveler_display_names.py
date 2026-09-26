"""Optional conversational names never replace stable traveler identity."""

import pytest
from pydantic import ValidationError

from travel_ai.routers.trip_sessions import get_trip_session_service
from travel_ai.schemas.sessions import TravelerPreferencesDraft
from travel_ai.services.preference_extraction import FixturePreferenceExtractor


def test_optional_name_and_fallback() -> None:
    traveler = TravelerPreferencesDraft(traveler_id="traveler_a")
    assert traveler.display_name is None
    assert traveler.display_label == "Traveler A"
    traveler = TravelerPreferencesDraft(traveler_id="traveler_b", display_name=" Ivy ")
    assert traveler.display_name == "Ivy"
    assert traveler.display_label == "Ivy"


@pytest.mark.parametrize("name", ["", "   ", "a" * 51])
def test_invalid_name(name: str) -> None:
    with pytest.raises(ValidationError):
        TravelerPreferencesDraft(traveler_id="traveler_a", display_name=name)


def test_names_can_change_or_be_omitted_without_affecting_ranking_request() -> None:
    get_trip_session_service.cache_clear()
    service = get_trip_session_service()
    session = service.create_session(None)
    assert [t.traveler_id for t in session.trip_request_draft.travelers] == [
        "traveler_a",
        "traveler_b",
    ]
    message = (
        "We will travel June 10 to June 14, 2099. Alice and Bob each have a $500 "
        "budget and can travel up to 10 hours."
    )
    result = service.extractor.extract(message, session.trip_request_draft)
    original = service._build_trip_request(result.draft)
    for name in ["Winnie", "Same name", None]:
        for traveler in result.draft.travelers:
            traveler.display_name = name
        service.extractor = FixturePreferenceExtractor({"rename": result})
        updated = service.add_message(session.session_id, "rename")
        assert service._build_trip_request(updated.trip_request_draft) == original
        assert "display_name" not in original.travelers[0].model_dump()
    assert service.confirm_session(session.session_id).state == "results"
    get_trip_session_service.cache_clear()


@pytest.mark.parametrize(
    "ids", [["new_id", "traveler_b"], ["traveler_a", "traveler_a"], []]
)
def test_extractor_cannot_replace_assigned_ids(ids: list[str]) -> None:
    get_trip_session_service.cache_clear()
    service = get_trip_session_service()
    session = service.create_session(None)
    result = service.extractor.extract(
        "Alice is leaving from Boston and Bob is leaving from New York.",
        session.trip_request_draft,
    )
    result.draft.travelers = [TravelerPreferencesDraft(traveler_id=id_) for id_ in ids]
    service.extractor = FixturePreferenceExtractor({"invalid": result})
    with pytest.raises(ValueError, match="preserve the two assigned traveler IDs"):
        service.add_message(session.session_id, "invalid")
    assert service._sessions[session.session_id].draft == session.trip_request_draft
    get_trip_session_service.cache_clear()
