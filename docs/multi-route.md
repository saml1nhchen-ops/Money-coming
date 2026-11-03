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

Calls prefer routes with remaining free quota, using the selection rules below. Equal remaining fractions choose the least busy route and rotate ordered ties. HTTP 429/5xx,
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
GPT-4.x/4o models omit reasoning parameters. `SIGNAL_GEO_THINKING` no longer enables thinking; minimum settings always apply. `SIGNAL_MAX_TOKENS` controls `max_output_tokens`
for Responses and `max_completion_tokens` for OpenAI Chat Completions.
The separate B.AI provider retains its own model default.


## Minimum thinking policy

`tools/ai_api.py:thinking_policy` centralizes thinking settings for Chat,
Gemini and Responses protocols. The registry's
`thinking_off` object remains the final chat route override (including `{}` to omit
unsupported switches); OpenAI derives effort from the actual selected model.
Existing output token limits and `SIGNAL_MAX_TOKENS` behavior are unchanged.

| Family / platform | Minimum request settings |
| --- | --- |
| OpenAI Responses / Chat | GPT-5.1+ (including 5.4): `reasoning.effort: none` / `reasoning_effort: none`; GPT-5/mini/nano: `minimal`; o-series: `low`; nonreasoning/chat-latest: omit |
| Google Gemini 2.5 Flash / Pro | `generationConfig.thinkingConfig.thinkingBudget: 0` / `128` |
| Google Gemini 3.x Flash / Pro | `thinkingLevel: minimal` / `low` |
| Qwen official/Bailian, SiliconFlow | `enable_thinking: false` |
| DeepSeek, Kimi on Bailian | `enable_thinking: false` |
| DeepSeek, Kimi on TokenHub; official DeepSeek/Kimi | `thinking: {type: disabled}`; legacy DeepSeek reasoner selects chat |
| Doubao Ark/official, Zhipu official, Hunyuan TokenHub/official | `thinking: {type: disabled}` |
| MiniMax official, TokenHub M3 | `thinking: {type: disabled}` |
| NVIDIA NIM reasoning models | `chat_template_kwargs: {thinking: false, enable_thinking: false}`; instruct models omit unsupported switches |
| Bailian GLM-5.3, TokenHub GLM-5.2 | Disabling is rejected: `reasoning_effort: low`, fallback-only |
| TokenHub GLM-5.3-Flash | `reasoning_effort: low`; preferred (owner probe reported zero reasoning tokens) |
| TokenHub MiniMax M3.1 Flash | Requires thinking: `reasoning_effort: low`, fallback-only when another route is available |

`SIGNAL_<FAMILY>_REASONING_EFFORT` overrides effort strings for OpenAI, Gemini 3.x,
and low-effort exceptions (for example `SIGNAL_ZHIPU_REASONING_EFFORT=low`). Use
only a value supported by the selected model. Turning thinking fully off is not
possible on routes that require it; these are explicitly demoted with
`fallback_only: true`. Unknown model overrides must provide appropriate
`thinking_off` settings in their route specification. These policies encode the
owner-supplied compatibility constraints; this change has not live-verified them.

Owner-reported live probes found TokenHub `glm-5.2` consumed 32 reasoning tokens
out of a 32-token output cap with `reasoning_effort: low`; NVIDIA
`minimaxai/minimax-m3.1-flash` consumed 25 reasoning tokens despite the disabling
switches. Both pool entries are fallback-only. These observations do not establish
that the other failing routes support thinking-off; their failures need diagnosis.

The Zhipu pool includes preferred TokenHub `glm-5.3-flash` (cap 4, 1M-token
allowance through 2027-11-03) and official `glm-4.7-flash` (cap 1).
TokenHub single-route selection also defaults to `glm-5.3-flash`. Bailian
`glm-5.3` and TokenHub `glm-5.2` remain fallback-only. The owner-reported live
probe of TokenHub `glm-5.3-flash` returned zero reasoning tokens with
`reasoning_effort: low`; this follow-up was validated offline only.

## Quota allocation and ledger

Route entries accept `quota` objects:

```json
{"free_tokens": 1000000, "expires": "2027-11-03", "scope": "per_model"}
```

Alternatively use `{"unlimited": true}` or `{"kind": "usd_credit"}`. Defaults:
TokenHub 1M tokens per model through 2027-11-03; Bailian/DashScope 1M through
2027-02-01; Ark 500k per model without an assumed expiry; official Zhipu
GLM-4.7-Flash and NVIDIA NIM unlimited; OpenAI paid credit with no assumed token
cap. Expiry dates are inclusive, evaluated using the local calendar date.
The legacy `free` metadata describes a model's permanent free classification;
finite promotional allowances are tracked separately by `quota`.

