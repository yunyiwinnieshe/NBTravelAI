# DeepSeek extraction baseline v1

Run: September 28, 2026, 03:40–03:41 UTC (September 27, US Pacific time).
Model requested and returned: `deepseek-flash`.
Frozen interpretation date: September 27, 2026, America/Los_Angeles.

## Results

- **56/56 live turn attempts passed**, from 28 distinct turns run twice.
- **28/28 turns passed both repetitions** across 24 scenarios.
- Identity: 10/10; preferences: 10/10; dates: 14/14; clarification: 8/8;
  unsupported requests: 4/4; multi-turn conversation: 10/10.
- No provider errors. Median adapter-call latency: 1.041 seconds;
  maximum observed: 1.321 seconds. These are local measurements for this run.
- Full offline repository suite: **324 passed**, with six existing dependency
  deprecation warnings. Ruff lint, formatting, and Git whitespace checks passed.
- Offline coverage now includes a timeout followed by a successful explicit retry,
  five sequential edits, and grader checks that detect unwanted companion updates
  and regressions hidden by an unchanged aggregate score.

[Full machine-readable results and provider outputs](baseline-v1.json) contain the
case-level inputs, expected/actual outputs, state, timing, configuration and hashes.
The run used an uncommitted working tree; the report records that and source hashes.
No API key or request authorization header is included.

## Observed behavior

Both repetitions kept speaker-only and named-speaker edits on Traveler A, mapped
named-companion edits to Traveler B, and applied explicit shared budgets to both.
The five-turn sequence introduced Alex, added museums, added hiking, removed
museums, then corrected Alex's budget to $600. Hiking and the companion's draft
were preserved throughout.

All weekday expressions resolved to the expected dates. Missing-year and
month-only messages requested exact dates instead of guessing. Combined budgets
and duplicate names produced clarification without changing the draft. Hotel
requests retained the valid airfare edit and returned an unsupported notice.

## Human spot review and remaining gaps

I inspected the first repetition's clarification and unsupported-request wording,
in addition to the automated checks. These observations are **not** folded into
the automated pass rate:

- Missing-year and month-only questions directly asked for the needed details.
- The combined-budget question correctly asked about per-person versus combined
  allocation. Its wording did not explicitly clarify whether the amount covers
  airfare versus the entire trip; that remains worth testing more directly.
- Duplicate names triggered clarification, but “Which Alex?” would be more useful
  as “Do you mean you or your companion?”
- Unsupported explanations included technical phrases such as “canonical field”
  and “available trip fields.” They should use plain customer-facing language.

The semantic question-quality checks above are manual, not an automated guarantee.
The automated score measures exact updates, structural issue requirements and
state preservation; it is **not** a complete conversation-quality score.

## Interpretation

This is a small development regression baseline, not 100% production accuracy.
The dataset was authored with knowledge of the prompt and is not a held-out test
set. Two repeats provide limited evidence about variability. Broader paraphrases,
negation, changing speaker conventions, unusual names, currency ambiguity, and
prompt-injection attempts remain useful future evaluation categories.

No full API/session/UI end-to-end run was performed: dependency wiring, session
issue retention, origin resolution, and unsupported-request acknowledgments remain
outside this ticket. The conversation test uses a test-only sparse-draft merger.

## How to evaluate the next change

Use the [evaluation guide](../README.md) to run the same dataset and grader into a
new report and compare against `baseline-v1.json`. Review per-case regressions as
well as the aggregate score. Do not overwrite this report or silently change the
expected outputs to make a candidate pass. Changes to the dataset or grader need
fresh baseline and candidate runs under the same evaluation version.
