"""Run an opt-in live Duffel Places origin-resolution smoke check."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from travel_ai.clients.duffel import DuffelClient, DuffelSettings
from travel_ai.providers.duffel import DuffelAirportPlaceProvider
from travel_ai.services.live_origin_resolution import (
    DuffelOriginResolver,
    OriginResolutionError,
    SQLiteLocationStore,
)


def main() -> None:
    """Verify live city, airport, ambiguity, and stable-ID behavior in test mode."""
    with TemporaryDirectory(prefix="travelai-origin-smoke-") as directory:
        store = SQLiteLocationStore(Path(directory) / "locations.sqlite3")
        with DuffelClient(DuffelSettings.from_environment()) as client:
            resolver = DuffelOriginResolver(DuffelAirportPlaceProvider(client), store)
            city_id = resolver.resolve("Portland, OR")
            city_airports = store.get_airports(city_id)
            assert city_airports and "PDX" in city_airports
            assert len(city_airports) <= 3
            assert resolver.resolve("Portland, Oregon") == city_id

            airport_id = resolver.resolve("PDX")
            assert store.get_airports(airport_id) == ["PDX"]

            try:
                resolver.resolve("Portland")
            except OriginResolutionError:
                pass
            else:
                raise AssertionError(
                    "Portland without a state should need clarification"
                )

            print(
                json.dumps(
                    {
                        "status": "passed",
                        "city_airports": city_airports,
                        "explicit_airport": "PDX",
                        "stable_location_id": True,
                        "ambiguous_city_clarified": True,
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
