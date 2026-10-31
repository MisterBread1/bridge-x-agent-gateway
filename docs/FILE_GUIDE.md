# Complete file guide

[README](../README.md) · [Architecture](ARCHITECTURE.md) · [Development](DEVELOPMENT.md) · [Testing](TESTING.md)

This inventory covers **all 84 tracked files in the documentation branch**, including hidden configuration and the original ZIP. It excludes ignored/private/generated working state. Every Python file was inspected; symbols/imports below reflect its implementation, including lazy imports. Empty package markers are listed explicitly.

## Complete tracked tree

```text
bridge-x-agent-gateway/
├── .github/
│   └── PULL_REQUEST_TEMPLATE.md
├── .gitignore
├── CHANGELOG.md
├── CONTRIBUTING.md
├── FILE_SHA256SUMS.txt
├── LIVE_CHECK.py
├── LOCAL_HTTP_ACCEPTANCE.py
├── README.md
├── RELEASE_NOTES.md
├── SECURITY.md
├── bridge-x-12.12.3-beta.1.zip
├── bridge_x/
│   ├── __init__.py
│   ├── __main__.py
│   ├── capabilities.py
│   ├── config.py
│   ├── context.py
│   ├── coordinator.py
│   ├── errors.py
│   ├── execution_scope.py
│   ├── gateway.py
│   ├── journal.py
│   ├── json_utils.py
│   ├── molab_native.py
│   ├── molab_provider.py
│   ├── molab_runtime.py
│   ├── providers.py
│   ├── rate_control.py
│   ├── receipts.py
│   ├── schema_engine.py
│   ├── schemas.py
│   ├── sse.py
│   ├── structured_intent.py
│   ├── tool_frames.py
│   ├── tool_models.py
│   └── tools.py
├── bridge_x_test_runner/
│   ├── __init__.py
│   └── runner.py
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CONFIGURATION.md
│   ├── CONTENTS_AUDIT.md
│   ├── DEVELOPMENT.md
│   ├── DOCUMENTATION_QA.md
│   ├── FILE_GUIDE.md
│   ├── GITHUB.md
│   ├── TESTING.md
│   └── VALIDATION.md
├── examples/
│   └── .molab_local.example.json
├── pytest.ini
├── requirements-dev.txt
├── requirements.txt
├── start.bat
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_agent_recovery.py
│   ├── test_audit_hardening.py
│   ├── test_command_engine_128.py
│   ├── test_dispatch_root_cause_12103.py
│   ├── test_execution_branches.py
│   ├── test_gateway.py
│   ├── test_journal_context.py
│   ├── test_molab_integration.py
│   ├── test_native_molab.py
│   ├── test_output_budget126.py
│   ├── test_output_regression_1210.py
│   ├── test_property_protocols.py
│   ├── test_provider_transport.py
│   ├── test_rate_control.py
│   ├── test_rate_recovery.py
│   ├── test_read_integer_fix_12101.py
│   ├── test_read_integer_fix_12102.py
│   ├── test_regression_124.py
│   ├── test_regression_127.py
│   ├── test_regression_129.py
│   ├── test_release_cli.py
│   ├── test_sandbox_runner.py
│   ├── test_schema125.py
│   ├── test_sse.py
│   ├── test_stress.py
│   └── test_tools.py
└── tools/
    ├── __init__.py
    ├── audit_release.py
    ├── build_release.py
    ├── configure.py
    └── native_css_acceptance.py
```

## Runtime code

Runtime modules are library implementation files. Ordinary users do **not** need to edit them; configure local settings instead. Maintainers change them only with regression evidence.

### `bridge_x/__init__.py`

[Open source](../bridge_x/__init__.py) · Category: runtime code · User edit: **No**.

Package version metadata. Publishes `__version__` used by CLI, HTTP responses, tests, and the ZIP builder.

**Key symbols:** `__version__`.

**Internal relationships:** Package metadata consumed by CLI, gateway, tests, and release tooling.

### `bridge_x/__main__.py`

[Open source](../bridge_x/__main__.py) · Category: runtime code · User edit: **No**.

CLI entry point for `python -m bridge_x`. Reads `Settings.from_env()`, checks Molab syntax/placeholders, reserves a loopback socket, optionally calls native mode setup, then starts Uvicorn. Syntax-only checks exit before network/SQLite startup.

**Key symbols:** `main`.

**Internal relationships:** `bridge_x.__init__`, `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_provider`, `bridge_x.molab_runtime`.

### `bridge_x/config.py`

[Open source](../bridge_x/config.py) · Category: runtime code · User edit: **No**.

Immutable runtime configuration and environment validation. `Settings` distinguishes library compatibility defaults from CLI defaults; validates providers, numeric bounds, local key, and generic HTTPS configuration. Its description omits credential values.

**Key symbols:** `Settings`.

**Internal relationships:** Package metadata consumed by CLI, gateway, tests, and release tooling.

### `bridge_x/gateway.py`

[Open source](../bridge_x/gateway.py) · Category: runtime code · User edit: **No**.

FastAPI request boundary and response orchestration. `create_app()` wires settings, provider, journal, coordinator, lifespan, and authenticated routes. Enforces body/deadline/output limits, buffers complete tool calls, rejects late stream failures, and serializes JSON/SSE. It never executes client tools.

**Key symbols:** `create_app`.

**Internal relationships:** `bridge_x.__init__`, `bridge_x.capabilities`, `bridge_x.config`, `bridge_x.coordinator`, `bridge_x.errors`, `bridge_x.execution_scope`, `bridge_x.journal`, `bridge_x.json_utils`, `bridge_x.providers`, `bridge_x.receipts`, `bridge_x.schemas`, `bridge_x.sse`, `bridge_x.tools`.

