"""Run saved conversation cases offline by default, or explicitly against DeepSeek."""

import argparse
import hashlib
import json
import platform
import re
import subprocess
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path

import httpx

from travel_ai.evaluation.recommendations import (
    RecommendationDataset,
    evaluate_recommendations,
    summarize_recommendations,
)
from travel_ai.evaluation.sessions import (
    Dataset,
    ReplayTransport,
    evaluate,
    needs_extraction,
    summarize,
)
from travel_ai.evaluation.transports import LimitedTransport
from travel_ai.services import deepseek_preference_extraction as adapter


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_value(*args):
    try:
        return subprocess.check_output(
            ["git", *args], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def metadata(
    dataset, dataset_bytes, bundle_bytes, reference, mode, settings, repeats, limit
):
    package = Path(adapter.__file__).parents[1]
    paths = [
        *sorted(package.rglob("*.py")),
        *sorted((package / "fixtures").glob("*.json")),
    ]
    status = git_value("status", "--porcelain")
    return {
        "mode": mode,
        "scope": (
            "Real adapter normalization + session service + "
            "deterministic fixture recommendations; no HTTP routing"
        ),
        "measures_model_quality": mode == "live",
        "dataset_version": dataset.version,
        "dataset_sha256": digest(dataset_bytes),
        "offline_fixture_sha256": digest(bundle_bytes) if mode == "offline" else None,
        "clock_configuration_sha256": digest(bundle_bytes),
        "reference_date": reference.isoformat(),
        "repeats": repeats,
        "prompt_sha256": digest(adapter._SYSTEM_PROMPT.encode()),
        "model_requested": settings.model if mode == "live" else None,
        "model_returned": [],
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_dirty": bool(status) if status is not None else None,
        "source_sha256": {
            str(p.relative_to(package)): digest(p.read_bytes()) for p in paths
        },
        "python": platform.python_version(),
        "dependencies": {
            name: version(name) for name in ("httpx", "pydantic", "fastapi")
        },
        "request_settings": {
            "timeout_seconds": settings.timeout_seconds,
            "automatic_retries": 0,
            "temperature": 0,
            "thinking": "disabled",
            "max_tokens": 4096,
        },
        "max_live_calls": limit,
        "live_calls": 0,
        "mock_calls": 0,
    }


def readable(report):
    meta, summary = report["metadata"], report["summary"]
    lines = [
        f"# Session evaluation — {meta['mode'].upper()}",
        "",
        "Real DeepSeek results."
        if meta["mode"] == "live"
        else (
            "OFFLINE: authored mock responses test adapter/session behavior. "
            "This is NOT model accuracy."
        ),
        "",
        f"Cases: {summary['case_runs_passed']}/{summary['case_runs']} passed.",
        (
            f"Steps: {summary['steps_passed']}/{summary['steps']} passed; "
            f"{summary['steps_skipped']} skipped."
        ),
        f"Live calls: {meta['live_calls']}; mock calls: {meta['mock_calls']}.",
        "",
        f"Dataset: {meta['dataset_version']} ({meta['dataset_sha256']}).",
        f"Prompt SHA-256: {meta['prompt_sha256']}.",
        f"Model: {meta['model_requested'] or 'none (mocked)'}.",
        f"Code: {meta['git_commit']} (dirty={meta['git_dirty']}).",
        "",
        "## Categories",
        "",
    ]
    lines.extend(
        f"- {key}: {value['passed']}/{value['total']} steps passed."
        for key, value in summary["categories"].items()
    )
    lines += ["", "## Failures", ""]
    failures = [r for r in report["records"] if not r["passed"]]
    lines.extend(
        f"- r{r['repeat']} {r['step_id']}: {', '.join(r['reasons'])}." for r in failures
    )
    if not failures:
        lines.append(
            "None in this run. This small development dataset does not "
            "establish production reliability."
        )
    lines += [
        "",
        "## Deterministic recommendations",
        "",
        (
            f"Cases: {report['recommendation_summary']['case_runs_passed']}/"
            f"{report['recommendation_summary']['case_runs']} passed; "
            f"{report['recommendation_summary']['provisional_case_runs']} "
            "provisional labels."
        ),
        "",
    ]
    lines.extend(
        f"- {r['case_id']}: {', '.join(r['reasons'])}."
        for r in report["recommendation_records"]
        if not r["passed"]
    )
    lines += [
        "",
        "See report.json for requests, expected/actual outcomes, and check reasons.",
        "",
    ]
    return "\n".join(lines)


def compact_results(report):
    """Keep versioned run evidence reviewable without full response payloads."""
    metadata = report["metadata"]
    version_keys = (
        "mode",
        "dataset_version",
        "dataset_sha256",
        "recommendation_dataset_version",
        "recommendation_dataset_sha256",
        "offline_fixture_version",
        "offline_fixture_sha256",
        "reference_date",
        "prompt_sha256",
        "model_requested",
        "model_returned",
        "git_commit",
        "git_dirty",
        "source_sha256",
        "live_calls",
        "mock_calls",
    )
    conversations = []
    for record in report["records"]:
        body = (record.get("actual") or {}).get("body") or {}
        conversations.append(
            {
                "step_id": record["step_id"],
                "case_id": record["case_id"],
                "category": record["category"],
                "label_status": record.get("label_status", "reviewed"),
                "repeat": record["repeat"],
                "expected": record["expected"],
                "actual": {
                    "http_status": (record.get("actual") or {}).get("http_status"),
                    "state": body.get("state"),
                    "fields": {
                        check["name"].removeprefix("field:"): check["actual"]
                        for check in record["checks"]
                        if check["name"].startswith("field:")
                    },
                    "missing": body.get("missing_fields", []),
                    "unsupported": bool(body.get("unsupported_requests")),
                    "deferred": bool(body.get("deferred_requests")),
                    "recommendation_count": len(body.get("recommendations") or []),
                },
                "passed": record["passed"],
                "reasons": record["reasons"],
                "failed_checks": [
                    check for check in record["checks"] if not check["passed"]
                ],
            }
        )
    return {
        "report_version": report["report_version"],
        "metadata": {key: metadata.get(key) for key in version_keys},
        "summary": report["summary"],
        "conversation_steps": conversations,
        "recommendation_summary": report.get("recommendation_summary"),
        "recommendation_cases": [
            {
                key: record[key]
                for key in (
                    "case_id",
                    "category",
                    "label_status",
                    "reviewer",
                    "repeat",
                    "expected",
                    "actual",
                    "passed",
                    "reasons",
                )
            }
            for record in report.get("recommendation_records", [])
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=Path("evals/conversations/cases.v2.json")
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path("evals/conversations/offline-responses.v2.json"),
    )
    parser.add_argument(
        "--recommendations",
        type=Path,
        default=Path("evals/recommendations/cases.v1.json"),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Authorize paid DeepSeek calls; default is offline",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=0,
        help="Required positive hard limit with --live",
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--case", action="append", dest="case_ids", help="Select a case ID (repeatable)"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("evals/session_runs"))
    parser.add_argument(
        "--run-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 10:
        parser.error("--repeats must be between 1 and 10")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.run_id):
        parser.error("--run-id must be a simple name, not a path")
    if args.live and args.max_calls < 1:
        parser.error("--live requires a positive --max-calls")
    if not args.live and args.max_calls:
        parser.error("--max-calls requires explicit --live")
    try:
        dataset_bytes = args.dataset.read_bytes()
        dataset = Dataset.model_validate_json(dataset_bytes)
        bundle_bytes = args.fixtures.read_bytes()
        bundle = json.loads(bundle_bytes)
        reference = date.fromisoformat(bundle["reference_date"])
        recommendation_bytes = args.recommendations.read_bytes()
        recommendation_dataset = RecommendationDataset.model_validate_json(
            recommendation_bytes
        )
        if recommendation_dataset.reference_date != reference:
            raise ValueError("conversation and recommendation reference dates differ")
        if args.case_ids:
            unknown = set(args.case_ids) - {c.id for c in dataset.cases}
            if unknown:
                parser.error(f"Unknown case IDs: {sorted(unknown)}")
            dataset = dataset.model_copy(
                update={"cases": [c for c in dataset.cases if c.id in args.case_ids]}
            )
        planned = args.repeats * sum(
            needs_extraction(s) for c in dataset.cases for s in c.steps
        )
        if args.live and planned > args.max_calls:
            parser.error(
                f"Need {planned} calls; --max-calls is {args.max_calls}. No calls sent."
            )
        settings = (
            adapter.DeepSeekSettings.from_environment()
            if args.live
            else adapter.DeepSeekSettings(api_key="offline-placeholder")
        )
        replay = None if args.live else ReplayTransport(bundle, dataset)
    except (OSError, ValueError, KeyError, adapter.DeepSeekConfigurationError) as error:
        parser.error(
            f"Evaluation setup failed ({type(error).__name__}); "
            "check dataset, fixtures, and configuration."
        )
    mode = "live" if args.live else "offline"
    output = args.output_dir / mode / args.run_id
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError:
        parser.error(
            "Cannot create new run directory; existing runs are never overwritten"
        )
    meta = metadata(
        dataset,
        dataset_bytes,
        bundle_bytes,
        reference,
        mode,
        settings,
        args.repeats,
        args.max_calls,
    )
    meta["offline_fixture_version"] = bundle["version"] if replay else None
    meta["recommendation_dataset_version"] = recommendation_dataset.version
    meta["recommendation_dataset_sha256"] = digest(recommendation_bytes)
    meta.update(
        started_at_utc=datetime.now(UTC).isoformat(),
        selected_case_ids=[c.id for c in dataset.cases],
        selected_recommendation_case_ids=(
            [] if args.case_ids else [c.id for c in recommendation_dataset.cases]
        ),
        planned_model_calls=planned,
    )
    returned_models = set()

    def capture(response):
        response.read()
        if response.is_success:
            try:
                name = response.json().get("model")
                if isinstance(name, str):
                    returned_models.add(name)
            except ValueError:
                pass

    transport = (
        LimitedTransport(httpx.HTTPTransport(retries=0), args.max_calls)
        if args.live
        else replay
    )
    with httpx.Client(
        transport=transport, trust_env=False, event_hooks={"response": [capture]}
    ) as client:
        extractor = adapter.DeepSeekPreferenceExtractor(
            settings, http_client=client, today=lambda: reference
        )
        records = evaluate(
            dataset, extractor, reference, repeats=args.repeats, replay=replay
        )
    meta.update(
        finished_at_utc=datetime.now(UTC).isoformat(),
        live_calls=transport.calls if args.live else 0,
        mock_calls=0 if args.live else replay.calls,
        model_returned=sorted(returned_models),
    )
    recommendation_records = (
        []
        if args.case_ids
        else evaluate_recommendations(recommendation_dataset, repeats=args.repeats)
    )
    report = {
        "report_version": "1.0",
        "metadata": meta,
        "summary": summarize(records),
        "records": records,
        "recommendation_summary": summarize_recommendations(recommendation_records),
        "recommendation_records": recommendation_records,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "results.json").write_text(
        json.dumps(compact_results(report), indent=2) + "\n"
    )
    (output / "summary.md").write_text(readable(report))
    print(readable(report))
    print(f"Saved {output}")
    return int(any(not r["passed"] for r in records + recommendation_records))


if __name__ == "__main__":
    raise SystemExit(main())
