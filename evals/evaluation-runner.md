# Offline-first evaluation runner

From the repository root, run:

```sh
.venv/bin/python -m travel_ai.scripts.evaluate_sessions
```

No API key, server, Postman login, or network access is needed. This runs 30
conversation cases (78 steps) and 20 deterministic recommendation cases and writes:

- `evals/session_runs/offline/<run-id>/report.json`: machine-readable results.
- `evals/session_runs/offline/<run-id>/results.json`: compact case outcomes for review.
- `evals/session_runs/offline/<run-id>/summary.md`: readable totals and failures.

The default run ID is a UTC timestamp. Use `--run-id my-baseline` to name it, and
`--output-dir /tmp/travel-ai-evals` to put results elsewhere. Existing run
directories are never overwritten. Exit code 0 means every step passed; 1 means
at least one step failed or was skipped; 2 means configuration/preflight failed.

## What offline evaluation means

The runner uses the versioned conversation expectations in
`conversations/cases.v2.json`. Model responses are separately authored in
`conversations/offline-responses.v2.json`; they are not generated from expected
outcomes at runtime. The real DeepSeek adapter validates and normalizes those
mock HTTP responses. The real session service applies updates, asks questions,
and enforces confirmation. The 20 cases in `recommendations/cases.v1.json`
test the deterministic recommendation service against saved eligibility labels,
budget and travel-time invariants, validation errors, and no-match outcomes.
They use the fixed flight snapshots and make no model calls.

This measures adapter/session behavior with controlled inputs, **not DeepSeek's
language understanding**. An offline pass cannot establish model accuracy or
prove that a prompt change improves interpretation. An ambient DeepSeek API key
or `EXTRACTION_PROVIDER=deepseek` cannot switch this runner into live mode.

The runner calls services directly, not the API routes. The
[Postman walkthrough](../docs/postman-conversation-walkthrough.md) remains the HTTP
integration check. This runner does not start a server or modify production
configuration. Its date override is scoped to the single-process evaluation.

## Explicit live evaluation

Set `DEEPSEEK_API_KEY` in the process environment. Then explicitly authorize and
bound calls:

```sh
.venv/bin/python -m travel_ai.scripts.evaluate_sessions \
  --live --max-calls 63 --run-id live-baseline
```

This writes under `evals/session_runs/live/`, separately from offline reports.
The current full dataset needs 63 model calls; structured actions, two explicit
control-only messages, and all recommendation-only cases make no model calls.
`--repeats 2` needs 126 calls.
A selected conversation subset can use a smaller
limit:

```sh
.venv/bin/python -m travel_ai.scripts.evaluate_sessions \
  --live --case 09_missing_year --repeats 3 --max-calls 9 \
  --run-id year-followup
```

`--case` can be supplied more than once; it selects conversation cases and skips
the recommendation-only suite. Unknown IDs fail preflight. Missing or
insufficient `--max-calls` is rejected before any request is sent. The limit is
also enforced at the transport boundary: failed attempts count, and calls beyond
the cap are blocked. No automatic retries are used in this evaluator, so a failure
is retained rather than silently replaced with a successful retry. Remaining
steps become skipped if the runtime budget is exhausted or their session could
not be created. Skipped steps never count as passes.

Model and HTTP I/O timeout are configurable through `DEEPSEEK_MODEL` and
`DEEPSEEK_TIMEOUT_SECONDS`. The production session retry/deadline wrapper is not
used here; its behavior remains covered by offline API tests. The evaluator's
call limit bounds the number of provider requests, not a dollar amount.

The older adapter-only runner also now requires a call limit:

```sh
.venv/bin/python -m travel_ai.scripts.evaluate_extraction \
  --live --max-calls 56 --repeats 2 \
  --output evals/preference_extraction/runs/new-candidate.json
```

Its existing saved-report comparison command remains offline and needs no key.
It has a different report/grader schema from the session runner; do not compare
their pass rates as if they measured the same thing.

## Results and reproducibility

Each session record includes case ID, stable step ID, repetition, category,
synthetic request, expected outcome, actual response, latency, check-level
expected/actual values, pass/fail, and failure reasons. Checks cover field values,
clarification targets, stable IDs, unrelated fields, unsupported notices,
question limits, confirmation gating, and preservation of drafts after failures.
The full `report.json` retains structured recommendations, not just an overall score. The
separate `recommendation_records` and `recommendation_summary` provide case IDs,
saved expected outcomes, actual outcomes, failures, and category totals.
Preference-ranking judgments are marked provisional for Ivy; the grader checks
hard eligibility and constraints, not subjective destination order.
The compact `results.json` keeps case IDs, expected and actual outcomes, failed
checks, and version hashes. Full response reports stay local; selected compact
baselines, summaries, and analyses are versioned with the project.

