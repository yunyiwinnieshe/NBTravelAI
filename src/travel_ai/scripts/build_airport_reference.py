"""Generate the V1 U.S. commercial-airport reference from OurAirports CSV."""

import argparse
import csv
import json
from datetime import date
from pathlib import Path

SOURCE_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
SUPPORTED_TYPES = {"large_airport", "medium_airport"}
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent / "fixtures" / "airport_reference.json"
)


def build_reference(input_path: Path, source_date: date) -> dict[str, object]:
    """Filter the public CSV into the small contract used by Travel AI."""
    with input_path.open(encoding="utf-8", newline="") as input_file:
        rows = [
            {
                "iata_code": row["iata_code"],
                "airport_type": row["type"],
                "scheduled_service": True,
            }
            for row in csv.DictReader(input_file)
            if row["iso_country"] == "US"
            and row["scheduled_service"] == "yes"
            and row["type"] in SUPPORTED_TYPES
            and len(row["iata_code"]) == 3
        ]
    rows.sort(key=lambda row: str(row["iata_code"]))
    return {
        "schema_version": "v1",
        "source": "OurAirports",
        "source_url": SOURCE_URL,
        "source_date": source_date.isoformat(),
        "airports": rows,
    }


def main() -> None:
    """Parse arguments and write deterministic formatted JSON."""
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--source-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data = build_reference(args.input_csv, args.source_date)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
