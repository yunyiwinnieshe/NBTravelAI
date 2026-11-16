"""Tests for the reproducible grounded-explanation quality evaluation."""

import json
from pathlib import Path

from travel_ai.evaluation.explanations import (
    ExplanationDataset,
    evaluate_explanations,
    summarize_explanations,
)
from travel_ai.scripts.evaluate_explanations import run

REPOSITORY_ROOT = Path(__file__).parents[1]
DATASET_PATH = REPOSITORY_ROOT / "evals" / "explanations" / "cases.v1.json"


def load_dataset() -> ExplanationDataset:
    return ExplanationDataset.model_validate_json(DATASET_PATH.read_bytes())


def test_versioned_explanation_cases_pass_evidence_checks() -> None:
    records = evaluate_explanations(load_dataset())
    summary = summarize_explanations(records)

    assert summary["cases"] == 5
    assert summary["cases_passed"] == 5
    assert summary["checks_passed"] == summary["checks"]
    assert summary["failure_reasons"] == {}


def test_evaluation_covers_unsafe_claim_fallback() -> None:
    records = evaluate_explanations(load_dataset())
    unsafe = next(
        record for record in records if record["generator_mode"] == "unsafe_claim"
    )

    check = next(
        item for item in unsafe["checks"] if item["name"] == "unsafe_generator_fallback"
    )
    assert check["passed"]
    assert "safest option" not in json.dumps(unsafe["actual"]).lower()


def test_runner_saves_json_evidence_and_markdown_summary(tmp_path: Path) -> None:
    exit_code, report = run(DATASET_PATH, tmp_path)

    assert exit_code == 0
    assert report["metadata"]["mode"] == "offline_fixture"
    assert report["metadata"]["measures_model_quality"] is False
    assert report["metadata"]["network_calls"] == 0
    saved = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert saved["summary"]["cases_passed"] == 5
    assert all(record["evidence"] for record in saved["records"])
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Cases: 5/5 passed" in summary
    assert "does not measure human persuasiveness" in summary
