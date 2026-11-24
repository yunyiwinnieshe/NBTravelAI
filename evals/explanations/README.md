# Grounded explanation evaluation

This directory contains the versioned, offline evaluation for recommendation
explanations. It checks whether published explanation text stays tied to the
restricted evidence contract; it is not an LLM benchmark or a user-preference
study.

## Reproduce

From the repository root:

```powershell
.venv\Scripts\python.exe -m travel_ai.scripts.evaluate_explanations
```

The command reads `cases.v1.json` and rewrites matching artifacts under
`runs/v1/`. It performs no network or model calls and fixes the recommendation
clock from the dataset.

## V1 cases and checks

The five synthetic fixture cases cover:

- three ranked destinations and their tradeoffs;
- a budget-constrained result set;
- empty preference lists;
- a no-match result; and
- an injected unsupported safety claim that must use the safe fallback.

Checks compare generated text with saved evidence for destination IDs, rank,
score, price/travel/preference/fairness differences, fairness scope, exclusion
guidance, timestamp, candidate-pool version, and fixture source labeling. They
also reject unsupported superlatives and promises of a result.

## Saved result

The V1 run passed **5/5 cases and 61/61 checks**. See
[`runs/v1/summary.md`](runs/v1/summary.md) for the review summary and
[`runs/v1/report.json`](runs/v1/report.json) for requests, exact evidence,
generated explanations, individual checks, hashes, and run metadata.

## Bounds

Passing this suite establishes deterministic grounding for the covered fixture
cases. It does not establish that the prose is persuasive, that users prefer the
rankings, that live data is fresh, or that an LLM can generate explanations
reliably. Those claims require separate human or live-model evaluation.