### `bridge_x/coordinator.py`

[Open source](../bridge_x/coordinator.py) · Category: runtime code · User edit: **No**.

Receipt-first turn preparation and durable dispatch coordination. `AgentTurn` carries bounded history, scope, receipt statistics, and request key. `ToolCoordinator.prepare()` reconciles original history, checks semantic/legacy fingerprints, and compacts context; `dispatch()` delegates atomic recording to `Journal`.

**Key symbols:** `AgentTurn`, `ToolCoordinator`.

**Internal relationships:** `bridge_x.context`, `bridge_x.journal`, `bridge_x.receipts`, `bridge_x.schemas`.

### `bridge_x/context.py`

[Open source](../bridge_x/context.py) · Category: runtime code · User edit: **No**.

Bound historical context without corrupting executable input. `compact()` copies history, shortens old tool output, archives fully paired old exchanges, protects the first user goal/latest messages, and rejects an unsafe remaining over-budget context. It does not assert archived success.

**Key symbols:** `compact`.

**Internal relationships:** `bridge_x.errors`.

### `bridge_x/execution_scope.py`

[Open source](../bridge_x/execution_scope.py) · Category: runtime code · User edit: **No**.

Foreground/background coordination identities. `resolve_execution_scope()` returns `main_turn` or a validated query-source/history digest. Used by the gateway and coordinator; scopes isolate pending-action guards without changing conversation ownership.

**Key symbols:** `resolve_execution_scope`.

**Internal relationships:** Package metadata consumed by CLI, gateway, tests, and release tooling.

### `bridge_x/journal.py`

[Open source](../bridge_x/journal.py) · Category: runtime code · User edit: **No**.

SQLite operation/receipt ledger and sanitized diagnostic store. `Journal` creates/migrates tables, records operation transitions and dispatch fingerprints atomically, reconciles original client call/result history, checks ownership, accepts explicit client digest verification, persists pacing metadata, and closes connections. See architecture for exact state semantics.

**Key symbols:** `Journal`.

**Internal relationships:** `bridge_x.errors`, `bridge_x.tool_models`.

### `bridge_x/receipts.py`

[Open source](../bridge_x/receipts.py) · Category: runtime code · User edit: **No**.

Conservative classification of client-reported outcomes. `classify_result()` decodes strict JSON and recognizes cancellation, timeout, explicit failure/success, and typed exit codes. Prose/stdout alone does not imply success. Used during journal reconciliation.

**Key symbols:** `classify_result`.

**Internal relationships:** `bridge_x.json_utils`.

### `bridge_x/providers.py`

[Open source](../bridge_x/providers.py) · Category: runtime code · User edit: **No**.

Shared provider events, fake simulator, generic HTTP adapter, and factory. Defines text/native/terminal/failure/wait events. `GenericOpenAIProvider` decodes bounded OpenAI-compatible SSE and requires finish plus DONE; `FakeProvider` provides deterministic fixtures. `make_provider()` lazily loads Molab.

**Key symbols:** `TextDelta`, `NativeToolDelta`, `Finish`, `Failed`, `RateLimitWait`, `Done`, `FakeProvider`, `GenericOpenAIProvider`, `make_provider`.

**Internal relationships:** `bridge_x.errors`, `bridge_x.json_utils`, `bridge_x.molab_provider`, `bridge_x.sse`.

### `bridge_x/capabilities.py`

[Open source](../bridge_x/capabilities.py) · Category: runtime code · User edit: **No**.

Explicit adapter protocol and declared capability metadata. `Provider` specifies the async generator interface; `ProviderCapabilities` and `capabilities_for()` separate static declarations from runtime observation. The gateway adds observed Molab native/live flags.

**Key symbols:** `ProviderCapabilities`, `Provider`, `capabilities_for`.

**Internal relationships:** `bridge_x.schemas`.

### `bridge_x/molab_provider.py`

[Open source](../bridge_x/molab_provider.py) · Category: runtime code · User edit: **No**.

Molab configuration, payload adaptation, event decoding, and generation transport. `read_molab_config()` validates operator URL/session/headers without leaking values. Payload builders select native or compatibility history. `MolabProvider` owns serialized HTTP generation, bounded pre-output rate recovery, outcome-budget metadata, mode checks, and sanitized stream metrics. `MolabSSEParser` retains older wire records.

**Key symbols:** `MolabConfiguration`, `read_molab_config`, `build_molab_messages`, `build_molab_payload`, `MolabSSEParser`, `decode_molab_event`, `MolabProvider`.

**Internal relationships:** `bridge_x.errors`, `bridge_x.json_utils`, `bridge_x.molab_native`, `bridge_x.molab_runtime`, `bridge_x.providers`, `bridge_x.rate_control`, `bridge_x.sse`, `bridge_x.structured_intent`, `bridge_x.tools`.

### `bridge_x/molab_native.py`

[Open source](../bridge_x/molab_native.py) · Category: runtime code · User edit: **No**.

Native frontend tool definitions, history, and input assembly. `native_tools()` preserves schemas; `native_messages()` pairs actual client results and archives old completed arguments. `NativeToolAssembler` requires valid start/delta/available sequences, agreement with completed input, and rejects notebook-side output events. The provider consumes it before shared schema validation.

**Key symbols:** `native_tools`, `native_messages`, `NativeToolAssembler`.

**Internal relationships:** `bridge_x.errors`, `bridge_x.json_utils`, `bridge_x.molab_provider`, `bridge_x.providers`, `bridge_x.tools`.

