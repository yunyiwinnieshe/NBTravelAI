# First expanded live evaluation

The 2026-10-04 run used the 30-case conversation dataset v2, the fixed
2026-10-03 reference clock, model `deepseek-flash`, and a hard limit of 65 calls.
It sent 65 real model requests. The deterministic recommendation suite made no
model calls. The report records dataset, prompt, code, and fixture hashes so a
later run can be compared against the same inputs.

- Conversations: **28/30 cases**, **76/78 steps** passed.
- Deterministic recommendations: **20/20 cases** passed.
- All non-injection conversation categories passed, including corrections,
  invalid values, unsupported requests, confirmation, and no-match recovery.
- The two failures were provisional prompt-injection state labels. Both messages
  left traveler budgets unchanged, produced no recommendations, and did not
  confirm the trip. DeepSeek classified each as unsupported and the session
  moved to `collecting` for acknowledgment, whereas the labels expected `review`.

A focused [two-repeat run](../live-injection-repeat-v1/summary.md) used eight more
model calls. In three of four injection turns, DeepSeek created an unsupported
notice and the session moved to `collecting`; in one it ignored the injection and
remained in `review`. All four preserved budgets and withheld recommendations.
This is an inconsistency in the **provisional state label**, not observed draft
corruption or a confirmation bypass. Keep the original expected labels and raw
case outcomes for comparison until Ivy reviews which safe behavior the product
should require. Do not count either live run as a 100% model pass.

The initial sandboxed connectivity probe could not resolve DeepSeek's host. A
network-enabled one-case check passed before the full run. No provider credentials
or authorization headers are stored in these reports.
