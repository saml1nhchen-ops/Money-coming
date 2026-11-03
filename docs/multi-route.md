# GEO route pools

Default direct GEO sampling uses the ordered, verified `pool: true` routes in
`dist/ai-providers.json` for the seven China families and OpenAI. Missing credentials silently
remove routes; a family without a pool falls back to its existing single-route
configuration. Unconfigured families retain the existing skip behavior. Hunyuan
currently has one verified platform; Qwen and Doubao have two models on one platform.
The matrix does not supply additional usable platforms for these families.

Credentials come from environment, repository `.env`, then `~/.secrets/<VAR>`
(first line only). `SIGNAL_LOAD_DOTENV=0` disables local credential loading for tests.
Credentials are never included in route state, attempt records or exports.

Override a family with `SIGNAL_DEEPSEEK_ROUTES=bailian:deepseek-v4.1-flash,tokenhub:deepseek-v4.1-flash`
or a JSON list of these strings. JSON objects can override `platform`, `base_url`,
`env_key_var`, `model`, `thinking_off`, and `concurrency`; the platform must have a
matrix entry for that family. Supply `thinking_off: {}` for models rejecting thinking
parameters. An explicit `SIGNAL_<FAMILY>_ROUTE` or request route retains single-route
behavior. Select an explicit route to override a model rather than a whole pool.

Each route has its own process-wide admission cap. Defaults are 4 and 1 for official
GLM-4.7-Flash. `SIGNAL_ROUTE_CONCURRENCY` overrides the general default;
`SIGNAL_GEO_PROVIDER_CONCURRENCY` remains a compatibility alias for this **per-route**
cap, with the new setting taking precedence. GLM's safety cap stays 1 unless explicitly
overridden with `SIGNAL_<FAMILY>_<PLATFORM>_<MODEL>_CONCURRENCY` (uppercase, replace
all non-alphanumeric characters with `_`). This variable takes highest precedence.
Limits are per model route, not a platform-wide quota; shared platform quotas may
still require lower caps. Global GEO concurrency defaults to the sum of selected
active route caps, overridable with `SIGNAL_GEO_CONCURRENCY`.

Calls choose the least busy available route, rotating ordered ties. HTTP 429/5xx,
timeouts and connection failures try another route in the same family, at most once
per route per planned call. Pooled attempts have a 30-second wall-clock limit,
configurable with `SIGNAL_ROUTE_ATTEMPT_TIMEOUT` (seconds). A slow attempt fails over
to another route in the same family. Admission waits and all attempts share the
existing `SIGNAL_CALL_TIMEOUT` per-call budget (default 90 seconds); failover does
not reset it. Explicit single-route calls keep their existing timeout behavior.
A timed-out request retains its admission slot until its underlying network work
exits, preventing retries from exceeding route concurrency. Other errors do not fail over. Three consecutive transient
failures cool a route for 60 seconds (`SIGNAL_ROUTE_FAILURE_THRESHOLD`,
`SIGNAL_ROUTE_COOLDOWN` in seconds). Cooling routes are skipped unless all remaining
routes are cooling. State is shared across concurrent batches in the process.

One question × family remains one planned/budgeted call even with failover. Attempts
can incur additional provider charges. Samples record `route_platform`, `route_model`,
`attempts` (status, HTTP status when available, latency), and `failovers`, including
failed samples. These are evidence/export fields, not primary report badges.

Opt-in benchmark (makes real API calls; never part of tests):

```sh
python3 tools/bench_geo_collect.py --china-families --questions 10
```

Prints per-provider success counts and aggregate input/output/reasoning token totals
from returned usage (reasoning is part of output, not an additional total), wall time, completion fraction, total observed 429s, failovers and successful
platform/model split. No answers or credentials are printed.

## OpenAI

OpenAI defaults to `gpt-5.4-mini` via the official Responses endpoint
`https://api.openai.com/v1`, using `SIGNAL_OPENAI_API_KEY`. Its official pool route
has concurrency 4 and follows the same pool and concurrency overrides above.
Use `SIGNAL_OPENAI_ROUTE=official` for single-route model/base overrides, or
`SIGNAL_OPENAI_ROUTES` to customize the pool.

With thinking off (default), GPT-5.1+ and GPT-6+ use reasoning effort `none`,
GPT-5/5-mini/5-nano use `minimal`, and o-series use `low`. Chat-latest and
GPT-4.x/4o models omit reasoning parameters. `SIGNAL_GEO_THINKING=1` leaves
reasoning settings to the API. `SIGNAL_MAX_TOKENS` controls `max_output_tokens`
for Responses and `max_completion_tokens` for OpenAI Chat Completions.
The separate B.AI provider retains its own model default.