### `bridge_x/molab_runtime.py`

[Open source](../bridge_x/molab_runtime.py) · Category: runtime code · User edit: **No**.

Read and configure the runtime AI mode. `runtime_mode_from_html()` parses known modes from embedded config. `ensure_native_mode()` reads the configured runtime and can change only AI mode from code mode to manual. Called on actual native CLI startup; syntax-only checks do not call it.

**Key symbols:** `runtime_mode_from_html`, `ensure_native_mode`.

**Internal relationships:** `bridge_x.errors`.

### `bridge_x/rate_control.py`

[Open source](../bridge_x/rate_control.py) · Category: runtime code · User edit: **No**.

Molab pacing, foreground priority, cooldown, and retry hints. `RateController` binds persistent journal state and exposes preflight/status/async admission slots. Helpers parse explicit HTTP/event retry hints and identify known background scopes. Actual retries live in `MolabProvider`; locks remain process-local.

**Key symbols:** `retry_after_seconds`, `event_retry_after`, `is_background`, `RateController`.

**Internal relationships:** `bridge_x.errors`.

### `bridge_x/schema_engine.py`

[Open source](../bridge_x/schema_engine.py) · Category: runtime code · User edit: **No**.

Single executable tool-validation contract. `registry()` creates Draft 2020-12 validators and schema hashes without remote retrieval. `validate_specs()` enforces count, choice, names, bounds, and schema, applies narrow integer compatibility, then allocates fresh local `ToolCall` IDs. `tool_choice_name()` resolves a forced function.

**Key symbols:** `registry`, `tool_choice_name`, `validate_specs`.

**Internal relationships:** `bridge_x.errors`, `bridge_x.json_utils`, `bridge_x.schemas`, `bridge_x.tool_models`.

### `bridge_x/schemas.py`

[Open source](../bridge_x/schemas.py) · Category: runtime code · User edit: **No**.

Pydantic input contracts. `ChatMessage`, `ToolDeclaration`, and `ChatRequest` validate roles/declarations/choice while allowing client extension fields. `OperationVerification` strictly accepts conversation identity and two SHA-256 values. Used by the HTTP and validation boundaries.

**Key symbols:** `ChatMessage`, `ToolDeclaration`, `ChatRequest`, `OperationVerification`.

**Internal relationships:** Package metadata consumed by CLI, gateway, tests, and release tooling.

### `bridge_x/tool_models.py`

[Open source](../bridge_x/tool_models.py) · Category: runtime code · User edit: **No**.

Provider-independent tool proposals and operation state names. `ToolCall` stores local ID/name/arguments/schema hash/owner and serializes OpenAI function calls. `OperationState` names lifecycle states. These are data models, not command executors.

**Key symbols:** `OperationState`, `ToolCall`.

**Internal relationships:** Package metadata consumed by CLI, gateway, tests, and release tooling.

### `bridge_x/tools.py`

[Open source](../bridge_x/tools.py) · Category: runtime code · User edit: **No**.

Shared entry points for native tools and retained text compatibility. `validate_native()` strictly decodes complete native argument JSON before schema validation. `parse_intent()` accepts only anchored complete JSON/v2/legacy representations; it never scavenges commands from Markdown/prose. `is_history_echo()` rejects historical-call echoes. Re-exports shared registry/model helpers for compatibility.

**Key symbols:** `is_history_echo`, `parse_intent`, `validate_native`.

**Internal relationships:** `bridge_x.errors`, `bridge_x.json_utils`, `bridge_x.schema_engine`, `bridge_x.schemas`, `bridge_x.tool_frames`, `bridge_x.tool_models`.

### `bridge_x/tool_frames.py`

[Open source](../bridge_x/tool_frames.py) · Category: runtime code · User edit: **No**.

Command Frame v2 literal/typed-field parser. `protocol_lines()` splits only CR/LF; `parse_frame_v2()` requires a final terminator, supports escaped literal delimiters and strict typed JSON, preserves source newlines, and returns values for shared schema validation. Retained compatibility code.

**Key symbols:** `protocol_lines`, `parse_frame_v2`.

**Internal relationships:** `bridge_x.errors`, `bridge_x.json_utils`.

### `bridge_x/structured_intent.py`

[Open source](../bridge_x/structured_intent.py) · Category: runtime code · User edit: **No**.

Prompt guidance for explicit structured-text fallback. `guidance()` describes one complete JSON intent, schema/type fidelity, bounded action guidance, and waiting for real receipts. Used only by compatibility prompt construction, not native input assembly.

**Key symbols:** `guidance`.

**Internal relationships:** Package metadata consumed by CLI, gateway, tests, and release tooling.

### `bridge_x/sse.py`

[Open source](../bridge_x/sse.py) · Category: runtime code · User edit: **No**.

Incremental bounded SSE framing and outgoing event formatting. `SSEEvent`/`SSEParser` handle strict fragmented UTF-8, comments, CR/LF, multiline data, and incomplete EOF. `sse_data()` and `sse_error()` format gateway events; both provider adapters use the parser contract.

**Key symbols:** `SSEEvent`, `SSEParser`, `sse_data`, `sse_error`.

**Internal relationships:** `bridge_x.errors`.

### `bridge_x/json_utils.py`

[Open source](../bridge_x/json_utils.py) · Category: runtime code · User edit: **No**.

Unambiguous JSON decoding and bounded value validation. `loads()` rejects duplicate keys and non-finite constants. `valid_value()` checks depth, UTF-8 strings, and finite numeric values without recursive traversal. Reused across requests, schemas, native tools, and receipts.

