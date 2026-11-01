# Testing

[README](../README.md) В· [Development](DEVELOPMENT.md) В· [File guide](FILE_GUIDE.md) В· [Documentation review](DOCUMENTATION_QA.md)

The default suite is **offline with simulated providers**. Some tests run actual local HTTP servers and execute Python or file operations in temporary directories. They do not contact a live Molab runtime or operate an installed ZCode client. Test filenames containing `molab`, `integration`, or `live` do not change that distinction.

## Run the complete suite

From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q -ra
```

Do not inherit a real provider's `BRIDGEX_*` settings into a test run. In a fresh shell, leave those variables unset; the fixtures supply dummy configuration and temporary journals. Installation downloads dependencies; test execution uses local fixtures. `pytest.ini` limits discovery to `tests/` and uses function-scoped asyncio fixture loops. Parametrization means collected cases outnumber test functions.

## Continuity and Doctor regressions

Run `python -m pytest tests/test_continuity.py tests/test_doctor.py -q` and `python -m tools.continuity_acceptance`. The long fixture checks seven unique actions across eight SQLite reopens, real CSS edits, unchanged neighbors and two empty-stdout Python checks, in JSON and SSE modes. The peer validates all preceding native receipt/input pairs before advancing. This is simulated upstream protocol evidence, not live model reasoning. See [baseline failures and release gate](AGENT_CONTINUITY.md).

## Coverage by behavior

| Area | Relevant modules and what they establish |
|---|---|
| Tool/schema unit tests | `test_tools.py`, `test_schema125.py`, `test_read_integer_fix_12101.py`, `test_read_integer_fix_12102.py`: declared names, required/extra fields, nested constraints, typed arguments, and narrowly permitted integer conversion. |
| SSE unit tests | `test_sse.py`, `test_property_protocols.py`: incremental UTF-8/CRLF framing, arbitrary chunk boundaries, multiline events, limits, and incomplete EOF rejection. |
| Provider transport integration | `test_provider_transport.py`, `test_molab_integration.py`: mocked `httpx` upstream, payload/history translation, HTTP/SSE errors, terminal contracts, and sanitized diagnostics. |
| Native tools | `test_native_molab.py`: frontend schemas, dynamic history/results, completed-input events, mode checks, malformed sequences, and no executable text fallback in native mode. |
| HTTP gateway | `test_gateway.py`: authentication, request bounds, JSON/SSE responses, heartbeat behavior, actual temporary file/Python execution by a test client, and receipt continuation. |
| Sequential scopes | `test_execution_branches.py`: foreground versus memory coordination, one native action when parallel calls are disabled, replanning after receipts, and stable scope after restart. |
| SQLite recovery | `test_agent_recovery.py`, `test_journal_context.py`: reopen, missing receipts, idempotency, ownership conflicts, transaction rollback, client hash readback, and safe context bounds. |
| Rate control | `test_rate_control.py`, `test_rate_recovery.py`: pacing, priority, persistent cooldowns, retry hints, bounded pre-output retries, no retries after partial output, cancellation, and one absolute deadline. |
| Text compatibility regressions | `test_regression_124.py`, `test_command_engine_128.py`, `test_dispatch_root_cause_12103.py`: legacy/v2 frames, literal markers in prose/source, required final delimiters, schema checks, and no speculative dispatch. |
| Output/history regressions | `test_output_budget126.py`, `test_output_regression_1210.py`, `test_regression_129.py`: advisory action budgets, bounded adaptation, history echo rejection, and exclusion of old raw arguments from compatibility prompts. |
| Boundary hardening | `test_audit_hardening.py`, `test_regression_127.py`: duplicate keys, invalid Unicode, non-finite numbers, forbidden remote refs, late events, safe headers/errors, and bounded terminal output. |
| Temporary executor | `test_sandbox_runner.py`: relative-path restrictions, symlink/traversal rejection, exact edits/patches, hash preconditions, and Python result classification. |
| CLI | `test_release_cli.py`: syntax-only config errors, non-overwriting template, explicit fake selection, optional dummy token, and occupied-port handling. |
| Release packaging | `test_release_packaging.py`: complete docs/workflows, stable prefix, valid checksums, repeatable output, unchanged checkout manifest, refusal to overwrite another asset, and private-file exclusion. |
| Synthetic stress | `test_stress.py`: 55 declared tools with a large request, 100,000 small SSE frames, and compaction of a 500-message tool history. These are correctness scenarios, not performance benchmarks. |

All file roles and cross-test fixture imports are listed in [FILE_GUIDE.md](FILE_GUIDE.md).

## Focused regression commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_sse.py tests/test_provider_transport.py tests/test_property_protocols.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_native_molab.py tests/test_execution_branches.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_agent_recovery.py tests/test_journal_context.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_rate_control.py tests/test_rate_recovery.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_release_cli.py
```

