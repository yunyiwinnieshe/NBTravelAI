# Travel AI - LLM Selection for Structured Preference Extraction

**Owner:** Winnie  
**Decision date:** August 19, 2026  
**Status:** DeepSeek selected for low-cost initial testing; benchmark decision
required before production use

## Decision

Use **DeepSeek V4 Flash in non-thinking mode** for initial structured
preference-extraction tests and development. Use **OpenAI GPT-5 mini** as the
quality benchmark. Select the later default only after the benchmark gate in
this document passes.

This is a narrowly scoped choice. The model receives a natural-language trip
request and returns a typed draft of `TripRequest` or a clarification need. It
does not retrieve travel data, decide eligibility, calculate a score, or
override deterministic results. Pydantic validation remains required after
every response.

The selection is reversible: the LLM sits behind a `PreferenceExtraction`
provider interface, while the canonical request schema and downstream ranking
engine stay provider-independent.

## Options reviewed

### 1. DeepSeek V4 Flash - selected for initial testing

- **Structured output:** Supports JSON Output. This guarantees valid JSON but
  not full schema compliance, so Pydantic validation remains mandatory.
  Strict JSON-schema tool calls exist but are beta and are not required for the
  first prototype.
- **Cost:** $0.14 per 1 million cache-miss input tokens and $0.28 per 1
  million output tokens at the documented standard rate.
- **Latency:** Run in non-thinking mode for this narrow extraction task and
  measure p50/p95 latency with the shared benchmark set.
- **Python SDK:** Its API is compatible with the OpenAI SDK by changing the
  base URL, which keeps the prototype small.
- **Logging:** Capture the provider model/version, response usage,
  validation outcome, latency, retries, and estimated cost in our own wrapper.

Sources: [models and pricing](https://api-docs.deepseek.com/quick_start/pricing/), [JSON Output](https://api-docs.deepseek.com/guides/json_mode/), [strict tool-call mode](https://api-docs.deepseek.com/guides/tool_calls), and [Python/OpenAI SDK compatibility](https://api-docs.deepseek.com/quick_start/).

### 2. OpenAI GPT-5 mini - quality benchmark

- **Structured output:** Supports Structured Outputs, which fits a Pydantic
  `TripRequest` contract.
- **Cost:** $0.25 per 1 million input tokens and $2.00 per 1 million output
  tokens at the documented standard rate.
- **Latency:** OpenAI describes it as faster and cost-efficient for
  well-defined tasks and precise prompts. We will still validate this claim
  with our own p50/p95 benchmark before treating it as a product target.
- **Python SDK:** The official Python SDK and Responses API are a direct fit
  for the Python/FastAPI backend.
- **Logging:** Our wrapper will record response ID, model snapshot, prompt
  version, schema-validation result, token usage, latency, retry count, and
  estimated cost. These fields are application-owned, so the same trace format
  remains usable if we change providers.

Sources: [model capabilities and pricing](https://developers.openai.com/api/docs/models/gpt-5-mini), [Structured Outputs overview](https://platform.openai.com/docs/guides/structured-outputs), and [model/Client SDK overview](https://developers.openai.com/api/docs/models/models-overview).

### 3. Gemini 2.5 Flash-Lite - cost-focused alternative

- **Structured output:** Gemini supports response schemas and its Python SDK
  accepts a Pydantic model as the response schema.
- **Cost:** $0.10 per 1 million text/image/video input tokens and $0.40 per 1
  million output tokens at the documented paid rate.
- **Latency:** Google positions Flash-Lite for cost-efficient, at-scale use;
  use the shared benchmark rather than treating this positioning as a measured
  latency result for Travel AI.
- **Python SDK:** The official `google-genai` Python examples use a Pydantic
  response schema, so it is technically compatible with our backend.
- **Logging:** Use the provider-neutral wrapper described below to capture
  request metadata and response usage without storing sensitive free-text
  requests by default.

Sources: [model capabilities](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash), [pricing](https://ai.google.dev/gemini-api/docs/pricing), and [Python structured-output example](https://ai.google.dev/gemini-api/docs/migrate-to-interactions#structured-output).

## Why DeepSeek V4 Flash is used first

DeepSeek V4 Flash has substantially lower documented output-token pricing than
GPT-5 mini and is compatible with the OpenAI Python SDK, making it suitable
for repeated, low-cost development experiments. Its normal JSON Output mode is
not a substitute for schema validation, which is why Pydantic validation and
the benchmark gate are non-negotiable.

GPT-5 mini is retained as a quality benchmark because it supports Structured
Outputs. Gemini Flash-Lite remains a lower-cost comparison point. This is not
a claim that DeepSeek is universally best; it is a pragmatic testing choice.

## Benchmark gate before production use

Before the model is connected to the recommendation workflow, run the same
versioned set of 30-50 representative prompts through each candidate. Include
complete requests, missing fields, ambiguous preferences, conflicting
constraints, and adversarial text.

Record, per model:

- Schema-valid rate after provider output and Pydantic validation.
- Required-field accuracy and clarification relevance.
- Unsafe or unsupported-field rate.
- p50 and p95 end-to-end latency in milliseconds.
- Input/output tokens and estimated cost per successful extraction.
- Retry, refusal, timeout, and provider-error rate.

Promote DeepSeek V4 Flash to the default only if it meets the Week 4 quality
bar and has acceptable latency and cost. Otherwise, use the best measured
alternative and record the decision in the project decision log.

## Logging and privacy requirements

Every extraction call must write a structured event with:

- `request_id`, provider, model ID or snapshot, and prompt version.
- Start/end timestamps, latency, retry count, and cache status if applicable.
- Input/output token counts and estimated cost.
- Schema-validation outcome, missing fields, and failure category.
- A redacted request summary rather than raw user text by default.

Never log API keys. Do not log full travel requests or other personal data in
production unless a documented retention policy and user consent make that
necessary. The LLM trace should point to the deterministic recommendation run,
but it must not duplicate private data unnecessarily.
