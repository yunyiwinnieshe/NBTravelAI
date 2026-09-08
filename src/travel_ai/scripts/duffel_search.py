"""Run one manual Duffel sandbox search and print normalized offers."""

import argparse
from datetime import date

from pydantic import TypeAdapter

from travel_ai.clients.duffel import DuffelClient, DuffelSettings
from travel_ai.providers.duffel import DuffelFlightOfferProvider
from travel_ai.schemas.flights import FlightOffer, FlightSearchQuery


def _airport_codes(value: str) -> list[str]:
    """Parse a comma-separated airport group for the smoke-test query."""
    return [code.strip().upper() for code in value.split(",") if code.strip()]


def parse_args() -> argparse.Namespace:
    """Parse the explicit inputs required for a sandbox offer request."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traveler-id", default="traveler_a")
    parser.add_argument("--origin-id", required=True)
    parser.add_argument("--destination-id", required=True)
    parser.add_argument("--origin-airports", required=True, type=_airport_codes)
    parser.add_argument("--destination-airports", required=True, type=_airport_codes)
    parser.add_argument("--departure-date", required=True, type=date.fromisoformat)
    parser.add_argument("--return-date", required=True, type=date.fromisoformat)
    return parser.parse_args()


def main() -> None:
    """Search Duffel test mode and emit only normalized, non-secret JSON."""
    args = parse_args()
    query = FlightSearchQuery(
        traveler_id=args.traveler_id,
        origin_id=args.origin_id,
        destination_id=args.destination_id,
        origin_airport_codes=args.origin_airports,
        destination_airport_codes=args.destination_airports,
        departure_date=args.departure_date,
        return_date=args.return_date,
    )

    with DuffelClient(DuffelSettings.from_environment()) as client:
        offers = DuffelFlightOfferProvider(client).search(query)

    output = TypeAdapter(list[FlightOffer]).dump_json(offers, indent=2)
    print(output.decode("utf-8"))


if __name__ == "__main__":
    main()
