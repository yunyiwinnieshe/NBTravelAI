"""Run and save the deterministic grounded-explanation evaluation."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from travel_ai.evaluation.explanations import (
    ExplanationDataset,
    evaluate_explanations,
    summarize_explanations,
)

PACKAGE_ROOT = Path(__file__).parents[1]


def _repository_root() -> Path:
    """Find checkout data even when this module is imported from site-packages."""
    candidates = (*Path(__file__).parents, Path.cwd(), *Path.cwd().parents)
    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "evals" / "explanations"
        ).is_dir():
            return candidate
    return Path.cwd()


REPOSITORY_ROOT = _repository_root()
DEFAULT_DATASET = REPOSITORY_ROOT / "evals" / "explanations" / "cases.v1.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "evals" / "explanations" / "runs" / "v1"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=REPOSITORY_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _source_hashes() -> dict[str, str]:
    paths = (
        ("src/travel_ai/scripts/evaluate_explanations.py", Path(__file__)),
        (
            "src/travel_ai/evaluation/explanations.py",
            PACKAGE_ROOT / "evaluation" / "explanations.py",
        ),
        (
            "src/travel_ai/services/explanation_evidence.py",
            PACKAGE_ROOT / "services" / "explanation_evidence.py",
        ),
        (
            "src/travel_ai/services/explanation_generation.py",
            PACKAGE_ROOT / "services" / "explanation_generation.py",
        ),
        (
            "src/travel_ai/schemas/explanations.py",
            PACKAGE_ROOT / "schemas" / "explanations.py",
        ),
        (
            "src/travel_ai/schemas/generated_explanations.py",
            PACKAGE_ROOT / "schemas" / "generated_explanations.py",
        ),
    )
    return {label: _sha256(path.read_bytes()) for label, path in paths}


def render_summary(report: dict[str, Any]) -> str:
    """Render a compact human-reviewable companion to the JSON evidence."""
    metadata = report["metadata"]
    summary = report["summary"]
    lines = [
        "# Grounded explanation quality evaluation — V1",
        "",
        "Deterministic offline evaluation; no LLM or network calls were made.",
        "",
        f"Cases: {summary['cases_passed']}/{summary['cases']} passed.",
        f"Checks: {summary['checks_passed']}/{summary['checks']} passed.",
        f"Dataset: {metadata['dataset_version']} ({metadata['dataset_sha256']}).",
        f"Evidence timestamp: {metadata['evaluated_at']}.",
        "",
        "## Coverage",
        "",
    ]
    lines.extend(
        f"- {category}: {result['passed']}/{result['total']} cases passed."
        for category, result in summary["categories"].items()
    )
    lines.extend(["", "## Case results", ""])
    for record in report["records"]:
        state = "PASS" if record["passed"] else "FAIL"
        lines.append(
            f"- **{state} — {record['case_id']}** ({record['category']}): "
            f"{len(record['checks']) - len(record['failure_reasons'])}/"
            f"{len(record['checks'])} checks passed."
        )
        if record["failure_reasons"]:
            lines.append(f"  Failures: {', '.join(record['failure_reasons'])}.")
    lines.extend(
        [
            "",
            "## What this establishes",
            "",
            "- Published rank, score, comparison, fairness, and freshness text is tied "
            "to saved evidence.",
            "- Unsupported structured claims are rejected and use the deterministic "
            "fallback.",
            "- Fairness wording is limited to the implemented metrics.",
            "- No-match guidance avoids guarantees; fixture/live source labels stay "
            "separate.",
            "",
            "## Bounds",
            "",
            "This synthetic fixture set tests grounding invariants and regressions. "
            "It does not measure human persuasiveness, destination desirability, "
            "live-provider freshness, LLM quality, or production reliability.",
            "",
            "See `report.json` for each request, evidence, generated text, and checks.",
        ]
    )
    return "\n".join(lines)


def run(
    dataset_path: Path = DEFAULT_DATASET,
    output_directory: Path = DEFAULT_OUTPUT,
) -> tuple[int, dict[str, Any]]:
    """Evaluate a versioned dataset and save matching JSON and Markdown artifacts."""
    dataset_bytes = dataset_path.read_bytes()
    dataset = ExplanationDataset.model_validate_json(dataset_bytes)
    records = evaluate_explanations(dataset)
    summary = summarize_explanations(records)
    git_status = _git_value("status", "--porcelain")
    report = {
        "metadata": {
            "evaluation": "grounded_recommendation_explanations",
            "evaluation_version": "v1",
            "mode": "offline_fixture",
            "measures_model_quality": False,
            "network_calls": 0,
            "dataset_version": dataset.version,
            "dataset_sha256": _sha256(dataset_bytes),
            "evaluated_at": dataset.evaluated_at.isoformat(),
            "generated_at": datetime.now(UTC).isoformat(),
            "git_commit": _git_value("rev-parse", "HEAD"),
            "git_dirty": bool(git_status) if git_status is not None else None,
            "source_sha256": _source_hashes(),
        },
        "summary": summary,
        "records": records,
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_directory / "summary.md").write_text(
        render_summary(report),
        encoding="utf-8",
    )
    return (0 if summary["cases_passed"] == summary["cases"] else 1), report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate grounded recommendation explanations offline."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    exit_code, report = run(args.dataset, args.output)
    print(render_summary(report))
    print(f"Saved {args.output.resolve()}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
