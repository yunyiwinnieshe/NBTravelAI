# DeepSeek planning sessions

Planning sessions now select extraction through configuration. DeepSeek interprets
messages; application code validates and saves sparse updates. The deterministic
recommendation service is unchanged and runs only after explicit confirmation.

## Run locally

Set these variables in the server process environment (a `.env` file is not
loaded automatically):

```sh
export EXTRACTION_PROVIDER=deepseek
export DEEPSEEK_API_KEY='<your key>'
export DEEPSEEK_TIMEOUT_SECONDS=20
export DEEPSEEK_MAX_RETRIES=1
export DEEPSEEK_TOTAL_TIMEOUT_SECONDS=30
.venv/bin/python -m uvicorn travel_ai.main:app --reload
```

Keep real credentials outside source control. `DEEPSEEK_MODEL` uses the adapter's
configured default, `deepseek-flash`. With `EXTRACTION_PROVIDER=fixture` (the
default), sessions use deterministic fixture messages without provider calls.
Invalid provider settings or a missing required key fail at application startup;
a DeepSeek configuration never silently falls back to fixture interpretation.

The session service receives the chosen extractor through its constructor.
`SessionPreferenceExtractor` adds the session retry/deadline policy around the
standalone adapter. All extractors expose `extract(message, draft, context=None)`;
standalone calls can omit context, while sessions supply clarification context.
Fixture extraction accepts the same argument but uses predefined results. The API owns and closes the configured service at shutdown.

## Conversation behavior

- Valid mentioned fields update the draft; unrelated saved values and assigned
  traveler IDs stay intact. Ambiguous or invalid values trigger clarification.
- Replies include up to three pending field questions, prioritizing required
  information. DeepSeek receives those questions and their original source
  messages, when available, so short replies can be interpreted in context.
  A short answer that could apply to multiple travelers must be clarified.
- Unsupported requests are displayed and retained. The reply includes up to two
  field questions alongside the unsupported-request acknowledgement prompt.
- `{"action":"continue_without_unsupported"}` acknowledges all current notices.
  Explicit natural-language agreement can also acknowledge notices using their
  validated IDs and evidence from the current message. Deferred requests appear
  in the review summary. A supported correction can resolve a field notice.
- Continuing without unsupported requests does not confirm the trip. Only
  `{"action":"confirm"}` starts recommendations. Ordinary text never confirms.
- Corrections require another review and confirmation. Repeating confirmation
  on an unchanged request returns the cached recommendation result.

Create a session with `POST /trip-sessions` and an `initial_message`; send later
messages or actions to `POST /trip-sessions/{session_id}/messages`. Each message
request accepts exactly one of `message` or `action`. Responses include
`pending_questions`, `unsupported_requests`, and `deferred_requests` alongside
the draft, assistant message, and state.

## Failure behavior

Each message is applied to an isolated candidate. The service commits it only
when extraction, validation, and merging succeed. Errors preserve the saved
draft, pending notices, review state, and any cached recommendations. A failed
initial message removes the newly allocated session.

Timeouts, network errors, HTTP 429, and provider 5xx errors may retry. The default
is one retry (two attempts); `DEEPSEEK_MAX_RETRIES` permits 0–2. Authentication,
configuration, and malformed/invalid structured responses are not retried.

`DEEPSEEK_TIMEOUT_SECONDS` controls the adapter's HTTP I/O timeout.
`DEEPSEEK_TOTAL_TIMEOUT_SECONDS` limits caller waiting across attempts, defaults
to 30 seconds, and accepts positive values up to 120. Retry delay is 0.25 seconds.
The wrapper permits four in-flight extractions; additional requests fail fast.
A synchronous HTTP request can continue after the caller deadline, but its late
result is discarded and cannot update the session. Shutdown waits for workers
before closing the HTTP client.

API errors contain safe text and a machine-readable code in `detail`:

- HTTP 503, `extraction_unavailable`: temporary failure; ask the user to retry.
- HTTP 502, `extraction_invalid_response`: invalid provider output; the user can
  try again, although the application does not automatically retry this error.
- HTTP 503, `extraction_configuration`: operator intervention required.

Provider response bodies and credentials are not exposed in these errors.

## Tests and recorded evidence

Validation on September 28, 2026: **349 tests passed**; Ruff lint and formatting
checks passed. Eight dependency deprecation warnings remain.

Run offline validation with:

```sh
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
```

The test suite selects fixture extraction by default. DeepSeek session tests
use mocked HTTP transport, exercising the real adapter, retry wrapper, API,
session service, and deterministic recommendations without network calls.
They cover corrections, clearing, short answers, missing years, unsupported
acknowledgements, confirmation, provider failures, invalid output, retries,
late responses, and atomic state preservation during merge failures.

For an opt-in real-provider walkthrough, start the server with DeepSeek enabled,
then run (this incurs provider usage):

```sh
.venv/bin/python -m travel_ai.scripts.deepseek_session_smoke \
  --live --base-url http://127.0.0.1:8000 \
  --output evals/preference_extraction/runs/session-wiring-next.json
```

Use a new output filename for every run. The script refuses to overwrite old
reports and saves requests, responses, timestamps, and pass/fail checks. It does
not save API credentials. Keep the messages synthetic because reports contain
conversation text.

The [first saved live run](../evals/preference_extraction/runs/session-wiring-v1.json)
passed all nine HTTP steps on September 28, 2026: partial creation, a short budget
answer, adding an interest, a correction with an unsupported hotel request,
blocked confirmation, explicit deferral, confirmed recommendations, lowering
both budgets, and confirmed `no_match`. This is one successful smoke run, not a
statistical estimate of model reliability. Compare future reports using the same
messages, and use the separate [adapter evaluation](../evals/preference_extraction/README.md)
for broader extraction cases.

## Current limits

Session origins remain Boston and New York. Airport/location expansion is a
separate ticket. Recommendations use fixture flights; the walkthrough uses
June 10–14, 2099 to match them. Other valid dates can produce `no_match`.
Sessions and cached results live in memory and disappear on restart; multiple
server processes do not share sessions. Persistent storage and the fuller
Postman/evaluation-case walkthrough remain separate work.
