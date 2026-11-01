# Development

[README](../README.md) · [Architecture](ARCHITECTURE.md) · [File guide](FILE_GUIDE.md) · [Testing](TESTING.md)

## Set up a checkout

Run commands from the directory containing `bridge_x/` and `requirements.txt`. Python 3.11+ is required; the recorded acceptance platform is Windows/Python 3.13.13.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m bridge_x --help
.\.venv\Scripts\python.exe -m bridge_x --provider fake --check-config
```

`requirements-dev.txt` includes the pinned runtime closure. Package installation needs download access; the offline test scenarios do not need a provider account. There is no `pyproject.toml` or editable-install package in this version. Run from the source root so local packages and the two root test helpers are importable. For a POSIX shell, use `.venv/bin/python`; that command form does not imply a certified platform.

## Directory conventions

`bridge_x/` owns the gateway and protocol logic. Keep provider-specific serialization in its adapter, common schema rules in `schema_engine.py`, receipt coordination in `coordinator.py`/`journal.py`, and bounded stream framing in `sse.py`. Put regression tests in `tests/` and manual helpers in `tools/`. `bridge_x_test_runner/` belongs only to tests. The [file guide](FILE_GUIDE.md) explains every file, including retained historical test names.

`Settings()` is an injectable library/test configuration: fake provider, structured compatibility mode, no pacing or retries by default. `Settings.from_env()` is the CLI configuration: Molab, native mode verification, pacing, and up to two safe rate retries. Never assume those defaults are interchangeable. `.env` files are not loaded.

## Extend or modify a provider

1. Implement an async `generate(req, messages)` iterator using the events from `providers.py` and the `Provider` protocol in `capabilities.py`.
2. Keep provider connection settings explicit. Extend `Settings`, environment validation, CLI choices, `make_provider()`, and capability declarations if adding a selectable provider.
3. Translate only documented/observed provider fields. Emit native argument **JSON text** in `NativeToolDelta`. Do not allocate client-facing IDs or execute tools in the adapter; shared validation creates `ToolCall` IDs.
4. Bound input/output and preserve cancellation. Yield `Finish` only after checking the full terminal contract; a late failure must override provisional completion.
5. Return sanitized typed failures. Keep secrets, request bodies, and remote error strings out of exceptions and diagnostics.
6. Add simulated-transport tests for valid text, valid tools, malformed JSON, truncated streams, late errors, timeout/cancellation, and HTTP failures. Use `test_provider_transport.py` and `test_native_molab.py` as patterns.
7. Update the environment/API reference, architecture, capability description, and file inventory if imports or files change.

Molab retries have stricter conditions than a generic retry flag. Do not enable transparent recovery for an unknown outcome or for notebook-side execution. Changes to native events must cover both the assembler and gateway behavior, including `parallel_tool_calls: false`.

## Follow the tool pipeline

Read `gateway.py` → `ToolCoordinator.prepare()` → adapter `generate()` → `tools.validate_native()` / compatibility `parse_intent()` → `schema_engine.validate_specs()` → `ToolCoordinator.dispatch()` → `Journal.deliver()`. On the next client request, original transcript receipts are reconciled **before** context compaction.

Test the behavior visible to the client: exact schemas/types, complete arguments, local call IDs, a real matching result, and no new dispatch on ambiguous retry. Preserve strict handling of duplicate JSON keys, remote schema references, incomplete native input, and SSE errors after finish. The [architecture](ARCHITECTURE.md) documents the narrow `Read` integer compatibility rule.

## Tests and local acceptance

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q tests/test_native_molab.py tests/test_execution_branches.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_agent_recovery.py tests/test_rate_recovery.py
.\.venv\Scripts\python.exe LOCAL_HTTP_ACCEPTANCE.py
.\.venv\Scripts\python.exe -m tools.native_css_acceptance
```

The HTTP command starts and closes its own fake-provider loopback process. The CSS command uses scripted native upstream events with real temporary file/Python actions. Neither command certifies live ZCode or Molab. See [TESTING.md](TESTING.md) for targeted suites, Windows skips, and external-access commands.

## Temporary SQLite and safe debugging

Prefer `Settings(journal_path=":memory:")` for disposable in-process tests. Use pytest's `tmp_path` for reopen/migration checks. Close `Journal` in `finally`, or use a context-managed `TestClient` so app lifespan closes it. A `with sqlite3.connect(...)` transaction context does not itself close the connection; explicitly close it or use `contextlib.closing`, especially before Windows temporary-directory cleanup.

For a manual offline server, choose a separate journal and port:

```powershell
$env:BRIDGEX_JOURNAL_PATH = Join-Path $env:TEMP 'bridge-x-dev.sqlite3'
.\.venv\Scripts\python.exe -m bridge_x --provider fake --port 18787
```

Use a unique journal filename for independent development sessions. Reusing one intentionally tests persistence. Stop only the process you started. Avoid an existing user's port, config file, and database. Remove or reset your shell's `BRIDGEX_JOURNAL_PATH` when returning to normal use.

Inspect sanitized `/diagnostics` and operation state first. Never add logging of full prompts, headers, native input bodies, or client output. Debug fixtures should use obvious dummy values and temporary directories. The helper named `Sandbox` limits test paths and commands; it does not isolate arbitrary Python from the operating system.

## Common pitfalls

| Pitfall | Required behavior |
|---|---|
| Treating `Finish` as sufficient success | Drain the stream; honor later errors and each adapter's end-marker contract. |
| Returning partial tool deltas early | Buffer until complete input, terminal validation, schema validation, and durable dispatch. |
| Returning an upstream ID to the client | Shared validation allocates the local ID used by the journal and receipt. |
| Reusing one idempotency key for progressed steps | A key identifies one dispatch request; progress the transcript and use a new logical key. |
| Compacting before reconciliation | Recover receipts from original call/result history first. |
| Relaxing schema validation to fix one tool | Add a focused regression; keep normalization narrow and schema-guided. |
| Calling `LIVE_CHECK.py` during offline validation | That manual command contacts the configured gateway/provider. Its regression test mocks HTTP. |
| Building a ZIP and expecting the whole checkout | The builder selects an allowlist; read the publication notes below. |

## Publication tooling

`python -m tools.build_release --output-dir artifacts` selects runtime/tests/tools/docs, the example, requirements, contribution guide, and GitHub Markdown/workflows. It creates `bridge-x-12.13.0-complete.zip` and `SHA256SUMS.txt` in that ignored output directory. The archive root is always `bridge-x-12.13.0/`, independent of checkout folder name. Files are ordered and timestamps fixed; identical input/toolchain yields repeatable bytes. Different pre-existing outputs are refused; choose a fresh output directory when inputs change.

The per-file checksum list is generated **inside the archive**, leaving the tracked checkout manifest unchanged. The original tracked ZIP is excluded from the complete archive and preserved. Symlink/escaped selected inputs are rejected. `tests/test_release_packaging.py` verifies complete docs, immutability, repeatability, and private-file exclusion.

GitHub [CI](../.github/workflows/ci.yml) runs offline regressions on main pushes and PRs. The [release workflow](../.github/workflows/release.yml) independently validates main before publishing a verified ZIP/checksum on version or publisher changes, or manual dispatch. Existing releases are left untouched. It uses the existing ephemeral Actions token with contents-write limited to the publishing job. No live-provider secret is required.
