# Planning conversation evaluations

This is the session-level companion to the existing
[extractor evaluations](../preference_extraction/README.md). It calls the real
HTTP API and checks saved drafts, clarification state, confirmation, and fixture
recommendations. The extractor dataset tests interpretation in isolation;
these cases test the full conversation.

## Cases and expectations

`cases.v1.json` contains 12 independent scenarios (34 requests total): complete
requests, missing one/multiple fields, short answers, budget corrections,
adding/replacing/clearing interests, ambiguous ownership, incomplete dates,
unsupported requests, explicit exclusion, and `no_match`.

Each case starts a fresh session. Each step declares its request and expected
HTTP status/state. Optional expectations check specific draft fields, missing
field paths, unsupported/deferred notices, and preservation of unrelated fields.
Interest order does not matter. Exact generated clarification wording is not
asserted; manually judge clarity in the walkthrough. These are synthetic examples,
not a representative production benchmark.

`assertions.js` provides shared Postman assertions. Generate both the v3 local
collection and the v2.1 desktop-importable export after changing cases/assertions:

```sh
.venv/bin/python -m travel_ai.scripts.build_conversation_collection
postman collection lint 'postman/collections/Planning conversations'
postman environment lint 'postman/environments/Travel AI local.environment.yaml'
```

JSON syntax in `.yaml` files is intentional: JSON is valid YAML. Edit the dataset
and shared assertion file, not the generated requests. If removing cases or
steps, also remove their stale generated request files before regenerating.

## Run and compare

Follow [the Postman walkthrough](../../docs/postman-conversation-walkthrough.md).
Every run should use a new report directory. Record model, timeout/retry settings,
Git revision and any uncommitted implementation changes, dataset hash, repetitions,
and CLI version. Record case-level results as well as assertion counts: many
passing setup assertions can otherwise hide a failed conversation.

Keep expectations stable when comparing prompt/code changes. Do not remove a
failing assertion to make a run green. Keep old reports and link known failures
to their cases. Compare model failures separately from provider/network failures.
Automated offline tests continue to use fixtures or mocked provider responses;
a live run can incur model usage and can vary across repetitions.

## First live experiment

- DeepSeek model: `deepseek-flash`; Postman CLI: `1.69.0`.
- One complete run: **11/12 cases passed; 328/330 assertions passed**.
- All 34 requests completed; expected HTTP 422 confirmation rejections passed.
- Confirmed recommendations and confirmed `no_match` both passed.
- Case `09_missing_year` failed two assertions: after `2099`, the departure date
  stayed June 10 instead of June 11, and the session stayed in `collecting`.
- A targeted fresh-session repetition reproduced the same failure (31/33
  assertions passed). It is not a second repetition of the whole dataset.
- No timeout or provider/authentication failure was observed in these runs.

Evidence:

- [Case-level results](runs/live-v1/results.json)
- [Run configuration and source hashes](runs/live-v1/metadata.json)
- [Postman transcript](runs/live-v1/postman-console.txt)
- [Diagnostic API responses](runs/year-diagnostic-v1/responses.json)
- [Known failure history](known-failures.json)

The root cause of the date failure is not yet isolated. These API responses
cannot prove whether the model, normalization, or session merge is responsible.
The previous valid draft was preserved. A follow-up fix should inspect the raw
structured output and add a regression test. This evaluation intentionally leaves
the failure visible.

Postman's `--output` report export required separate CLI authentication. Local
collection execution with `--no-report-events` succeeded without it. The saved
transcript and derived `results.json` provide local evidence; nothing was pushed
to the cloud workspace. Raw responses were captured only for the targeted
diagnostic. Each run used synthetic messages and no credentials in Postman.

## Follow-up: clarification prompt fix

The original prompt returned correct updates in three later instrumented runs
(`year-trace-baseline`, `year-trace-baseline-2`, `year-trace-baseline-3`). Each trace
records model output, normalization, and final API state with no credentials.
Those successes establish that the existing merge path can apply this correction;
they do not identify the exact cause of the earlier failures.

The revised prompt resolves conflicting instructions about editing only fields
mentioned in the current message versus using pending questions for short replies.
It explicitly combines the proposed month/day from the pending correction with the
current year answer, even when that year equals the old saved year. The old
source message's statement that the year is missing does not override the new
answer. Evidence still quotes the current reply, and ambiguous targets still
require clarification. No blind four-digit-year parser or validation bypass was
added.

Verification with unchanged case expectations:

- [Targeted Postman run](runs/year-fix-v1/results.json): 3/3 fresh sessions passed,
  99/99 assertions.
- [Full Postman run](runs/live-v2/results.json): 12/12 cases passed, 330/330
  assertions, including recommendations and no_match.
- 354 offline tests passed; lint and formatting checks passed. Regression checks
  cover clearing the resolved issue, preserving unrelated fields, invalid/past
  dates, an empty model result, multiple possible dates, and no pending question.

The historical failure is marked mitigated with passing verification, not erased.
The old prompt also passed later reruns, so these small samples do not prove a
statistical improvement or guarantee all future model responses will succeed.

## Offline-first runner

The [evaluation runner](../evaluation-runner.md) now defaults to
`cases.v2.json`: the 12 original cases plus 18 new scenarios for invalid
corrections, companion ownership, unsupported requests, confirmation, no-match
recovery, and prompt injection. `offline-responses.v2.json` contains separately
authored mock model outputs. Cases `24`, `29`, and `30` have provisional labels
for Ivy to review. The v1 file remains the source for the existing Postman
walkthrough and historical live results. Real DeepSeek runner calls require
`--live` and an explicit `--max-calls`.