**Key symbols:** `loads`, `valid_value`.

**Internal relationships:** Package metadata consumed by CLI, gateway, tests, and release tooling.

### `bridge_x/errors.py`

[Open source](../bridge_x/errors.py) · Category: runtime code · User edit: **No**.

Sanitized typed failure envelope and retry timing. `BridgeError.public()` returns stable codes/types/retry fields and `headers()` emits Retry-After when available. `UpstreamError` specializes it for adapters. Does not expose raw provider error bodies.

**Key symbols:** `BridgeError`, `UpstreamError`.

**Internal relationships:** Package metadata consumed by CLI, gateway, tests, and release tooling.

## Test modules and fixtures

Category: **tests** for every row below. Ordinary users do **not** edit these for setup; contributors change/add tests with related behavior. Test functions are pytest entry points, not an application API. Relative helper imports are listed explicitly; runtime relationships are captured in the same column. All upstream transport fixtures are simulated.

| Exact path | Responsibility / verified behavior | Internal relationships |
|---|---|---|
| [`tests/__init__.py`](../tests/__init__.py) | Empty package marker enabling relative imports between regression modules. | Package marker used by relative test imports |
| [`tests/conftest.py`](../tests/conftest.py) | Shared synthetic Write/Bash schemas plus `tools` and `request_factory` pytest fixtures; downstream modules import these declarations. | `bridge_x.schemas` |
| [`tests/test_agent_recovery.py`](../tests/test_agent_recovery.py) | Restart/duplicate-dispatch protection, explicit idempotency, CSS edit/readback across journal reopen, ownership and transaction rollback, capability honesty, absolute deadline cancellation, and twice-invoked real temporary HTTP cleanup. Exports `Proposals` for other tests. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.journal`, `bridge_x.molab_provider`, `bridge_x.providers`, `bridge_x.schemas`, `bridge_x.tool_models`, `bridge_x_test_runner.runner`, `tests.conftest`, `tests.test_molab_integration` |
| [`tests/test_audit_hardening.py`](../tests/test_audit_hardening.py) | Finite settings, strict JSON/Unicode and duplicate keys, remote schema refs, SSE late events, malformed native data/config headers, receipt types, safe errors, output bounds, timeout output, and a mocked LIVE_CHECK regression. | `LIVE_CHECK`, `bridge_x`, `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_provider`, `bridge_x.providers`, `bridge_x.receipts`, `bridge_x.schemas`, `bridge_x.sse`, `bridge_x.tools`, `bridge_x_test_runner.runner`, `tests.conftest`, `tests.test_molab_integration`, `tests.test_provider_transport` |
| [`tests/test_command_engine_128.py`](../tests/test_command_engine_128.py) | V2 literal/typed fields, empty commands, CRLF/Unicode, escaped delimiters, required end markers, schema/choice/size rules, randomized source roundtrips, compact tool guidance, and gateway streaming/non-streaming behavior. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_provider`, `bridge_x.providers`, `bridge_x.schemas`, `bridge_x.tools`, `tests.conftest` |
| [`tests/test_dispatch_root_cause_12103.py`](../tests/test_dispatch_root_cause_12103.py) | Anchored dispatch regression: markers in prose, fenced examples, JSON data, and legacy payloads stay non-executable; genuine incomplete anchored commands fail. Also checks safe HTTP delivery and absence of an executable prompt example. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_provider`, `bridge_x.providers`, `bridge_x.schemas`, `bridge_x.tools`, `tests.conftest` |
| [`tests/test_execution_branches.py`](../tests/test_execution_branches.py) | Serial native batches and replanning, explicitly allowed parallel calls, independent memory/foreground scopes, shared receipt ownership, pending-operation isolation, restart persistence, SDK-option-independent keys, and legacy fingerprint protection. | `bridge_x.config`, `bridge_x.coordinator`, `bridge_x.errors`, `bridge_x.execution_scope`, `bridge_x.gateway`, `bridge_x.journal`, `bridge_x.providers`, `bridge_x.schemas`, `bridge_x.tool_models`, `tests.conftest` |
| [`tests/test_gateway.py`](../tests/test_gateway.py) | Local authentication/status, body limits, fake text/tool flows, real temporary Write/Python execution by the test client, SSE success/error/heartbeat/late failure, and history receipt restoration. | `bridge_x`, `bridge_x.config`, `bridge_x.gateway`, `bridge_x.journal`, `bridge_x.providers`, `tests.conftest` |
| [`tests/test_journal_context.py`](../tests/test_journal_context.py) | Deliver/receive/duplicate and cross-owner receipts, journal reopen, unknown results, context preservation and safe refusal, transcript restoration, later parent recovery, chronological order, and idempotent unmatched results. | `bridge_x.context`, `bridge_x.errors`, `bridge_x.journal`, `bridge_x.tools` |
| [`tests/test_molab_integration.py`](../tests/test_molab_integration.py) | Simulated Molab transport/configuration/payloads, legacy wire records and text tools, safe error categories/counters, real temporary client Write/Python/result cycle, late SSE rejection, readiness, and no silent fake fallback. Exports fixture helpers `save_config`, `mock_molab`, and `response_stream`. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_provider`, `bridge_x.providers`, `bridge_x.schemas`, `bridge_x.tools`, `bridge_x_test_runner.runner`, `tests.conftest` |
| [`tests/test_native_molab.py`](../tests/test_native_molab.py) | Native frontend definitions/history, assembled input/snapshot fidelity, malformed sequences, no JSON-text execution in native mode, late errors, local session-header deduplication, mocked AI mode setup, and distinct runtime/access/mode errors. Exports `events` for rate tests. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_native`, `bridge_x.molab_provider`, `bridge_x.molab_runtime`, `bridge_x.schemas`, `tests.conftest`, `tests.test_agent_recovery`, `tests.test_molab_integration` |
| [`tests/test_output_budget126.py`](../tests/test_output_budget126.py) | Advisory action-size guidance, inspect-before-edit stage, intact client schemas, no invented upstream max_tokens setting, distinct output/context limits, valid environment range, and no dispatch of truncated source. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_provider`, `bridge_x.providers`, `bridge_x.schemas`, `tests.conftest`, `tests.test_molab_integration` |
| [`tests/test_output_regression_1210.py`](../tests/test_output_regression_1210.py) | Focused schema subset and forced tool, budget adaptation only on client retry after output limit, no rate-limit adaptation, no fabricated SSE completion, expiring fingerprint-only cache, and old SQLite counter migration. | `bridge_x.config`, `bridge_x.gateway`, `bridge_x.journal`, `bridge_x.molab_provider`, `bridge_x.schemas`, `tests.conftest`, `tests.test_molab_integration`, `tests.test_output_budget126` |
| [`tests/test_property_protocols.py`](../tests/test_property_protocols.py) | Hypothesis-generated UTF-8 SSE fragmentation, JSON argument roundtrips, and schema-constrained integer text conversion across line endings. Generated examples are offline. | `bridge_x.schemas`, `bridge_x.sse`, `bridge_x.tools`, `tests.conftest` |
| [`tests/test_provider_transport.py`](../tests/test_provider_transport.py) | Mocked generic OpenAI SSE transport requiring finish plus DONE, late-error override, missing-DONE rejection, and sanitized HTTP failure. Exports `provider_for` for boundary regressions. | `bridge_x.config`, `bridge_x.providers`, `bridge_x.schemas` |
| [`tests/test_rate_control.py`](../tests/test_rate_control.py) | Explicit Retry-After parsing, CLI pacing defaults, known background priority, serialized admission/spacing, cancellation, shared persisted cooldown, queue timeout, safe HTTP/SSE retry metadata, permanent-quota distinction, and longer hint precedence. Exports synthetic `settings` for recovery tests. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.journal`, `bridge_x.molab_provider`, `bridge_x.rate_control`, `tests.conftest`, `tests.test_molab_integration`, `tests.test_native_molab` |
| [`tests/test_rate_recovery.py`](../tests/test_rate_recovery.py) | Bounded HTTP/SSE pre-output retry and exactly one dispatch, no replay after partial text/tool/terminal or unknown failure, total deadline, persistent pressure/migration, cancellation, background queue behavior, and heartbeats during simulated long thinking. | `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.journal`, `bridge_x.molab_provider`, `bridge_x.rate_control`, `tests.conftest`, `tests.test_molab_integration`, `tests.test_native_molab`, `tests.test_rate_control` |
| [`tests/test_read_integer_fix_12101.py`](../tests/test_read_integer_fix_12101.py) | Schema-guided Read integer pagination in legacy/v2 text frames, ambiguous/invalid rejection, no path/string/nested coercion, JSON/native pagination compatibility, and actual HTTP result types. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_provider`, `bridge_x.providers`, `bridge_x.schemas`, `bridge_x.tools` |
| [`tests/test_read_integer_fix_12102.py`](../tests/test_read_integer_fix_12102.py) | Read offset/limit across all representations, canonical/minimum rules, normalization limited to Read pagination for JSON/native, preservation of typed values and caller inputs, and HTTP/SSE integer output. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.providers`, `bridge_x.schemas`, `bridge_x.tools` |
| [`tests/test_regression_124.py`](../tests/test_regression_124.py) | Legacy tool frame literals/typed values, schema fidelity, large-registry prompt bounds, simulated Write/Bash cycle, streaming conversion, one upstream rejection without legacy retry, and no late-error dispatch. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_provider`, `bridge_x.schemas`, `bridge_x.tools`, `tests.conftest`, `tests.test_molab_integration` |
| [`tests/test_regression_127.py`](../tests/test_regression_127.py) | Adversarial SSE EOF/UTF-8 fragmentation, escaped frame/source markers, strict JSON and local/remote refs, terminal ordering, malformed native/OpenAI data, required tools, old function history, randomized malformed frames, and no fabricated success. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.providers`, `bridge_x.schemas`, `bridge_x.sse`, `bridge_x.tools`, `tests.conftest`, `tests.test_molab_integration` |
| [`tests/test_regression_129.py`](../tests/test_regression_129.py) | Old raw argument omission from compatibility history, historical-call echo rejection and sanitization, safe continuation after prior calls, ordinary prose handling, and invalid-name injection exclusion. The secret marker is synthetic test data. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_provider`, `bridge_x.schemas`, `bridge_x.tools`, `tests.conftest`, `tests.test_molab_integration` |
| [`tests/test_release_cli.py`](../tests/test_release_cli.py) | Missing/placeholder configuration without SQLite creation, CLI fake override, optional empty dummy token, occupied loopback port without touching its listener, and non-overwriting template setup. | `tools` |
| [`tests/test_sandbox_runner.py`](../tests/test_sandbox_runner.py) | Temporary write/edit/read/patch/Python execution, Unicode paths, traversal/symlink rejection, hash/conflict checks, nonzero exits, binary-file refusal, and prohibition of non-Python entry points. The symlink case can skip on Windows. | `bridge_x_test_runner.runner` |
| [`tests/test_schema125.py`](../tests/test_schema125.py) | Exact Edit/nested schemas in compatibility guidance, missing/extra/nested-field errors without value leakage, valid typed structures, prose non-execution, and a simulated adapter schema failure. | `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_provider`, `bridge_x.schemas`, `bridge_x.tools`, `tests.conftest`, `tests.test_molab_integration` |
| [`tests/test_sse.py`](../tests/test_sse.py) | Incremental multiline/comments/CRLF/UTF-8 parsing, EOF truncation, limits, invalid Unicode, generic text/tool/terminal decoding, DONE semantics, and safe upstream errors. | `bridge_x.errors`, `bridge_x.providers`, `bridge_x.sse` |
| [`tests/test_stress.py`](../tests/test_stress.py) | Synthetic 55-tool large request, 100,000 small SSE frames, and safe compaction of a 500-message tool history; correctness checks rather than throughput measurements. | `bridge_x.config`, `bridge_x.context`, `bridge_x.gateway`, `bridge_x.sse` |
| [`tests/test_tools.py`](../tests/test_tools.py) | Strict JSON/native intent schema, exact tool/choice/parallel rules, no fenced-JSON scavenging, malformed/partial arguments, duplicate/bad declarations, byte and depth limits. | `bridge_x.errors`, `bridge_x.tools` |

