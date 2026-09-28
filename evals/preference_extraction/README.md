# Preference extraction evaluation

This directory defines a repeatable **adapter evaluation**, not a full HTTP API or
UI end-to-end test. It sends synthetic messages through DeepSeek, validation, and
a test-only draft merger. It never wires the adapter into planning sessions.

## Dataset and grading

`cases.v1.json` is the versioned reference dataset: 24 scenarios, 28 turns per
repetition, including a five-turn conversation. The reference date is frozen at
September 27, 2026 in America/Los_Angeles. This makes relative-date expectations
repeatable even when the evaluator runs on a later calendar date.

Coverage includes speaker and named-traveler ownership, shared budgets,
add/replace/remove preferences, all seven next-weekday expressions, qualitative
normalization, unsupported requests, missing years, month-only dates, combined
budget ambiguity, duplicate names, and accumulated conversation state.

Each turn specifies its expected complete sparse update, status, required issue
paths/reasons, and whether an unsupported-request notice is required. Wording of
questions is not matched exactly because multiple phrasings can be correct.
Interest-tag order is ignored, but additional or missing edits fail the case.

A turn passes only when **all** its checks pass:

- Exactly the expected updates, without extra changes to another traveler.
- Expected status, clarification issues, and unsupported-request behavior.
- Stable traveler IDs and no mutation of the extractor's input.
- Correct accumulated draft after applying the update.

The conversation starts once and feeds each updated draft to the next turn. An
incorrect earlier edit can cause later state checks to fail; inspect the first
failure rather than treating every downstream failure as an independent cause.

The merge helper is deliberately test-only. It does not implement session locks,
origin resolution, unsupported-request acknowledgment, persistence, HTTP routes,
or UI rendering. Those need separate integration tests during API wiring.

## Run and compare

Export `DEEPSEEK_API_KEY` in the shell (never place it in a report or commit it).
From the repository root:

```sh
.venv/bin/python -m travel_ai.scripts.evaluate_extraction \
  --live --repeats 2 \
  --output evals/preference_extraction/runs/candidate-v1.json \
  --compare evals/preference_extraction/runs/baseline-v1.json
```

Two repetitions make 56 real, potentially billable API calls. There are no
automatic retries, so errors are recorded rather than silently replaced by a
successful retry. Existing output files cannot be overwritten. Use a new name
for each run. A nonzero exit means at least one turn failed.

Compare two existing reports without credentials or network access:

```sh
.venv/bin/python -m travel_ai.scripts.evaluate_extraction \
  --compare evals/preference_extraction/runs/baseline-v1.json \
  --candidate evals/preference_extraction/runs/candidate-v1.json
```

A comparison reports improved, regressed, and still-failing case/repetition pairs,
plus the percentage-point change in pass rate. A regression gives a nonzero exit.
It refuses comparisons if dataset hash, evaluator hash, repetition count, or
case/repetition keys differ. If you change the dataset or grading rules, rerun
both the baseline and candidate implementations under the new evaluation.

## What to retain for each experiment

Reports contain:

- Dataset version/hash, frozen reference date, UTC run timestamps.
- Requested model and provider-returned model identifier, when available.
- Prompt hash, adapter/schema source hashes, evaluator hash, Git commit and dirty
  flag, Python/dependency versions, request settings, and timeout.
- Every synthetic input draft/message, expected output, actual validated result,
  before/after state, check outcomes, safe errors, and measured latency.
- Selected successful provider response fields, including generated operations,
  usage and finish reason, to investigate model errors versus adapter errors.
- Pass counts by category, failures by check, and cases passing every repetition.

No API keys or request headers are saved. Provider error bodies are omitted.
Use synthetic/anonymized inputs; these reports are designed to be reviewable in
Git. Commit the code, dataset, and selected baseline together so the hashes can
be traced to an exact implementation. A dirty Git flag means the commit alone
cannot reconstruct the run; source hashes identify the working-tree content.

## Improvement workflow

1. Establish a baseline before changing the prompt or implementation.
2. Investigate failed cases and inspect their raw operations and validated output.
3. Make one focused change and rerun the **same** dataset and grader.
4. Check per-case regressions, particularly unintended traveler edits, rather than
   accepting a higher overall score that hides a new safety failure.
5. Review actual clarification wording and whether it asks the right question.
6. Add newly discovered failure cases to a new dataset version. Keep a separate,
   independently authored holdout set before making broad quality claims.

This small dataset is a **development regression suite**, not an estimate of
accuracy across all customer messages. Two repetitions expose some variability;
they do not establish reliability. Compare repeated runs under similar conditions
and use more repetitions before release. A model alias can change even if your
code does not; preserve the returned model identifier and run timestamp.

Use deterministic graders for exact updates, IDs, and state. Human review is
still needed for semantic quality of clarification and unsupported explanations.
An LLM judge could help later, but would itself need calibration and is unnecessary
for these exact field-level checks. Token usage is recorded when returned; this
runner does not calculate billed cost or claim precise pricing.

## Offline checks

```sh
.venv/bin/python -m pytest tests/test_deepseek_preference_extraction.py \
  tests/test_extraction_evaluation.py
```

Mocked tests verify sequential edits, timeout then successful explicit retry,
unchanged input after failures, and grader behavior (including detecting an
unwanted companion edit and a regression hidden by an unchanged overall score).
The rest of the repository's tests remain part of normal CI; live runs are opt-in.

The approach follows the distinction between capability and regression evals in
[Anthropic's evaluation guide](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
and dataset-based experiments described in
[LangSmith's evaluation documentation](https://docs.langchain.com/langsmith/evaluation-types).
