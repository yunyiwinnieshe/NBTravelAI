# Session evaluation — OFFLINE

OFFLINE: authored mock responses test adapter/session behavior. This is NOT model accuracy.

Cases: 11/12 passed.
Steps: 32/34 passed; 1 skipped.
Live calls: 0; mock calls: 28.

Dataset: 1.0 (468b27a027e30539c4f02b94e262dca566ca0d560c2589b18644c4054a8b11cf).
Prompt SHA-256: 8baaa8aa3b9d9f3c9a96eeb09d090b1aa3342f6939a9e3e0782b9e6375860f60.
Model: none (mocked).
Code: 4d18fc189da3bf7ec96007b44c55745c65b42e9f (dirty=True).

## Categories

- ambiguous: 5/5 steps passed.
- complete: 6/6 steps passed.
- corrected: 10/10 steps passed.
- incomplete: 3/5 steps passed.
- unsupported: 8/8 steps passed.

## Failures

- r1 03_missing_multiple/01: http_status, DeepSeekResponseError.
- r1 03_missing_multiple/02: session_creation_failed.

See report.json for each request, expected/actual outcomes, and check-level reasons.