## Test support and manual tooling

Ordinary users run documented entry points; they do **not** edit these files for normal setup. Maintainers extend them with targeted checks. `main()` symbols are command entry points, not automatic startup actions.

### `bridge_x_test_runner/__init__.py`

[Open source](../bridge_x_test_runner/__init__.py) · Category: Test support · User edit: **No**.

Empty test-helper package marker; enables imports of the runner without making it a gateway dependency.

### `bridge_x_test_runner/runner.py`

[Open source](../bridge_x_test_runner/runner.py) · Category: Test support · User edit: **No**.

`Sandbox`/`SandboxError` restrict fixture paths, perform hash-checked atomic text edits/strict single-file patches, and run fixed Python files with bounded output; `RunReceipt` carries exit/timeout/output data. Imported by tests, never gateway runtime; not OS isolation.

**Public symbols:** `SandboxError`, `RunReceipt`, `Sandbox`.

### `tools/__init__.py`

[Open source](../tools/__init__.py) · Category: Tooling · User edit: **No**.

Package marker for `python -m tools...` helpers. No gateway startup side effect.

### `tools/configure.py`

[Open source](../tools/configure.py) · Category: Tooling · User edit: **No**.

`main()` copies the example with exclusive creation into a local ignored `.molab_local.json`; repeated invocation preserves an existing file. Depends on the example file, not on credentials.

