# Configuration and API reference

Environment variables are read by `Settings.from_env()`. `.env` is not loaded. Python `Settings()` retains compatibility defaults for library tests; use `Settings.from_env()` for the CLI behavior below.

| Variable | Default | Purpose |
|---|---|---|
| `BRIDGEX_PROVIDER` | `molab` | `molab`, `fake`, or `openai-compatible`. CLI `--provider` overrides it. |
| `BRIDGEX_LOCAL_KEY` | `molab-local` | Local Bearer key; use a unique nonempty value for normal operation. |
| `BRIDGEX_MOLAB_CONFIG` | Project `.molab_local.json` | Explicit local Molab connection file. |
| `BRIDGEX_JOURNAL_PATH` | `bridge_x_state.sqlite3` | Journal path relative to the working directory, or `:memory:` for disposable tests. |
| `BRIDGEX_TIMEOUT_SECONDS` | `600` | Total gateway request deadline, including queue and retries. |
| `BRIDGEX_ACTION_CHARS` | `2200` | Advisory action size, 1000–12000; not a provider token limit. |
| `BRIDGEX_MOLAB_TOOL_MODE` | `native` | `native`, `auto`, or explicit legacy `structured`. Native is the public default. |
| `BRIDGEX_MOLAB_REQUEST_INTERVAL` | `15` | Minimum seconds between generation starts. |
| `BRIDGEX_MOLAB_BACKGROUND_INTERVAL` | `30` | Minimum seconds between background starts. |
| `BRIDGEX_MOLAB_BACKGROUND_IDLE` | `10` | Foreground idle period before background admission. |
| `BRIDGEX_MOLAB_COOLDOWN` | `60` | Initial fallback pause after rate rejection; explicit longer upstream delays win. |
| `BRIDGEX_MOLAB_MAX_QUEUE_WAIT` | `120` | Queue budget when transparent rate recovery is disabled. With verified native recovery, the remaining total deadline bounds admission. |
| `BRIDGEX_MOLAB_RATE_RETRIES` | `2` | 0–2 extra attempts after an explicit rejection before output, in verified native mode only. |
| `BRIDGEX_MOLAB_RATE_RECOVERY` | `900` | Seconds to retain increased caution after a rate limit. |
| `BRIDGEX_GENERIC_URL` | Empty | Operator-supplied documented HTTPS endpoint for the generic adapter. |
| `BRIDGEX_GENERIC_MODEL` | Empty | Model identifier for the generic adapter. |
| `BRIDGEX_GENERIC_API_KEY` | Empty | Explicit generic upstream key. |

Numeric time settings must be finite and positive. `BRIDGEX_LOCAL_KEY` authenticates the local gateway; it is not a Molab token. Do not put unsupported fields in the example and expect them to affect the application.

CLI options: `--provider`, `--port` (default 8787, loopback only, zero chooses a free port), and `--check-config` (syntax only; no remote access or SQLite creation).

## Local HTTP endpoints

| Endpoint | Local Bearer key | Behavior |
|---|---|---|
| `GET /health` | No | Process version and selected provider; not proof of upstream access. |
| `GET /ready` | No | Ready for fake mode or if the adapter exposes `live_verified`; generic mode currently does not set this flag. |
| `GET /v1/models` | Yes | Configured model identifier. |
| `GET /v1/capabilities` | Yes | Declared protocol and observed native capability. |
| `POST /v1/chat/completions` | Yes | OpenAI-compatible chat, native calls, and SSE. |
| `GET /diagnostics` | Yes | Bounded sanitized metadata and pacing status. |
| `GET /v1/operations/{call_id}` | Yes | Operation state, not a request to execute it. |
| `POST /v1/operations/{call_id}/verification` | Yes | Compares client-supplied expected/observed digests, checks owner/state, and records `VERIFIED`. No independent filesystem check. |

The server never runs tools itself. Tool schemas, results, and transcript text are untrusted input, not higher-priority instructions.

## Client identity and tool receipts

| Input | Meaning |
|---|---|
| `conversation_id` body field | Owner of tool proposals/results and the main session identity. |
| `x-session-id` header | Used as conversation identity only when the body omits it; must be nonblank and at most 256 characters. |
| `idempotency_key` body / `Idempotency-Key` header | Identifies one logical dispatch request. Conflicting body/header values are rejected. Use a new key for the next progressed action. |
| `x-zcode-query-source` | Execution-scope source, normally `main_turn`; background sources derive a stable history digest. Not a separate authentication credential. |
| `x-request-id` | Optional sanitized correlation ID for metadata; not an idempotency key. |
| `role: tool`, `tool_call_id` | Actual client result paired with the gateway-returned call ID. Include the preceding assistant call in history when available. |