Run the relevant group during implementation, then the full suite before publishing executable changes. A docs-only update should validate links, paths, diagrams, inventory, source preservation, and example commands. The review recorded in [DOCUMENTATION_QA.md](DOCUMENTATION_QA.md) also includes an offline full-suite run.

[Offline CI](../.github/workflows/ci.yml) runs the complete Windows/Python 3.13 suite and independent acceptance checks for main pushes and PRs. [Beta publishing](../.github/workflows/release.yml) repeats validation on main before creating a versioned release with the complete ZIP and checksum. These files configure checks; passing status requires an actual completed Actions run.

## Independent local acceptance

```powershell
.\.venv\Scripts\python.exe LOCAL_HTTP_ACCEPTANCE.py
.\.venv\Scripts\python.exe -m tools.native_css_acceptance
```

The HTTP helper allocates a free loopback port, starts its own fake-provider Uvicorn process with a temporary journal, checks version/auth/models/SSE, shuts down through a private parent pipe, and reopens SQLite. It writes `local_http_acceptance_result.json`, which is ignored. `test_agent_recovery.py` also invokes this helper twice to catch Windows file-lock cleanup regressions. These checks do not use the user's listener on 8787.

The CSS acceptance script mocks native Molab HTTP events but uses a real temporary Unicode/space directory and real client-side Read в†’ Edit в†’ Read в†’ Python-check actions. It checks exact CSS-only bytes, the unchanged neighbor, CRLF, exit status, and four returned receipts across five upstream fixture requests. Its `Bash` label represents a client tool; the fixture invokes a fixed Python checker without running arbitrary shell text. The gateway never executes it.

## Windows checks

The symlink escape test skips if Windows cannot create symbolic links; a skip is not proof that the symlink branch ran. Unicode filenames, spaces, CRLF preservation, subprocess UTF-8, and SQLite cleanup receive separate coverage. Use context-managed clients and close connections before removing temporary files. The HTTP helper's forced shutdown fallback applies only to its own test process tree.

The earlier public-release acceptance report separately checked `start.bat` in a fresh environment: setup, forwarded arguments, error exit codes, repeat invocation, and Unicode/space paths. Those results are historical; the current documentation pass does not relabel them as a newly tested clean installation.

## Commands requiring external access

| Command/action | External or existing-state effect |
|---|---|
| Install requirements | Downloads packages from the configured package index. |
| Native Molab CLI launch | Reads the operator's configured runtime; can change AI mode from code mode to manual. |
| `python LIVE_CHECK.py` | Contacts the existing local gateway on 8787 and sends a live Molab text request. |
| `python LOCAL_HTTP_ACCEPTANCE.py --live` | Starts a separate gateway and sends a live-provider request with the operator's configuration. |
| Installed ZCode acceptance | Runs the real client against an explicitly selected gateway/provider and a disposable project. No general installed-client acceptance script is supplied in this public source set. |

Run live checks only with explicit authorization for the current runtime, selected client, and temporary project. Do not infer live compatibility from offline results or silently switch provider on failure. No external provider calls are part of this documentation task.

## Evidence and historical results

[VALIDATION.md](VALIDATION.md) preserves the previous clean public-release report: **468 passed, 1 skipped** on Windows/Python 3.13.13, with HTTP and scripted CSS acceptance. [DOCUMENTATION_QA.md](DOCUMENTATION_QA.md) records the commands actually run during this repository polish. Historical installed-ZCode observations are summarized separately in [CHANGELOG.md](../CHANGELOG.md); they do not certify current upstream behavior.

The existing Starlette/httpx test-client deprecation warning should remain visible. Do not remove a test, suppress warnings, or convert a failure to a skip just to obtain a clean headline.

## Stable publication gate

`python -m tools.verify_release <complete.zip> --work-dir <temporary-directory>` validates exact archive checksum coverage and installs a fresh Python environment from that extracted ZIP, then runs pip check, compileall, full pytest, HTTP smoke, native CSS acceptance, and syntax-only fake startup. It downloads test dependencies and never contacts a live model. The release workflow requires this gate before publication. `test_release_verification.py` tests traversal/wrong-root rejection, missing manifest coverage, and the named-media audit boundary.