**Public symbols:** `main`.

### `tools/audit_release.py`

[Open source](../tools/audit_release.py) · Category: Tooling · User edit: **No**.

`scan()`/`main()` inspect a directory or ZIP for forbidden/generated files, home paths, private IP ranges, common key prefixes, and private-key blocks. Reports locations/categories, never matched values. It is a bounded scanner, not a full secret guarantee; ZIP binaries must be inspected separately from text.

**Public symbols:** `scan`, `main`.

### `tools/build_release.py`

[Open source](../tools/build_release.py) · Category: Tooling · User edit: **No**.

`main()` selects an explicit file/directory allowlist, reads `bridge_x.__version__`, refreshes the selected per-file SHA-256 list, writes a ZIP beside the checkout, and writes its outer checksum. Does not automatically include arbitrary new root docs or `.github/`; does not read private credentials.

**Public symbols:** `main`.

**Internal relationships:** `bridge_x`.

### `tools/native_css_acceptance.py`

[Open source](../tools/native_css_acceptance.py) · Category: Tooling / acceptance · User edit: **No**.

`tool()` builds fixture schemas; `main()` runs mocked native Molab events through the actual gateway while the fixture executes temporary Read/Edit/Read/Python actions and returns real receipts. Asserts exact CSS-only bytes, CRLF, Unicode/space paths, unchanged neighbor, and exit code; neither live Molab nor installed ZCode.

**Public symbols:** `tool`, `main`.

**Internal relationships:** `bridge_x.config`, `bridge_x.gateway`, `bridge_x.molab_provider`.

### `LOCAL_HTTP_ACCEPTANCE.py`

[Open source](../LOCAL_HTTP_ACCEPTANCE.py) · Category: Tooling / acceptance · User edit: **No**.

`main()` starts a temporary fake-provider loopback Uvicorn server, checks HTTP/SSE/authentication, gracefully stops only that child, reopens SQLite, and emits a local ignored report. Explicit `--live` and internal fault-injection modes can contact Molab; default is offline. Imported/invoked by recovery tests.

**Public symbols:** `main`.

**Internal relationships:** `bridge_x`, `bridge_x.config`.

### `LIVE_CHECK.py`

[Open source](../LIVE_CHECK.py) · Category: Tooling / live check · User edit: **No**.

`main()` contacts the configured existing local Molab gateway on port 8787, checks version/provider, and makes a text request with safe diagnostics. Explicit manual invocation is live; its test replaces HTTP with a mock. Retained because regression tests import it.

**Public symbols:** `main`.

**Internal relationships:** `bridge_x`, `bridge_x.config`.

## Configuration, documentation, and release files

