# Control-message safeguard: live verification

On 2026-10-04, the 30-case conversation dataset v2 passed **30/30 cases** and
**78/78 steps** against `deepseek-flash`. The bounded run sent 63 real model
requests. The 20 deterministic recommendation cases passed without model calls.
The two control-only messages were handled before model extraction, stayed in
`review`, preserved both budgets, created no unsupported notice, and produced no
recommendations. Genuine unsupported travel requests still followed the
acknowledgment flow in this run.

The [original expanded live baseline](../live-expanded-v1/analysis.md) had
28/30 conversation cases because DeepSeek variably treated the two control
messages as unsupported requests. A [prompt-change experiment](../live-control-guard-v2/summary.md)
fixed those two states but missed a temperature-ownership case. The prompt edit
was removed, leaving the prior prompt and the narrow deterministic safeguard.
The affected temperature case then passed [three fresh live repetitions](../live-temperature-repeat-v1/summary.md)
before this full rerun. These runs document the observed behavior; they do not
prove a general prompt-injection defense or a stable model accuracy rate.

The report contains synthetic conversation text, expectations, actual session
outcomes, checks, and version hashes. It contains no API key or authorization
header. The dataset's three subjective labels remain marked provisional for
Ivy's review.

After this live run, the narrow guard was refined to let messages with genuine
trip details reach extraction even when they also contain role-like wording.
That final refinement is covered by the [subsequent offline run](../../offline/runner-offline-v4/summary.md)
and the full unit suite (381 passed), but this live report's code hash identifies
the pre-refinement version. The saved injection messages take the same guarded
path in both versions.
