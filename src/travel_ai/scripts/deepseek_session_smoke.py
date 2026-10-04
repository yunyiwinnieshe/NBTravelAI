"""Opt-in walkthrough against a locally running DeepSeek-configured session API."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("pass --live to opt in to real model requests through the server")
    if args.output.exists():
        parser.error("choose a new output path; existing reports are not overwritten")
    records = []
    failures = []
    started = datetime.now(UTC).isoformat()
    with httpx.Client(base_url=args.base_url, timeout=40) as client:

        def post(path, payload, expected_status=200, state=None):
            response = client.post(path, json=payload)
            body = response.json()
            passed = response.status_code == expected_status and (
                state is None or body.get("state") == state
            )
            records.append(
                {
                    "path": path,
                    "request": payload,
                    "status": response.status_code,
                    "response": body,
                    "passed": passed,
                }
            )
            print(
                f"{'PASS' if passed else 'FAIL'} {path}: "
                f"{response.status_code} {body.get('state')}",
                flush=True,
            )
            if not passed:
                failures.append(len(records))
            return body

        first = post(
            "/trip-sessions",
            {
                "initial_message": (
                    "My name is Alex and I'm leaving from Boston. "
                    "My companion Jamie leaves "
                    "from New York. We travel June 10 to June 14, 2099. "
                    "Jamie's maximum "
                    "round-trip airfare budget is $500 USD. "
                    "Each of us can travel at most "
                    "10 hours one way including layovers."
                )
            },
            state="collecting",
        )
        if "session_id" in first:
            url = f"/trip-sessions/{first['session_id']}/messages"
            filled = post(url, {"message": "800"}, state="review")
            if (
                filled.get("trip_request_draft", {})
                .get("travelers", [{}])[0]
                .get("budget_usd")
                != 800
            ):
                failures.append("short_answer_budget")
            post(url, {"message": "I also like hiking."}, state="review")
            post(
                url,
                {
                    "message": (
                        "My round-trip airfare budget is $600 USD, "
                        "and I want a hotel with a pool."
                    )
                },
                state="collecting",
            )
            post(url, {"action": "confirm"}, expected_status=422)
            reviewed = post(
                url,
                {"message": "Yes, continue without the hotel request."},
                state="review",
            )
            if (
                reviewed.get("trip_request_draft", {})
                .get("travelers", [{}])[0]
                .get("budget_usd")
                != 600
            ):
                failures.append("correction_budget")
            if not reviewed.get("deferred_requests"):
                failures.append("missing_deferred_notice")
            post(url, {"action": "confirm"}, state="results")
            post(
                url,
                {
                    "message": (
                        "We each now have a maximum round-trip "
                        "airfare budget of $1 USD."
                    )
                },
                state="review",
            )
            post(url, {"action": "confirm"}, state="no_match")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "started_at_utc": started,
                "finished_at_utc": datetime.now(UTC).isoformat(),
                "scope": (
                    "Real HTTP session API + configured DeepSeek "
                    "+ deterministic fixture recommendations"
                ),
                "passed": not failures,
                "failures": failures,
                "records": records,
            },
            indent=2,
        )
        + "\n"
    )
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