Usage is persisted in `runtime/route-ledger.json`, beside the existing runtime
results directories. Entries are keyed by `platform/model`, shared across
families and explicit/pool routes. Official Qwen maps to `bailian`, Doubao to
`ark`, and NIM to `nvidia` so identical routes share usage. The ledger contains
only token counts and seed annotations, never keys, prompts or answers.
Each successful response adds input + output, plus reasoning only when reported
separately (Gemini thoughts or top-level reasoning). OpenAI output detail
reasoning is already included in output. Missing usage adds nothing; late successful
responses after a caller timeout are counted too. Updates use a process thread
lock, unique temporary file, flush/fsync and atomic `os.replace`. This prevents
thread races and partial files; separate processes must use separate ledgers or
an external accounting system. Corrupt/unwritable ledgers surface errors.

Remaining fraction is `max(0, (free_tokens - recorded_tokens) / free_tokens)`.
Unlimited routes score 1.0, expired allowances score 0, and paid/unknown routes
default to 0.25. Availability, concurrency and cooldown filtering still apply.
Routes below 5% remaining are excluded if another candidate meets the threshold;
if all are depleted, calls can still proceed and may incur paid usage. Fallback-only
routes wait while a healthy, funded preferred route is at its admission cap. A caller
waits up to `SIGNAL_ROUTE_FALLBACK_GRACE` seconds (default 2, clamped to zero)
for a preferred slot on each admission; an available healthy preferred slot always
wins. After the grace, fallback routes may use available slots. If all preferred
routes have failed in this call, are cooling, or are excluded by quota filtering,
fallback admission is immediate. Missing preferred credentials also allow immediate
fallback. The call deadline still bounds the wait. Quota filtering happens before
slot filtering so a busy preferred route cannot be bypassed merely because a
fallback route has more free quota. Among
unequal fractions, weighted random selection uses fraction / (1 + busy calls),
spreading load while favoring more remaining quota. Equal fractions retain the
existing least-busy rotating selection. No quota reservation is made for inflight
calls, so concurrent calls can cross an allowance boundary. The ledger is local
usage accounting, not a provider balance query, and misses calls from other clients.

| Environment variable | Default / purpose |
| --- | --- |
| `SIGNAL_ROUTE_FALLBACK_GRACE` | `2`; seconds to wait for a healthy preferred slot before fallback admission |
| `SIGNAL_ROUTE_QUOTA_MODE` | `weighted`; `off` restores least-busy rotation (fallback demotion remains) |
| `SIGNAL_ROUTE_QUOTA_MIN_FRACTION` | `0.05`; low-allowance cutoff |
| `SIGNAL_ROUTE_PAID_WEIGHT` | `0.25`; paid/unknown route weight, clamped 0–1 |
| `SIGNAL_ROUTE_LEDGER` | runtime path above; custom path, or `off` to disable reading/writing |
| `SIGNAL_ROUTE_QUOTAS` | JSON object keyed by `platform/model`; values replace quota objects |

Quota overrides also work through JSON family route specifications. An explicit
model override shares its platform quota policy but gets its own model ledger key.
`scope: per_model` documents the supported scope; shared platform credit accounting
is not inferred from this field.

```sh
SIGNAL_LOAD_DOTENV=0 python3 tools/route_ledger.py show
SIGNAL_LOAD_DOTENV=0 python3 tools/route_ledger.py seed --known
```

Seeding is opt-in and never decreases an existing count. It marks entries
`partial: true` with a lower-bound note. Known lower bounds: TokenHub
DeepSeek-v4-flash-202605 63,832; GLM-5.3-flash 70,403; Kimi-k3.1-pro 13,021;
Bailian Qwen3.8-flash 84,385. Actual usage can be higher.

## Route verifier and benchmark

```sh
python3 tools/verify_routes.py --dry-run
python3 tools/verify_routes.py --families openai gemini qwen
python3 tools/bench_geo_collect.py --china-families --with openai --questions 10
# --china-families --providers openai also includes OpenAI.
```

The verifier deduplicates each default and pool platform/model, sends one tiny
`Reply with OK.` request per configured route with a 32-token output cap (256 for Gemini 2.5 Pro
to accommodate its mandatory thinking budget), and
prints family, platform, model, status, answer_nonempty, input/output/reasoning
tokens and latency. It does not fail over, print answers or print credentials.
Failures also print a fixed `error_category` and numeric `http_status` (`none`
when unavailable). Categories distinguish authentication, permission, missing
endpoint/model, rate limits, provider errors, transport failures and malformed
responses where identifiable. Exception text and provider bodies are never printed.
A missing credential prints `status=not_configured` without a call; live calls update the ledger. `--dry-run`
uses fixture credentials, disables local credential loading, prints only bodies
and route identities, and makes no network requests. It can therefore run without
configured credentials. Live verification and benchmarks are opt-in and can spend
quota or credits, including on required-thinking fallback routes.

The benchmark additionally prints each family's average input/output/reasoning
tokens per returned sample (including failed samples as zero usage), and per-family
platform/model distribution. The aggregate route split still counts completions.
Offline checks: `SIGNAL_LOAD_DOTENV=0 SIGNAL_ROUTE_LEDGER=off python3 -m unittest discover -s tests`.
Quota tests explicitly use temporary ledgers and mock all provider transports.
