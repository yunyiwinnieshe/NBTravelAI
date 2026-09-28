"""Opt-in live extraction smoke test; never invoked by pytest or app startup."""

import argparse
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from travel_ai.schemas.sessions import TravelerPreferencesDraft, TripRequestDraft
from travel_ai.schemas.trip import TripPreferences
from travel_ai.services.deepseek_preference_extraction import (
    DeepSeekExtractionError,
    DeepSeekPreferenceExtractor,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly allow paid requests to DeepSeek with synthetic trip messages",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("pass --live to opt in to real DeepSeek requests")
    today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    start = today + timedelta(days=14)
    current = TripRequestDraft(
        travelers=[
            TravelerPreferencesDraft(
                traveler_id="traveler_a",
                display_name="Winnie",
                origin="Boston, MA",
                budget_usd=1000,
                max_travel_time_hours=8,
                preferences=TripPreferences(
                    interest_tags=["museums"],
                    temperature_range={"minimum_celsius": 15, "maximum_celsius": 23},
                ),
            ),
            TravelerPreferencesDraft(
                traveler_id="traveler_b",
                display_name="Ivy",
                origin="New York, NY",
                budget_usd=900,
                max_travel_time_hours=7,
            ),
        ],
        start_date=start,
        end_date=start + timedelta(days=4),
    )
    friday = today + timedelta(days=(4 - today.weekday()) % 7 or 7)
    cases = [
        (
            "I have an $800 USD round-trip airfare budget.",
            {"travelers.traveler_a.budget_usd": 800},
        ),
        (
            "My round-trip airfare budget is $650 USD.",
            {"travelers.traveler_a.budget_usd": 650},
        ),
        (
            "Winnie's round-trip airfare budget is $750 USD.",
            {"travelers.traveler_a.budget_usd": 750},
        ),
        (
            "Ivy's round-trip airfare budget is $850 USD.",
            {"travelers.traveler_b.budget_usd": 850},
        ),
        (
            "We both have a round-trip airfare budget of $800 USD each.",
            {
                "travelers.traveler_a.budget_usd": 800,
                "travelers.traveler_b.budget_usd": 800,
            },
        ),
        (
            "I also like beaches.",
            {"travelers.traveler_a.preferences.interest_tags": ["museums", "beach"]},
        ),
        (
            "Actually, I only want beaches.",
            {"travelers.traveler_a.preferences.interest_tags": ["beach"]},
        ),
        (
            "Remove museums from my interests. I don't care about temperature anymore.",
            {
                "travelers.traveler_a.preferences.interest_tags": [],
                "travelers.traveler_a.preferences.temperature_range": None,
            },
        ),
        (
            "We leave next Friday and return three days later.",
            {
                "start_date": friday.isoformat(),
                "end_date": (friday + timedelta(days=3)).isoformat(),
            },
        ),
        (
            "I have $800 USD for round-trip airfare and want a hotel with a pool.",
            {"travelers.traveler_a.budget_usd": 800},
        ),
        ("I want somewhere romantic.", {}),
        (
            "I like great restaurants and clubbing instead of museums.",
            {"travelers.traveler_a.preferences.interest_tags": ["food", "nightlife"]},
        ),
        (
            "I prefer warm weather.",
            {
                "travelers.traveler_a.preferences.temperature_range": {
                    "minimum_celsius": 20,
                    "maximum_celsius": 30,
                }
            },
        ),
    ]
    failures = 0
    try:
        with DeepSeekPreferenceExtractor(today=lambda: today) as extractor:
            for message, expected in cases:
                print(f"\nMessage: {message}")
                try:
                    result = extractor.extract(message, current)
                except DeepSeekExtractionError as error:
                    print(f"FAIL: {error}")
                    failures += 1
                    continue
                sparse = result.draft.model_dump(mode="json", exclude_unset=True)
                print(
                    json.dumps(
                        {
                            **result.model_dump(mode="json"),
                            "draft": sparse,
                        },
                        indent=2,
                    )
                )
                actual = {k: v for k, v in sparse.items() if k != "travelers"}
                for traveler in sparse["travelers"]:
                    prefix = f"travelers.{traveler['traveler_id']}."
                    for key, value in traveler.items():
                        if key == "preferences":
                            actual.update(
                                {
                                    prefix + "preferences." + k: v
                                    for k, v in value.items()
                                }
                            )
                        elif key != "traveler_id":
                            actual[prefix + key] = value

                # Interest order is immaterial; all other values are exact.
                def comparable(mapping):
                    return {
                        k: sorted(v) if k.endswith("interest_tags") else v
                        for k, v in mapping.items()
                    }

                passed = comparable(actual) == comparable(expected)
                if "hotel" in message:
                    passed = passed and bool(result.unsupported_requests)
                if "romantic" in message:
                    passed = passed and result.status == "needs_clarification"
                print("PASS" if passed else f"FAIL: expected updates {expected}")
                failures += int(not passed)
    except DeepSeekExtractionError as error:
        print(f"Configuration failed: {error}")
        return 1
    print(f"\n{len(cases) - failures}/{len(cases)} cases passed.")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
