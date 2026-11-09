# Recommendation evaluation cases

`cases.v1.json` contains 20 synthetic, versioned requests evaluated by the
deterministic recommendation service. The evaluation runner applies the fixed
`2026-10-03` reference date and existing flight, airport, city, and climate
fixtures. It compares saved outcome and eligible/excluded destination IDs, and
checks that every displayed flight option respects its traveler's budget and
one-way travel-time limit. Invalid requests must fail validation before a
recommendation is requested.

The three preference cases carry `label_status: reviewed` and `reviewer: Ivy`.
Ivy approved their ranking behavior because it treats preferences as soft
signals and balances them against airfare, travel time, and fairness. No ranking
formula was changed to make these examples pass.

Run both this dataset and the 30 conversation cases with one offline command:

```sh
.venv/bin/python -m travel_ai.scripts.evaluate_sessions
```

The report keeps conversation and deterministic recommendation results in
separate sections. See [the runner guide](../evaluation-runner.md) for live-model
controls, version hashes, and result interpretation.
