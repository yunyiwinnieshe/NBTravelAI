# Postman conversation walkthrough

Use the saved collection to explore session creation, messages, review,
confirmation, recommendations, and no_match. There are 12 independent scenario
folders. Run the requests within a folder in order; its first request creates a
fresh session and later requests automatically reuse the returned session ID.

## Start the backend

Configure the backend process with your own environment variables:

```sh
export EXTRACTION_PROVIDER=deepseek
export DEEPSEEK_API_KEY='<your current key>'
export DEEPSEEK_MODEL=deepseek-flash
export DEEPSEEK_TIMEOUT_SECONDS=20
export DEEPSEEK_MAX_RETRIES=1
export DEEPSEEK_TOTAL_TIMEOUT_SECONDS=30
.venv/bin/python -m uvicorn travel_ai.main:app --host 127.0.0.1 --port 8012
```

Do not put the real key into this document, the collection, or its environment.
The application does not automatically load `.env`. If using one locally, load
it explicitly through your chosen environment tooling. Requests from Postman
need no DeepSeek credential: the backend makes those provider calls.

These conversational messages require DeepSeek mode. The application's default
fixture extractor recognizes only its predefined fixture messages, so it cannot
interpret this live collection. The collection itself does not switch providers.

The examples deliberately use June 10–14, 2099 to match fixture flights. Boston
and New York are the supported departure cities. Recommendation results are
fixture-based even though language interpretation uses real DeepSeek.

## Open in Postman desktop

1. Import `postman/planning-conversations.postman_collection.json`.
2. Import `postman/travel-ai-local.postman_environment.json`.
3. Select **Travel AI local**. Its `base_url` is `http://127.0.0.1:8012`; change
   that value if the backend uses another port.
4. Open **Planning conversations**. Start with folder **01_complete**.
5. Send **Create session**. Expect HTTP 200 and `state: review`. Inspect
   `trip_request_draft` and the readable `assistant_message`.
6. Send **Text is not confirmation**. It must remain `review`, with an empty
   `recommendations` list. Ordinary text is not the structured confirmation action.
7. Send **Confirm reviewed trip**, whose body is `{"action":"confirm"}`.
   Expect `state: results` and a nonempty `recommendations` list.

The post-response scripts capture `session_id`; you do not have to copy it.
Review is a response state, not a separate endpoint in the current API.

Next try these folders:

- **04_short_answer**: the app asks for Alex's budget; sending `800` completes it.
- **05_correction**: Alex's budget changes to $600; Jamie's details stay intact.
- **10_unsupported**: the hotel limitation persists after another message and
  blocks confirmation with HTTP 422.
- **11_acknowledge**: explicitly continuing without the hotel request returns
  to review; a separate confirmation produces recommendations.
- **12_no_match**: start with a complete request, lower both budgets to $1, then
  confirm. Expect `state: no_match` and an empty recommendations list. This is a
  successful evaluation with no eligible fixture destination, not an API error.
- **09_missing_year**: checks the year-only correction regression. After the
  prompt fix it passed three targeted repetitions and the full collection. The
  earlier failure and verification remain in the evaluation history.

Use the collection runner to execute all folders. Inspect **Test Results** for
field/state assertions and read a few assistant replies for clarity. A passing
status code alone does not mean the model interpreted the message correctly.

## Repeat locally from the command line

Install the Postman CLI if needed (`npm install -g postman-cli`). Then run:

```sh
mkdir -p evals/conversations/runs/my-next-run
postman collection run 'postman/collections/Planning conversations' \
  -e 'postman/environments/Travel AI local.environment.yaml' \
  --no-report-events --timeout-request 40000 \
  > evals/conversations/runs/my-next-run/postman-console.txt 2>&1
```

Check the exit status and summary: exit code 1 indicates a failure; do not hide
it. The first experiment found a failing case; the post-fix run passed. Use a fresh directory
for each run so earlier results are retained. The API's caller deadline is 30
seconds; Postman's request timeout is 40 seconds to allow the API to respond.

For a targeted diagnostic that includes synthetic API response bodies:

```sh
postman collection run 'postman/collections/Planning conversations' \
  -i '09_missing_year' \
  -e 'postman/environments/Travel AI local.environment.yaml' \
  --env-var record_responses=true --no-report-events --timeout-request 40000
```

Full response recording is opt-in. Do not use real traveler messages in reports
that will be committed. `--output` in CLI 1.69.0 requires CLI login even for local
reports; the console transcript works without that login. The plugin's connected
account and CLI login are separate. These commands disable cloud run uploads and
do not publish or alter the existing Postman cloud workspace.

## Results and follow-up

See [evaluation results](../evals/conversations/README.md) and
[known failures](../evals/conversations/known-failures.json). Re-run the same cases
after a fix, save a new report, and compare case outcomes. The first run covers
this small development dataset, not all possible user messages. Offline failure
and timeout regression tests remain in the normal pytest suite.