Metadata records:

- Conversation and recommendation dataset versions and SHA-256 hashes; selected
  conversation IDs and repetitions.
- Offline fixture version/hash and clock-configuration hash.
- Prompt SHA-256, requested and provider-returned model identifiers.
- Git commit/dirty state, Python/dependency versions, and source-file hashes.
- Hashes of the fixed airport, climate, city, and flight fixture snapshots.
- Frozen reference date, request settings, UTC timestamps, call limit, and actual
  live/mock attempt counts.

The reference date is `2026-10-03`, declared in the fixture/configuration file
and applied consistently to extraction and session/request date validation.
Recommendation timestamps use that same reference. Flight dates in 2099 remain
synthetic fixture examples, not real availability.

Provider error bodies, exception details, request headers, and credentials are
not saved. Error types and failed checks are recorded. Reports still contain
conversation text; only use synthetic or suitably anonymized cases.

Retain JSON and Markdown together. For before/after evaluation, use identical
case expectations, fixture/clock data, selection, and repetitions. Check code,
prompt, and model versions before interpreting a difference. Offline and live
results must remain separate in any later evaluation report. The CLI uses
separate output directories and prominently labels both formats.

## Extending the dataset

For a new conversation case, add its requests and expectations to the saved
conversation dataset, then author the corresponding mock model responses in the
fixture file for offline evaluation. A fixture reference is required for every
message that invokes extraction; action-only steps use `null`. Missing fixtures
fail setup instead of fabricating successful outcomes. The only dynamic fixture
substitutions are the current message for evidence and the sole pending notice
ID for acknowledgement. Keep fixture predictions separate from grading labels.

The v1 conversation cases remain as the Postman collection source; v2 extends
them for this offline-first runner. The broader failure-priority report is a
subsequent ticket. No ranking formulas, persistence, or origin-resolution behavior
changed.

## Validation

```sh
.venv/bin/pytest tests/test_session_evaluation.py tests/test_extraction_evaluation.py
```

Tests block real transport creation in offline mode, exercise capped live mode
through mock HTTP transport, count failed attempts against the cap, verify report
separation/no overwrite, and deliberately corrupt outputs to prove the grader
rejects wrong companion edits and incomplete year corrections. They also detect
recommendations invoked before review. Test live-mode reports are mocked tests,
not actual model evaluation results.

The retained `offline/runner-offline-v1` development report caught an incorrectly
authored companion-evidence fixture in `03_missing_multiple`; it is not a model
failure. The fixture was corrected to quote only the companion's clause. The
subsequent offline baseline verifies the corrected fixture set. Run the command
above to generate a fresh 50-case report; the output is separated from real-model
results by mode and run ID. A passing offline run is not a claim that DeepSeek
would interpret every message correctly.

Verification after the control-message safeguard: **381 offline tests passed**, and Ruff
lint and format checks passed. The earlier [12-case offline baseline](session_runs/offline/runner-offline-v2/summary.md)
remains available for historical comparison.

## First expanded live run

The [2026-10-04 live run](session_runs/live/live-expanded-v1/analysis.md) used
the 30-case conversation dataset, sent 65 bounded DeepSeek calls, and passed
28/30 conversation cases (76/78 steps). All 20 deterministic recommendation
cases passed without model calls. The two provisional prompt-injection labels
expected `review`; DeepSeek instead surfaced the messages as unsupported and
the session required acknowledgment. Draft budgets remained unchanged and no
recommendations were produced. A focused two-repeat run showed both `review`
and `collecting` as safe outcomes; the labels remain provisional for Ivy's review.

## Control-message safeguard and follow-up

The session now recognizes a narrow set of explicit control-only messages,
including the two saved prompt-injection cases, before model extraction. It
keeps the draft and state unchanged and explains that system or credential
instructions cannot be followed. Ordinary trip corrections still reach the
extractor, and unsupported *travel* requests still require acknowledgment.
The saved cases keep their `review` expectation, so the safeguard is tested
against the original labels rather than relaxed labels.

The [live rerun](session_runs/live/live-control-guard-v3/analysis.md)
passed all 30 conversation cases / 78 steps and all 20 deterministic
recommendation cases, using 63 real model calls. The earlier intermediate run
and the targeted temperature repetitions are retained because live model
outputs can vary; one successful run does not guarantee future accuracy.
