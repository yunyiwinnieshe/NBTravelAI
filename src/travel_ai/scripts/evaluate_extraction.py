"""Versioned, opt-in live adapter evaluation; does not wire planning sessions."""

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import time
from collections import Counter
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx

from travel_ai.evaluation.transports import LimitedTransport
from travel_ai.schemas.sessions import TripRequestDraft
from travel_ai.services import deepseek_preference_extraction as adapter
from travel_ai.services.preference_extraction import PreferenceExtractor


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sparse_values(draft: TripRequestDraft) -> dict[str, Any]:
    """Expose all explicitly returned fields, including unexpected metadata edits."""
    data = draft.model_dump(mode="json", exclude_unset=True)
    values = {key: value for key, value in data.items() if key != "travelers"}
    for traveler in data.get("travelers", []):
        prefix = f"travelers.{traveler['traveler_id']}."
        for key, value in traveler.items():
            if key == "preferences":
                values.update({prefix + key + "." + k: v for k, v in value.items()})
            elif key != "traveler_id":
                values[prefix + key] = value
    return values


def comparable(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: sorted(value) if key.endswith("interest_tags") else value
        for key, value in values.items()
    }


def merge_for_evaluation(
    draft: TripRequestDraft, updates: dict[str, Any]
) -> TripRequestDraft:
    """Test-only sparse merge; no persistence, origin resolver, or session logic."""
    data = draft.model_dump(mode="json")
    travelers = {t["traveler_id"]: t for t in data["travelers"]}
    for path, value in updates.items():
        if path in ("start_date", "end_date"):
            data[path] = value
        else:
            _, traveler_id, *parts = path.split(".")
            target = travelers[traveler_id]
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
    return TripRequestDraft.model_validate(data)


