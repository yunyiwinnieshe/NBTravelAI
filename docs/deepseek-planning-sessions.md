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

Session storage is also constructor-injected through the minimal
`PlanningSessionRepository` contract (`create`, `get`, and `save`). Its strict,
JSON-serializable `PlanningSessionRecord` includes schema version, revision,
timezone-aware UTC timestamps, the structured draft and workflow state, limited
question/unsupported/deferred text needed to continue, and the exact confirmed
result. Thread locks remain process-local and are never serialized. The default
`InMemoryPlanningSessionRepository` stores defensive copies and rejects stale
revisions. Setting `PLANNING_SESSION_DB_PATH` selects the durable
`SQLitePlanningSessionRepository`; leaving it unset keeps the process-local
adapter for isolated development and tests.

Session mutations use an explicit transaction-like flow: load the saved record,
make and validate a deep candidate copy, apply the change, validate and save the
candidate, and only then return its response. Extraction, recommendation, record
validation, or repository-save failures therefore leave the previously saved
record unchanged. Messages that do not change durable state and duplicate
confirmations do not create unnecessary revisions.

The SQLite adapter uses WAL mode, a bounded one-second lock wait by default, and
`BEGIN IMMEDIATE` transactions. Saves update only the expected revision; if
another process has already advanced it, the repository raises
`PlanningSessionConflictError` rather than overwriting newer state. The HTTP
API reports that conflict as 409 and asks the caller to reload instead of
automatically repeating model or recommendation work.

A confirmed result is stored as the exact historical `ConversationTurnResponse`,
not regenerated when the session is loaded again. The snapshot includes ranked
destinations, prices, the recommendation `data_mode`
(`fixture` or `live`), and its original `evaluated_at` evidence timestamp.
A later session save never replaces that evidence time with `updated_at`.
Duplicate confirmation returns the stored snapshot without another provider or
recommendation call; editing the draft still clears it and requires a new
confirmation.

Restart acceptance tests create fresh application and service instances against
the same temporary SQLite file. They cover incomplete drafts and questions,
continuation through confirmation, unsupported and deferred requests, exact
confirmed snapshots, unknown IDs, failed extraction and recommendation calls,
duplicate confirmation, stale concurrent writes, corrupt or unsupported stored
records, and provider secrets remaining absent from the database. Invalid stored
records raise `PlanningSessionDataError`; the API returns a non-retryable 503
without exposing the stored payload.

## Operational limits

### Database location and initialization

- If `PLANNING_SESSION_DB_PATH` is unset, the application uses process-local
  memory. Those sessions disappear when the process stops and are not shared
  between server processes.
- If it is set, the value is the SQLite database file path. A relative path is
  resolved from the server process's working directory. The parent directory
  must already exist and be writable. The durable adapter rejects `:memory:`.
  This setting is independent of `ORIGIN_LOCATION_DB_PATH`.
- Storage configuration is created when the service is first constructed and
  cached for that process. Restart the server after changing the environment.
- On startup, the SQLite adapter enables WAL mode and runs `CREATE TABLE IF NOT
  EXISTS planning_sessions`. The table stores the session ID, record schema
  version, optimistic revision, creation and update timestamps, and the full
  validated record as JSON. It does not alter an existing table.

### Schema and migrations

The current durable record schema is version 1. There is no migration runner,
automatic upgrade, or downgrade path yet. A corrupt record or an unsupported
schema version fails safely with `PlanningSessionDataError` rather than being
partially loaded. Before an incompatible schema change, back up the database and
provide and test an explicit migration.

### Retention and personal data

There is no delete repository operation, time-to-live, scheduled cleanup, or
archive job. SQLite records remain until an operator removes or replaces the
database; in-memory records last only for the process lifetime.

The stored record can contain traveler display names, origin text and normalized
origin IDs, dates, budgets, travel-time limits, interests and preferences,
pending question text, limited source-message excerpts used for clarification,
exact unsupported or deferred request text, and the exact confirmed
recommendation response. The confirmed response includes destinations, scores,
prices, flight details, its fixture/live source label, and its evidence
timestamp.

Provider credentials are not intentionally stored, and restart tests scan the
database for configured DeepSeek and Duffel secrets. However, arbitrary
sensitive text entered by a user can be retained when it becomes clarification,
unsupported, or deferred context. Treat the database as personal data. The
application does not encrypt it at rest or implement access control.

### Backup and recovery

The application does not create backups or restore them. In WAL mode, active
state can also exist in the database's `-wal` and `-shm` files, so copying only
the main file while writes are active is not a reliable backup. Operators should
use SQLite's backup mechanism, stop and checkpoint the application, or take a
consistent snapshot of all database files. Backup frequency, encryption,
retention, access control, and restore testing are deployment responsibilities.

### Concurrency and unavailable storage

- A process-local lock serializes changes to one session inside one service
  process. Across processes, SQLite permits one writer at a time and the
  revision check rejects stale saves instead of losing a newer update.
- The default SQLite lock wait is one second. The service does not automatically
  retry a stale revision or a database lock timeout. Stale HTTP updates return
  409 so the caller can reload. SQLite storage is intended for a small,
  single-host demo, not a high-write distributed deployment.
- If the database directory is missing, permissions are insufficient, or the
  file cannot be opened or initialized, application startup fails. It does not
  silently fall back to memory.
- A runtime SQLite failure returns a retryable 503 through the existing shared
  storage-error handler. That handler's current error code and message are
  origin-storage-specific even when session storage failed; separating those
  responses is a known reliability follow-up. Corrupt or unsupported session
  data instead returns the non-retryable `planning_session_data_invalid` 503.
  There is no automatic repair, but a failed save leaves the previously
  committed session unchanged.

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

Fixture mode session origins remain Boston and New York. Opt-in Duffel Places
resolution accepts verified US city/state or airport input, but recommendations
still use fixture flights; see [the setup guide](planning-origin-resolution.md).
The walkthrough uses
June 10–14, 2099 to match them. Other valid dates can produce `no_match`.
Without `PLANNING_SESSION_DB_PATH`, sessions and cached results still live only
in memory. SQLite mode adds restart persistence for a small, single-host demo
but keeps the operational limits documented above.