| Exact path | Category and responsibility | Relationship / questions answered | Should an ordinary user edit it? |
|---|---|---|---|
| [`.gitignore`](../.gitignore) | **Configuration.** Excludes environments, bytecode/test caches, private local configuration/environment values, SQLite/database sidecars, logs, dumps, acceptance output, and coverage artifacts. | Git publication hygiene; never a substitute for staged-diff review. | Maintainers only when generated/private file categories change. |
| [`.github/PULL_REQUEST_TEMPLATE.md`](../.github/PULL_REQUEST_TEMPLATE.md) | **Documentation / GitHub.** Prompts a PR author for the concrete problem, resulting behavior, executed checks, evidence limits, and private-data exclusion. | Used by GitHub when opening pull requests; links conceptually to contribution and file guides. | Contributors fill its sections in a PR; maintainers edit the template. |
| [`requirements.txt`](../requirements.txt) | **Configuration / dependencies.** Pins the 22-distribution runtime dependency closure, including FastAPI/Uvicorn, httpx, Pydantic, JSON Schema, and transitive requirements. | Consumed by manual setup, start.bat when dependencies are missing, and requirements-dev.txt. | Users install it; maintainers update pins with compatibility checks. |
| [`requirements-dev.txt`](../requirements-dev.txt) | **Configuration / dependencies.** Includes requirements.txt plus pinned pytest, pytest-asyncio, Hypothesis, and test dependency closure. | Installs the complete offline regression environment. | Users install for testing; maintainers update and verify pins. |
| [`pytest.ini`](../pytest.ini) | **Configuration / tests.** Limits test discovery to tests and sets function-scoped asyncio fixture loops. | Read by pytest; keeps manual root helpers out of default discovery. | Maintainers only when test organization changes. |
| [`examples/.molab_local.example.json`](../examples/.molab_local.example.json) | **Configuration / example.** Placeholder-only notebook/runtime URL, session ID, optional server token, and explicit headers; all supported connection-file fields. | Source for tools.configure; read_molab_config validates the locally copied form. | Copy/create locally and edit ignored .molab_local.json; never put real values in this example. |
| [`start.bat`](../start.bat) | **Tooling / Windows launcher.** Creates .venv using py -3 or python when missing, checks Python 3.11 and imports, installs runtime requirements if imports fail, forwards CLI arguments, and preserves exit status. | Delegates to bridge_x.__main__; does not validate pins in an existing importable environment or overwrite configuration. | Users run it; maintainers edit only with launcher checks. |
| [`README.md`](../README.md) | **Documentation.** Project entry point: purpose/features, actual startup/API example, client setup, tool/SSE/recovery overview, errors, structure, security, limits, and navigation. | Links the detailed operator, architecture, developer, test, and release guides. | Users read; maintainers update when public behavior changes. |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | **Documentation.** Explains safe reproducible reports, focused changes, required evidence, and offline/live test boundaries. | Entry to DEVELOPMENT, TESTING, SECURITY, and the PR template. | Contributors follow it; maintainers update process guidance. |
| [`CHANGELOG.md`](../CHANGELOG.md) | **Documentation / history.** Reconstructs version-specific changes and distinguishes structured text intent, native frontend tools, later scopes/rate recovery, and reported test evidence. | Uses prior reports without republishing private artifacts; links current QA separately. | Maintainers append verified history; users do not edit for setup. |
| [`RELEASE_NOTES.md`](../RELEASE_NOTES.md) | **Documentation / release.** Summarizes the beta, preserved public distribution, historical acceptance, current repository-doc additions, and known limits. | Links README, original validation summary, current review, and file guide. | Maintainers update for an actual release; users read. |
| [`SECURITY.md`](../SECURITY.md) | **Documentation / security.** Explains loopback/key handling, client permissions, scope/verification trust boundaries, safe sharing, and credential rotation after exposure. | Complements architecture and development debugging guidance; contains no private reporting address. | All users read; maintainers keep boundaries accurate. |
| [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) | **Documentation.** Explains request/provider/native/schema/SSE flows, fresh client IDs, receipt/state semantics, SQLite recovery, execution scopes, pacing, and security. | Maps implementation to four Mermaid component/sequence/state diagrams and FILE_GUIDE imports. | Developers read; maintainers update when implementation changes. |
| [`docs/CONFIGURATION.md`](../docs/CONFIGURATION.md) | **Documentation.** Lists every environment setting, CLI option, endpoint, identity header, error family, connection-file constraint, and effective limits/defaults. | Operator reference grounded in config, __main__, schemas, gateway, and adapters. | Users follow it to edit local settings; maintainers edit the reference. |
| [`docs/CONTENTS_AUDIT.md`](../docs/CONTENTS_AUDIT.md) | **Documentation / historical inventory.** Preserves the earlier public-ZIP file-selection decisions and explanations for excluded original working-folder launchers/artifacts. | Historical scope only; FILE_GUIDE is the current exact repository inventory. | Users read; maintainers clarify scope rather than erase history. |
| [`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md) | **Documentation.** Covers environment setup, package conventions, provider changes, tool pipeline, regressions, safe diagnostics, temporary SQLite, and builder limitations. | Developer workflow tied to actual modules and TESTING commands. | Contributors follow it; maintainers keep instructions verified. |
| [`docs/DOCUMENTATION_QA.md`](../docs/DOCUMENTATION_QA.md) | **Documentation / verification.** Records this documentation task baseline, source preservation, actual validation commands/results, confidentiality scope, and remaining limitations. | Keeps current task evidence distinct from earlier VALIDATION results. | Reviewers read; maintainers update only with actual observed checks. |
| [`docs/FILE_GUIDE.md`](../docs/FILE_GUIDE.md) | **Documentation / inventory.** This complete tree, per-file purpose/responsibility/category/edit guidance, public symbols, and internal import map. | Must match every tracked file; generated review tooling is kept outside the public repository. | Users navigate; maintainers update when tracked paths change. |
| [`docs/GITHUB.md`](../docs/GITHUB.md) | **Documentation / presentation.** Provides About text/topics, navigation, original-artifact scope, future release steps, CI absence, and an optional approved-demo placement. | Connects repository presentation to README, release notes, testing, and builder behavior. | Maintainers use it for settings/releases; users do not need to edit. |
| [`docs/TESTING.md`](../docs/TESTING.md) | **Documentation.** Maps all test groups, complete/focused commands, HTTP/CSS acceptance, Windows checks, external-access commands, and evidence provenance. | Connects fixtures and behaviors to tests; distinguishes simulated transports from installed-client/live work. | Contributors follow it; maintainers update with new behaviors/tests. |
| [`docs/VALIDATION.md`](../docs/VALIDATION.md) | **Documentation / historical evidence.** Preserves earlier clean-install public-release observations, failures and fixes during preparation, scanner scope/false positive, and platform warnings. | Links current QA separately; its external original report is not falsely presented as tracked. | Users/reviewers read; maintainers preserve attribution. |
| [`FILE_SHA256SUMS.txt`](../FILE_SHA256SUMS.txt) | **Generated verification manifest.** SHA-256 of the current tracked repository files except this manifest itself. | Refreshed for this documentation checkout; the frozen ZIP has its own original internal manifest. Builder output has a narrower allowlist. | Do not hand-edit; maintainers regenerate after final file selection. |
| [`bridge-x-12.12.3-beta.1.zip`](../bridge-x-12.12.3-beta.1.zip) | **Release artifact.** Original binary public distribution already on the default branch; preserved byte-for-byte. | Its extracted source is exposed here; later repository docs are not inside this frozen ZIP. Audit contents using ZIP extraction/member inspection. | Users may extract; do not edit or silently replace this versioned artifact. |

## Runtime module dependencies

Direct internal imports from the actual AST, including imports inside functions. Standard-library and third-party dependencies are omitted here; their exact installation pins are in the requirement files. This table is a dependency map, not a claim that every imported compatibility alias is exercised on every request.

| Importing file | Direct project imports |
|---|---|
| `bridge_x/__init__.py` | None |
| `bridge_x/__main__.py` | `bridge_x.__init__`, `bridge_x.config`, `bridge_x.errors`, `bridge_x.gateway`, `bridge_x.molab_provider`, `bridge_x.molab_runtime` |
| `bridge_x/capabilities.py` | `bridge_x.schemas` |
| `bridge_x/config.py` | None |
| `bridge_x/context.py` | `bridge_x.errors` |
| `bridge_x/coordinator.py` | `bridge_x.context`, `bridge_x.journal`, `bridge_x.receipts`, `bridge_x.schemas` |
| `bridge_x/errors.py` | None |
| `bridge_x/execution_scope.py` | None |
| `bridge_x/gateway.py` | `bridge_x.__init__`, `bridge_x.capabilities`, `bridge_x.config`, `bridge_x.coordinator`, `bridge_x.errors`, `bridge_x.execution_scope`, `bridge_x.journal`, `bridge_x.json_utils`, `bridge_x.providers`, `bridge_x.receipts`, `bridge_x.schemas`, `bridge_x.sse`, `bridge_x.tools` |
| `bridge_x/journal.py` | `bridge_x.errors`, `bridge_x.tool_models` |
| `bridge_x/json_utils.py` | None |
| `bridge_x/molab_native.py` | `bridge_x.errors`, `bridge_x.json_utils`, `bridge_x.molab_provider`, `bridge_x.providers`, `bridge_x.tools` |
| `bridge_x/molab_provider.py` | `bridge_x.errors`, `bridge_x.json_utils`, `bridge_x.molab_native`, `bridge_x.molab_runtime`, `bridge_x.providers`, `bridge_x.rate_control`, `bridge_x.sse`, `bridge_x.structured_intent`, `bridge_x.tools` |
| `bridge_x/molab_runtime.py` | `bridge_x.errors` |
| `bridge_x/providers.py` | `bridge_x.errors`, `bridge_x.json_utils`, `bridge_x.molab_provider`, `bridge_x.sse` |
| `bridge_x/rate_control.py` | `bridge_x.errors` |
| `bridge_x/receipts.py` | `bridge_x.json_utils` |
| `bridge_x/schema_engine.py` | `bridge_x.errors`, `bridge_x.json_utils`, `bridge_x.schemas`, `bridge_x.tool_models` |
| `bridge_x/schemas.py` | None |
| `bridge_x/sse.py` | `bridge_x.errors` |
| `bridge_x/structured_intent.py` | None |
| `bridge_x/tool_frames.py` | `bridge_x.errors`, `bridge_x.json_utils` |
| `bridge_x/tool_models.py` | None |
| `bridge_x/tools.py` | `bridge_x.errors`, `bridge_x.json_utils`, `bridge_x.schema_engine`, `bridge_x.schemas`, `bridge_x.tool_frames`, `bridge_x.tool_models` |

The factory/native serialization use lazy imports to avoid eager adapter cycles. No runtime module imports `bridge_x_test_runner`, `tests`, or a manual acceptance script. External runtime dependencies include FastAPI/Starlette, Uvicorn, httpx, Pydantic, jsonschema, and referencing; Python supplies SQLite.

## Local files outside this inventory

`.molab_local.json`, environment secrets, SQLite/WAL/SHM, local logs, transcripts, temporary projects, `.venv`, caches, coverage output, and `.git` internals are local state rather than public tracked files. The example stays placeholder-only. See [SECURITY.md](../SECURITY.md) and [the historical selection audit](CONTENTS_AUDIT.md).