The schema engine replaces upstream IDs with fresh local call IDs. Return the local ID exactly. Receipts with explicit boolean `success` or integer `exit_code` can establish reported outcomes; stdout alone cannot. An unmatched result is retained as unverified. See [architecture and recovery](ARCHITECTURE.md#tool-ids-and-client-receipts).

## Error responses

Errors produced by `BridgeError.public()` use an `error` object containing `message`, `type`, `code`, and `retryable`. Optional `retry_after_seconds` and UTC `retry_at` describe a delay; ordinary HTTP errors can also carry `Retry-After`. Authentication/status-not-found and framework request validation have their own small response shapes; clients should check status and payload, not require identical fields on every route.

| Error family | Behavior and response context |
|---|---|
| `INVALID_REQUEST`, `INVALID_TOOL_SCHEMA`, `TOOL_NOT_AVAILABLE` | Input rejected before generation, generally HTTP 400. Oversized body/context uses 413. |
| `TOOL_SCHEMA_MISMATCH`, `INVALID_NATIVE_TOOL_DELTA` | Tool contract rejected; commonly 422 at the gateway, with some provider-native failures using 502. No executable partial call is released. |
| `EXECUTION_UNKNOWN`, ownership/receipt conflicts | HTTP 409 before generation when a dispatch/result cannot safely continue. Preserve state and reconcile actual effects. |
| `MOLAB_COOLDOWN_ACTIVE`, `MOLAB_QUEUE_TIMEOUT` | HTTP 429 local pacing condition; that attempt did not send a new model request. |
| `MOLAB_RATE_LIMIT`, Molab `UPSTREAM_RATE_LIMIT` | Explicit HTTP/SSE upstream rejection; rate-limit metadata, bounded pre-output recovery when eligible, otherwise HTTP 429 or SSE error. |
| `UPSTREAM_QUOTA_EXHAUSTED` in Molab | Explicit permanent-quota signal, HTTP 429 / SSE error, `insufficient_quota`, no automatic retry promise. |
| Generic upstream HTTP 429 | `UPSTREAM_RATE_LIMIT` wrapped with HTTP 503 and `retryable: true`; no Molab pacing/retry loop. Generic SSE rate failures reach the gateway's 429 mapping. |
| `MOLAB_RUNTIME_GONE` | Configured runtime returned 410; changing local mode does not restore it. |
| Native mode/access/HTTP failures | Distinct `MOLAB_NATIVE_MODE_REQUIRED`, `MOLAB_NATIVE_MODE_UNKNOWN`, `MOLAB_ACCESS_DENIED`, and `MOLAB_HTTP_ERROR`; inspect the sanitized code. |
| Deadline, incomplete stream, late error | `UPSTREAM_DEADLINE` is 504; other stream/transport failures generally 502. Never use a missing terminal as success. |

Once streaming has begun, failure is `event: error` inside HTTP 200 and is **not** followed by a successful `[DONE]`. Tools remain buffered until complete validation. A retryable error describes the possibility of a later attempt; it does not authorize blindly repeating an uncertain client command.

## Limits and defaults in Python

`Settings.from_env()` exposes only the variables listed above. Other dataclass limits are library configuration, not undocumented environment switches: request bytes 1,500,000; provider response bytes 4,000,000; output characters 1,000,000; tool argument bytes 256,000; context characters 220,000; heartbeat 5 seconds. The gateway/schema engine accepts at most 16 tool calls per response. `max_message_chars` is present in `Settings` but is not currently an independent per-message enforcement step in the request path.

`Settings()` directly defaults to fake provider / structured mode / disabled pacing and retries. Environment-based startup defaults to Molab / native mode / verified pacing and two retries. `auto` uses native payloads and permits compatibility parsing in the gateway, but does not enable the verified-native retry policy. See [DEVELOPMENT.md](DEVELOPMENT.md).

The example file supports `notebook_url`, `chat_url`, `marimo_session_id`, optional empty `marimo_server_token`, and `http_headers`. The runtime URL must be HTTPS on a `.sb.molab.run` host, port 443/default, exactly `/api/ai/chat`, with no credentials, query, or fragment. Header names and ASCII values are validated; reserved routing/framing/Marimo headers cannot be overridden. These are implementation checks, not a guarantee of current upstream availability.

## Persistence

The journal includes operation transitions and separate execution scopes. Historical receipt reconciliation uses the original conversation owner. Unconfirmed mutations in the same scope block unsafe continuation. `provider_control` records cooldown and the recent rate-pressure timestamp; a runtime/session change does not intentionally reset that state.

Keep one active bridge for a given journal/quota. Admission priority is process-local, not a distributed limiter. A successful completion does not prove that a final client action was executed unless its receipt is available.
