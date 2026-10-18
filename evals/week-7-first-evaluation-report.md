# Week 7 — first evaluation and priority failures

Prepared 2026-10-18 from the saved synthetic evaluation datasets. This report
separates model interpretation and session behavior from deterministic
recommendation constraints. Pass counts describe these cases and versions, not
production accuracy.

## Runs and category results

| Evidence | Extraction and session behavior | Deterministic recommendations |
| --- | --- | --- |
| [First expanded live run](session_runs/live/live-expanded-v1/analysis.md), 2026-10-04, DeepSeek `deepseek-flash`, 65 calls | 28/30 cases; 76/78 steps | 20/20 cases |
| [Verified live rerun](session_runs/live/live-control-guard-v3/analysis.md), 2026-10-04, same model, 63 calls | 30/30 cases; 78/78 steps | 20/20 cases |
| [Fresh offline run](session_runs/offline/week7-report-2026-10-18/summary.md), 2026-10-18, authored mock responses, 0 live calls | 30/30 cases; 78/78 steps | 20/20 cases |

The verified live and fresh offline runs both passed these conversation steps:
ambiguous 7/7, complete 6/6, confirmation 7/7, corrected 21/21, incomplete
5/5, invalid 10/10, no-match 5/5, prompt injection 4/4, and unsupported 13/13.
These are **session-step categories**, not a separate score for extraction alone.
The older [adapter-only live extraction baseline](preference_extraction/runs/baseline-v1.md)
passed 56/56 attempts across 28 distinct turns. Its grader and dataset differ,
so its score is not combined with the session scores.

The fresh deterministic run passed budget 8/8, coverage 1/1, basic eligibility
1/1, identity 1/1, preference 3/3, travel-time 2/2, and validation 4/4 cases.
There were **zero observed hard-constraint violations** in these 20 cases.
The three preference cases check hard eligibility; their subjective ranking
labels are still provisional and require Ivy's review. The runner does not grade
human preference order or establish broad ranking quality.

The runner also generated `report.json` and `results.json` in the fresh run's
local directory. They retain case IDs, expectations, actual values, checks,
category totals, and version hashes. Repository policy ignores these larger
generated files; rerun the command below to regenerate them. The live run has
its own saved summary under `session_runs/live/live-control-guard-v3/`. Offline
mock results are not evidence that DeepSeek understood those messages.

## Failure classification and priority

| Priority | Class and reproducible case | Observed impact | Resolution and evidence |
| --- | --- | --- | --- |
| P0 | Confirmation bypass or saved-value corruption | None observed in these runs. Both initial injection failures preserved budgets and returned no recommendations. | Confirmation requires the structured action; edits require renewed review. Regression checks cover the gate, idempotent confirmation, and unrelated-field preservation. |
| P1 | Extraction/session correction: `09_missing_year`, step 03, answer `2099` | In the first HTTP run, the proposed June 11 departure stayed June 10 and the session repeated the year question. The prior valid draft was preserved. | The prompt now supplies pending-question context. [Known-failure record](conversations/known-failures.json) retains expected/actual output, diagnosis, fix, and [3/3 targeted plus 12/12 full HTTP verification](conversations/README.md). Regression tests cover this reply and ambiguous or invalid alternatives. |
| P2 | Session state: `29_injection_override/02` and `30_injection_confirm/02` | The first expanded live run labeled injected control messages `collecting` instead of the provisional `review`; budgets and confirmation gate stayed intact. | A narrow control-message safeguard passed the [full live rerun](session_runs/live/live-control-guard-v3/analysis.md) and [fresh offline run](session_runs/offline/week7-report-2026-10-18/summary.md). The initial failures and repeated outcomes remain saved. |
| P2 | Model variation: `23_clear_temperature/02` | An intermediate prompt experiment missed the temperature clear and state expectation. | That prompt edit was removed; [three targeted repeats](session_runs/live/live-temperature-repeat-v1/summary.md) and the full live rerun passed. Retain the case to detect recurrence. |
| P2 | Ranking-label review: `13_no_interests`, `14_museum_nature`, and `15_temperature` | Hard eligibility passes, but the desired subjective order is unapproved. | Ivy should review the three `label_status: provisional` examples in [the recommendation dataset](recommendations/cases.v1.json); revise labels only with a documented rationale and a new baseline. |

No P0 fix was needed because no P0 failure was observed. The historical correction
and state failures were fixed or bounded without deleting their original
expectations. The prompt-injection category remains a limited test of two
synthetic messages, not a general security guarantee.

## Reproduce and finish review

Run `.venv/bin/python -m travel_ai.scripts.evaluate_sessions` for a new offline
run. The [runner guide](evaluation-runner.md) gives the explicit, call-limited
live command and explains its frozen reference date and report metadata. Compare
the same dataset and configuration across runs; model outputs may vary. The
remaining review is approval of the three provisional ranking labels and a
release threshold for observed live-model performance. Expand the dataset before
using these pass rates as a release-quality estimate.
