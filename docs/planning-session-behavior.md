# Planning-session behavior

**Status:** Agreed behavior for the planned conversational API; implementation
is a follow-up.

This document defines how a trip-planning session collects and updates a draft,
asks for clarification, requests confirmation, and starts deterministic
recommendations. It supplements the endpoint outline in `docs/api-outline.md`.

## Session states

- `collecting`: At least one required value is missing, ambiguous, or invalid.
  The app saves any other valid values and asks one focused question.
- `review`: All required values are valid. The app shows the complete normalized
  request and waits for explicit confirmation.
- `results`: The user confirmed the current request revision and at least one
  eligible destination was found.
- `no_match`: The user confirmed the current request revision, but no fixture
  destination satisfied the constraints. This is a successful evaluation, not
  a service failure.

Recommendations run only on an explicit confirmation of a complete, unchanged
request. They never run in `collecting` or `review`.

## Shared behavior rules

### Required and optional information

The session requires exact trip dates and, for each of exactly two travelers:

- a resolved origin;
- an individual round-trip airfare budget in USD; and
- a maximum one-way itinerary duration, including layovers.

The confirmed trip must satisfy the canonical request rules, including a future
trip lasting 3–7 calendar days. Preference values are optional. A traveler may
provide a temperature range, interest tags, both, or neither. When no
preferences were provided, the review summary says so; confirmation accepts
that omission.

Each traveler has a stable internal ID such as `traveler_a` and may also have a
display name such as Alice. Corrections using the display name update the
corresponding stable traveler record.

### Saving and clarifying information

- A message may fill or update several fields.
- Valid values are saved even when another value in the same message is invalid
  or unclear.
- An invalid or ambiguous value is not saved over a previously valid value.
- Values not mentioned by the user remain unchanged.
- If several issues remain, the app asks one focused clarification question at
  a time. Hard constraints are clarified before optional preferences.
- Unsupported preferences are explained rather than silently ignored.

### Origin resolution

Free text is resolved before the request reaches deterministic recommendation
code. If the text has one supported fixture interpretation, the session saves
the canonical fixture ID; for example, `Boston` becomes `boston_ma` and
`New York` becomes `new_york_ny`. The review summary shows both the readable
place and its resolved ID.

If text is ambiguous, such as `Vancouver`, the app stays in `collecting` and
asks the user to identify the intended place. If the resolved place is not
supported by the fixture provider, the app asks for a supported origin. It does
not silently substitute another city.

The product behavior allows both travelers to use the same origin. The current
`TripRequest` validator still requires distinct origins, so that validator must
be aligned before the session API implements this rule.

### Review, confirmation, and later changes

The review summary shows exact dates and, for each traveler, the display name,
resolved origin, airfare budget, one-way travel-time limit, and any preferences.
It also states when no preferences were provided.

Confirmation is a structured action sent to the message endpoint, not merely a
phrase inferred from ordinary text:

```json
{
  "action": "confirm"
}
```

The eventual message-request contract must accept exactly one of `message` or
`action`. `confirm` is accepted only while the current request is complete and
in `review`.

Any changed detail invalidates the prior confirmation. A complete changed
request returns to `review`; an incomplete or invalid changed request returns
to `collecting`. Recommendations do not rerun until another explicit
confirmation. This also applies to changes made after `results` or `no_match`.

Repeating `confirm` without changing the request returns the existing result
rather than starting a duplicate recommendation run.

## Example conversations

The saved information below is abbreviated to the fields relevant to each
turn. `Recommendations run` means the deterministic recommendation workflow,
not LLM extraction or validation.

### 1. Only some trip details are provided

**User says:** “Alice is flying from Boston and Bob is flying from New York.
We want to travel June 10–14, 2099.”

- **App saves:** Alice as `traveler_a` with origin `boston_ma`; Bob as
  `traveler_b` with origin `new_york_ny`; start date `2099-06-10`; end date
  `2099-06-14`.
- **Still missing or unclear:** Both budgets and both maximum one-way travel
  times.
- **State:** `collecting`.
- **App shows:** “What is Alice’s maximum round-trip airfare budget in USD?”
- **Recommendations run:** No.

### 2. A message contains an unclear budget

**Existing draft:** Both origins and dates are saved. Alice has a $500 budget
and a six-hour one-way limit; Bob has a six-hour one-way limit.

**User says:** “Bob wants something affordable, and we both like food.”

- **App saves:** The `food` interest for both travelers. It does not replace
  Bob’s budget with an inferred number.
- **Still missing or unclear:** Bob’s exact budget in USD.
- **State:** `collecting`.
- **App shows:** “What is the maximum round-trip airfare Bob is willing to pay
  in USD?”
- **Recommendations run:** No.

### 3. All required details are supplied without preferences

**User says:** “Alice will leave from Boston with a $500 budget and a six-hour
one-way limit. Bob will leave from New York with a $450 budget and a five-hour
limit. Travel June 10–14, 2099.”

- **App saves:** Both resolved origins, both exact budgets, both travel-time
  limits, and both dates. No preferences are saved.
- **Still missing or unclear:** Nothing required. Preferences are optional.
- **State:** `review`.
- **App shows:** A complete summary, including “Preferences: none provided” for
  each traveler, followed by “Confirm this trip request to find destinations.”
- **Recommendations run:** No.

### 4. One traveler’s value is corrected during review

**Existing draft:** The complete request from Example 3 is in `review`.

**User says:** “Change only Alice’s budget to $600.”

- **App saves:** Alice’s budget becomes `$600`. Bob’s budget and every other
  saved field remain unchanged.
- **Still missing or unclear:** Nothing.
- **State:** `review`.
- **App shows:** The revised complete summary and asks for confirmation again.
- **Recommendations run:** No.

### 5. Explicit confirmation produces recommendations

**Existing draft:** A complete request is in `review`, using supported fixture
origins and constraints that allow at least one fixture destination.

**API receives:**

```json
{"action": "confirm"}
```

- **App saves:** The current request revision as confirmed and stores the
  recommendation result.
- **Still missing or unclear:** Nothing.
- **State:** `results`.
- **App shows:** The ranked eligible destinations and their flight options.
- **Recommendations run:** Yes, once for the confirmed request revision.

### 6. Explicit confirmation produces no eligible destination

**Existing draft:** A complete request is in `review`, but the saved budgets or
travel-time limits are too restrictive for every fixture destination.

**API receives:**

```json
{"action": "confirm"}
```

- **App saves:** The current request revision as confirmed and stores the
  successful empty recommendation result.
- **Still missing or unclear:** Nothing; the request itself is valid.
- **State:** `no_match`.
- **App shows:** “No fixture destination meets both travelers’ current
  constraints. You can adjust a budget, travel-time limit, date, or origin and
  try again.”
- **Recommendations run:** Yes. The workflow completed normally and found no
  eligible destination.

## Implementation boundary

These examples define product behavior, not storage technology or LLM prompt
wording. Winnie can choose the persistence mechanism and internal orchestration,
provided the public state transitions, saved-field behavior, explicit
confirmation gate, and `no_match` meaning remain the same.
