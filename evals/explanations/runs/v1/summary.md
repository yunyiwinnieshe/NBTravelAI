# Grounded explanation quality evaluation — V1

Deterministic offline evaluation; no LLM or network calls were made.

Cases: 5/5 passed.
Checks: 61/61 passed.
Dataset: v1.0 (f3eefa212194658fe1054113dead5820f1a33f6b748686d1545842f5dd71ed6e).
Evidence timestamp: 2099-06-01T10:00:00+00:00.

## Coverage

- fairness_boundary: 1/1 cases passed.
- no_match_guidance: 1/1 cases passed.
- ranked_tradeoffs: 2/2 cases passed.
- unsupported_claims: 1/1 cases passed.

## Case results

- **PASS — ranked_three_destinations** (ranked_tradeoffs): 14/14 checks passed.
- **PASS — budget_constrained_results** (ranked_tradeoffs): 11/11 checks passed.
- **PASS — empty_preferences** (fairness_boundary): 14/14 checks passed.
- **PASS — no_match_low_budget** (no_match_guidance): 7/7 checks passed.
- **PASS — unsafe_claim_fallback** (unsupported_claims): 15/15 checks passed.

## What this establishes

- Published rank, score, comparison, fairness, and freshness text is tied to saved evidence.
- Unsupported structured claims are rejected and use the deterministic fallback.
- Fairness wording is limited to the implemented metrics.
- No-match guidance avoids guarantees; fixture/live source labels stay separate.

## Bounds

This synthetic fixture set tests grounding invariants and regressions. It does not measure human persuasiveness, destination desirability, live-provider freshness, LLM quality, or production reliability.

See `report.json` for each request, evidence, generated text, and checks.