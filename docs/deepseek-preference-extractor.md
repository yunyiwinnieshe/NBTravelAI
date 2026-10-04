# DeepSeek preference extractor

`DeepSeekPreferenceExtractor` implements `PreferenceExtractor.extract(message,
current_draft)`. Planning sessions can select it with
`EXTRACTION_PROVIDER=deepseek`; see [session wiring](deepseek-planning-sessions.md).
The default remains fixture extraction. No frontend, flight provider, or ranking
changes are included.

## Configuration and use

Set `DEEPSEEK_API_KEY` in the process environment. Optional settings are
`DEEPSEEK_MODEL` (default `deepseek-flash`) and `DEEPSEEK_TIMEOUT_SECONDS` (default
20, finite and positive). `.env.example` documents these; the adapter does not
load a `.env` file automatically. Never commit a real key.

```python
from travel_ai.services.deepseek_preference_extraction import (
    DeepSeekPreferenceExtractor,
)

with DeepSeekPreferenceExtractor() as extractor:
    result = extractor.extract(message, current_draft)
    sparse_updates = result.draft.model_dump(exclude_unset=True)
```

The current draft must have exactly the application-assigned `traveler_a` and
`traveler_b` IDs. The result always includes both IDs, even when one or both
travelers have no updates. The input draft is never mutated.

The adapter calls the direct `POST https://api.deepseek.com/chat/completions`
endpoint through the existing httpx dependency, using JSON mode, thinking
disabled, no streaming, and a bounded output. The HTTP connect/read/write/pool
timeouts default to 20 seconds each; this is an HTTP I/O timeout, not an absolute
whole-turn wall-clock deadline. There are no automatic retries. Injected HTTP
clients belong to their caller; the context manager closes internally owned ones.

References checked September 27, 2026:
- [Models and pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)

## Conversation rules

- The speaker is Traveler A; their companion is Traveler B. Names are labels;
  ambiguous or duplicate-name references require clarification. Explicit “both”
  can update both travelers.
  A traveler can refer to themselves by their unique current display name instead
  of “I”; the prompt maps that name case-insensitively to its existing traveler ID.
  Mentioning a name does not rename a traveler or imply they are the companion.
  Unknown names and guessed nicknames require clarification. Name interpretation
  remains model-driven, rather than a complete deterministic identity resolver.
- The prompt receives the reference date in `America/Los_Angeles` and a computed
  `next_weekdays` mapping for all seven weekdays strictly after today. “Next Monday”
  on a Monday means seven days later; the same rule applies to every weekday.
  A supplied clock makes tests repeatable. V1 requires exact dates: missing or
  incomplete dates require clarification, including an absolute date without a
  year. The model must not assume the current year or invent a missing trip date.
  Explicit relative expressions such as “next Tuesday” can resolve to exact dates.
  Past dates are rejected, not rolled forward. Combined dates must span 3–7
  calendar days, inclusive, including when only one date changes.
- Budgets mean per-person round-trip airfare in USD. Ambiguous combined budgets,
  whole-trip budgets, and unsupported currencies require clarification.
- Origins remain free text. The adapter does not resolve or assign origin IDs.
- Vocabulary and qualitative temperature ranges follow the existing preference
  contract. Documented synonyms: beaches → beach, great restaurants → food,
  clubbing → nightlife, hiking → outdoor_activities, parks and scenery → nature.
- Unmentioned values are omitted. Nulls and empty lists are explicit clears,
  never implicit defaults. Always serialize with `exclude_unset=True` when
  consuming sparse results; `exclude_none=True` would lose clear operations.

## Add, update, remove

The private model response contains ordered operations with `op`, `field_path`,
`value`, and an exact quote from the current message as `evidence`:

- `set` updates/replaces a field with a non-null value.
- `add` appends controlled interest tags without removing existing ones.
- `remove` with a tag list removes only those tags.
- `remove` with null clears a field (an empty list for interests).

The adapter validates and applies these to a temporary representation, then
returns only the affected fields through the existing sparse draft contract.
For example, adding beaches to museums returns `["museums", "beach"]`; clearing
temperature returns explicit `temperature_range: null`. No session merge changes
are needed for these representations. Sequential operations on a field are
applied in order; an invalid operation discards all edits to that field for the
turn while retaining valid independent fields.

## Validation and failures

JSON mode alone does not establish schema or semantic correctness. The adapter
checks the response envelope, complete finish reason, exact response structure,
field-path allowlist, evidence presence, controlled tags, strict field types,
numeric limits, temperature bounds, and date constraints. The model cannot write
traveler IDs or resolved origin IDs. Unknown paths, malformed output, or evidence
not found in the message reject the entire response. Structurally valid responses
with invalid individual field values retain valid siblings and report field
issues; explicit issues override conflicting updates.

A live test exposed a first-person budget incorrectly assigned to both travelers.
The prompt now explicitly distinguishes singular and shared ownership. A narrow
validation check also rejects a companion edit whose evidence refers only to the
speaker, with no shared or companion reference. This is not general language
understanding; ambiguous references still require model-driven clarification.

Quoted evidence and prompting reduce unmentioned updates but do not prove a
model interpreted a sentence correctly. The live smoke cases exercise language
behavior; offline tests exercise the adapter boundary. Human review remains
required before recommendation confirmation.

Out-of-scope requests without a trip field (e.g. hotels) are returned in
`unsupported_requests`, with `user_text` and `explanation`; no fake field path is
created. Issues about supported fields remain in `missing_fields`. Either makes
status `needs_clarification`. The adapter also reports required fields absent
from the merged draft, without populating those fields. Status is advisory:
origin resolution and session readiness remain application responsibilities.

Errors expose no provider response body or key:

- `DeepSeekConfigurationError`: missing/invalid settings, authentication failure,
  or rejected request; operator action required, `retryable=False`.
- `DeepSeekUnavailableError`: timeout, transport failure, 429, or 5xx;
  `retryable=True`, with a safe try-again message.
- `DeepSeekResponseError`: malformed, truncated, or unsafe output;
  `retryable=True`.

The session layer catches these errors and preserves saved state. It adds bounded
retries for temporary failures, a total caller deadline, clarification context,
and unsupported-request acknowledgement. These policies are separate from the
standalone adapter. See [session configuration](deepseek-planning-sessions.md).

## Tests

For saved, repeatable evaluations and before/after comparisons, use the
[evaluation guide](../evals/preference_extraction/README.md). It includes a fixed
dataset, a five-turn conversation, two repetitions, and per-case JSON reports.
See the [first live baseline](../evals/preference_extraction/runs/baseline-v1.md)
for results and the limitations found during human review.

Offline checks (all provider calls use `httpx.MockTransport`):

```sh
.venv/bin/python -m pytest tests/test_deepseek_preference_extraction.py
```

The opt-in script makes thirteen real, potentially billable requests using synthetic
messages and a fixed example draft. It prints results and checks expected sparse
updates for budgets, add/replace/remove, relative dates, unsupported requests,
synonyms, and qualitative temperature. Each case starts from the same draft.
It exits nonzero on a mismatch or provider error; it is not collected by pytest.

After exporting `DEEPSEEK_API_KEY` in your shell:

```sh
.venv/bin/python -m travel_ai.scripts.deepseek_extract --live
```

Without `--live`, the script exits before constructing the adapter or making any
request. Do not treat successful mocked tests as a live model accuracy benchmark.