def evaluate(
    extractor: PreferenceExtractor,
    dataset: dict[str, Any],
    *,
    repeats: int = 1,
    provider_trace: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Grade complete updates and cumulative state; retain failures, never retry."""
    records = []
    for repeat in range(1, repeats + 1):
        for scenario in dataset["scenarios"]:
            draft = TripRequestDraft.model_validate(
                scenario.get("initial_draft", dataset["initial_draft"])
            )
            expected_draft = draft.model_copy(deep=True)
            for turn in scenario["turns"]:
                before = draft.model_dump(mode="json")
                expected_draft = merge_for_evaluation(
                    expected_draft, turn["expected_updates"]
                )
                record = {
                    "case_id": scenario["id"] + "/" + turn["id"],
                    "category": scenario["category"],
                    "repeat": repeat,
                    "message": turn["message"],
                    "input_draft": before,
                    "expected": turn,
                    "expected_draft_after": expected_draft.model_dump(mode="json"),
                }
                if provider_trace is not None:
                    provider_trace.clear()
                started = time.perf_counter()
                checks = {}
                try:
                    result = extractor.extract(turn["message"], draft)
                    actual = sparse_values(result.draft)
                    checks["exact_updates"] = comparable(actual) == comparable(
                        turn["expected_updates"]
                    )
                    checks["status"] = result.status == turn["expected_status"]
                    checks["required_issues"] = all(
                        any(
                            issue.field_path in expected["paths"]
                            and issue.reason in expected["reasons"]
                            for issue in result.missing_fields
                        )
                        for expected in turn["required_issues"]
                    )
                    expected_notice = turn["expected_unsupported"]
                    checks["unsupported_notice"] = (
                        expected_notice is None
                        or bool(result.unsupported_requests) == expected_notice
                    )
                    checks["traveler_ids"] = sorted(
                        t.traveler_id for t in result.draft.travelers
                    ) == sorted(t["traveler_id"] for t in before["travelers"])
                    checks["input_unchanged"] = draft.model_dump(mode="json") == before
                    draft = merge_for_evaluation(draft, actual)
                    checks["cumulative_state"] = comparable(sparse_values(draft)) == (
                        comparable(sparse_values(expected_draft))
                    )
                    record["actual_updates"] = actual
                    record["result"] = {
                        **result.model_dump(mode="json"),
                        "draft": result.draft.model_dump(
                            mode="json", exclude_unset=True
                        ),
                    }
                except adapter.DeepSeekExtractionError as error:
                    record["error"] = {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
                    checks["provider_success"] = False
                    checks["input_unchanged"] = draft.model_dump(mode="json") == before
                record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
                record["checks"] = checks
                record["passed"] = all(checks.values())
                record["draft_after"] = draft.model_dump(mode="json")
                if provider_trace is not None:
                    record["provider"] = dict(provider_trace)
                records.append(record)
                print(
                    f"{'PASS' if record['passed'] else 'FAIL'} "
                    f"r{repeat} {record['case_id']} "
                    f"{record['latency_ms']}ms "
                    f"{[k for k, v in checks.items() if not v]}",
                    flush=True,
                )
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    categories = {}
    for category in sorted({r["category"] for r in records}):
        selected = [r for r in records if r["category"] == category]
        categories[category] = {
            "passed": sum(r["passed"] for r in selected),
            "total": len(selected),
        }
    case_ids = {r["case_id"] for r in records}
    passed = sum(r["passed"] for r in records)
    latencies = [r["latency_ms"] for r in records]
    return {
        "passed": passed,
        "total": len(records),
        "pass_rate": passed / len(records),
        "cases_passing_all_repeats": sum(
            all(r["passed"] for r in records if r["case_id"] == case_id)
            for case_id in case_ids
        ),
        "unique_cases": len(case_ids),
        "categories": categories,
        "failure_checks": dict(
            Counter(
                key for r in records for key, value in r["checks"].items() if not value
            )
        ),
        "median_latency_ms": statistics.median(latencies),
        "max_latency_ms": max(latencies),
        "provider_errors": sum("error" in r for r in records),
    }


def compare_reports(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Reject incomparable datasets/graders; show changed cases, not just averages."""
    for key in ("dataset_sha256", "evaluator_sha256", "repeats"):
        if old["metadata"][key] != new["metadata"][key]:
            raise ValueError(f"Cannot compare reports with different {key}")

    def states(report):
        return {(r["case_id"], r["repeat"]): r["passed"] for r in report["records"]}

    before, after = states(old), states(new)
    if before.keys() != after.keys():
        raise ValueError("Reports have different case/repeat keys")
    return {
        "pass_rate_change_percentage_points": round(
            100 * (new["summary"]["pass_rate"] - old["summary"]["pass_rate"]), 2
        ),
        "improved": [list(k) for k in before if not before[k] and after[k]],
        "regressed": [list(k) for k in before if before[k] and not after[k]],
        "still_failing": [list(k) for k in before if not before[k] and not after[k]],
    }


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/preference_extraction/cases.v1.json"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--compare", type=Path, help="Compare against this saved run")
    parser.add_argument(
        "--candidate", type=Path, help="Compare saved runs without API calls"
    )
    args = parser.parse_args()
    if args.candidate:
        if not args.compare:
            parser.error("--candidate requires --compare")
        try:
            comparison = compare_reports(
                json.loads(args.compare.read_text()),
                json.loads(args.candidate.read_text()),
            )
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps(comparison, indent=2))
        return int(bool(comparison["regressed"]))
    if not args.live:
        parser.error("pass --live to authorize paid DeepSeek requests")
    if not args.output or args.output.exists():
        parser.error(
            "--output must name a new report file; saved runs are never overwritten"
        )
    if not 1 <= args.repeats <= 10:
        parser.error("--repeats must be between 1 and 10")
    dataset_bytes = args.dataset.read_bytes()
    dataset = json.loads(dataset_bytes)
    planned = args.repeats * sum(len(s["turns"]) for s in dataset["scenarios"])
    if args.max_calls < planned:
        parser.error(f"--max-calls must cover the planned {planned} provider calls")
    settings = adapter.DeepSeekSettings.from_environment()
    trace = {}

    def capture(response: httpx.Response) -> None:
        # Capture synthetic responses only; never headers, credentials, or error bodies.
        response.read()
        trace["http_status"] = response.status_code
        if not response.is_success:
            return
        try:
            body = response.json()
            for key in ("id", "model", "usage", "system_fingerprint", "choices"):
                if key in body:
                    trace[key] = body[key]
        except ValueError:
            trace["malformed_response"] = True

    package = Path(adapter.__file__).parents[1]
    source_paths = [Path(adapter.__file__), *sorted((package / "schemas").glob("*.py"))]
    metadata = {
        "mode": "live",
        "max_live_calls": args.max_calls,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "reference_date": dataset["reference_date"],
        "dataset_version": dataset["version"],
        "dataset_sha256": digest(dataset_bytes),
        "evaluator_sha256": digest(Path(__file__).read_bytes()),
        "prompt_sha256": digest(adapter._SYSTEM_PROMPT.encode()),
        "source_sha256": {
            str(p.relative_to(package)): digest(p.read_bytes()) for p in source_paths
        },
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "model_requested": settings.model,
        "repeats": args.repeats,
        "timeout_seconds": settings.timeout_seconds,
        "request_settings": {
            "temperature": 0,
            "thinking": "disabled",
            "max_tokens": 4096,
        },
        "python": platform.python_version(),
        "dependencies": {name: version(name) for name in ("httpx", "pydantic")},
        "scope": "Adapter + test-only draft merge; no HTTP API/session/UI integration",
    }
    transport = LimitedTransport(httpx.HTTPTransport(retries=0), args.max_calls)
    with httpx.Client(
        transport=transport, event_hooks={"response": [capture]}, trust_env=False
    ) as client:
        with adapter.DeepSeekPreferenceExtractor(
            settings,
            http_client=client,
            today=lambda: date.fromisoformat(dataset["reference_date"]),
        ) as extractor:
            records = evaluate(
                extractor, dataset, repeats=args.repeats, provider_trace=trace
            )
    report = {"metadata": metadata, "summary": summarize(records), "records": records}
    metadata["live_calls"] = transport.calls
    metadata["finished_at_utc"] = datetime.now(UTC).isoformat()
    if args.compare:
        report["comparison"] = compare_reports(
            json.loads(args.compare.read_text()), report
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))
    print(f"Saved {args.output}")
    return int(report["summary"]["passed"] != report["summary"]["total"])


if __name__ == "__main__":
    raise SystemExit(main())
