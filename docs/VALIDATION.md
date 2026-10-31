# Public release validation

**Historical evidence:** this page preserves the earlier public-release preparation report. It is not a newly executed clean installation. For checks run during repository documentation, see [DOCUMENTATION_QA.md](DOCUMENTATION_QA.md); for reproducible commands, see [TESTING.md](TESTING.md).

Version: **12.12.3-beta.1**. Local acceptance environment: **Windows 11 (10.0.26200), Python 3.13.13**. The archive was extracted into a new path containing spaces and Unicode. A new `.venv` was created there; it did not reuse the working gateway's environment, configuration, or journal.

## Clean installation results

| Check | Observed result |
|---|---|
| Runtime pinned installation | Exit 0; 22 distributions in the runtime dependency closure. |
| Runtime `pip check` | Exit 0. |
| Template creation | Creates placeholders; second invocation preserves the existing file byte-for-byte. |
| Missing / malformed / placeholder config | Explicit errors; no real provider credentials used. |
| Optional token omitted/empty | Syntax-only check succeeds with a demonstration session. |
| Quick Start | Real CLI/Uvicorn on 127.0.0.1:18787, actual PowerShell health and local-key generation commands checked. |
| Local authentication | Unauthenticated chat/diagnostics rejected; authorized requests succeed. |
| HTTP modes | Streaming and non-streaming responses checked. |
| Occupied port | CLI exits 2 with PORT_UNAVAILABLE; existing listener remains. |
| Stop / reopen | Two server lifetimes, graceful Uvicorn shutdown, exit 0, same SQLite reopened successfully. |
| Development install / `pip check` | Exit 0. |
| `compileall` | Exit 0 for runtime, tests and tools. |
| Full pytest | **468 passed, 1 skipped, 0 failures, 0 errors**. Clean-run wall time approximately 56 seconds. |
| Independent HTTP smoke | Actual temporary loopback server; SSE success, no error, exit 0, forced_shutdown=false, SQLite reopened. |
| Native CSS acceptance | Read -> Edit -> Read -> Bash/Python, exit 0, exact CSS-only bytes, neighbor unchanged, CRLF preserved, all four receipts returned across five upstream fixture requests. |

The native scenario uses scripted native Molab wire events and a real local filesystem/terminal executor. It is **not** an installed-ZCode integration or a live-Molab test. No external model request or access to the author's runtime was performed. Package installation downloads dependencies; source, logs, configuration and credentials were not uploaded for validation.

## Regression discovered during preparation

The first extracted run had 466 passing tests, two failures, and one skip. The new SQLite diagnostic check in the HTTP helper used a transaction context manager without closing the connection; Windows correctly refused temporary-file cleanup. The public helper now uses explicit connection closing. Both original tests remain and pass; no failed test was removed, weakened, or converted to a skip.

## Secret and artifact audit

- Only runtime Python, all source tests, their required helpers, pinned requirements, new tools/docs, and an example configuration were selected. No source `.git`, local configuration, environment file, SQLite/WAL/SHM, model transcript, log, cache, virtual environment or prior artifact is part of the public project/ZIP.
- **detect-secrets 1.5.0** scanned the selected folder and a fresh extraction of the ZIP with `scan --all-files --no-verify`. Network credential verification was disabled. A separate synthetic positive control produced two detections, confirming active detection.
- The scan union found one reviewed **Secret Keyword** false positive: the `secret_marker` constant in `tests/test_regression_129.py`, in `test_historical_calls_dont_include_raw_argument_json`. It is a short synthetic content marker repeated 1000 times to test history compaction, not an authentication value. Its value is not reproduced in audit output. No plugin was disabled and no blanket exclusion was added to conceal it. Path-dependent scanner filters can produce different candidate counts; both targets were checked.
- Custom checks cover forbidden/generated file categories, developer home paths, common key prefixes/private-key blocks, private IPv4 addresses, and non-demonstration Molab URLs. No unresolved finding was observed in that scope.
- The example contains only supported fields and obvious placeholders. User-specific paths in two old synthetic fixtures were replaced by a generic example path. Required source tests were retained.
- Local README links were resolved. ZIP membership, per-file SHA-256 and the external archive SHA-256 are checked by the final release gate. Code and dependencies are compared against the extracted tested copy; documentation updates are re-audited.
- The preparation did not open the author's private connection file to compare credential values, audit unknown previous repositories, or assert that previously published secrets do not exist. No absolute guarantee of detecting every possible secret is made.

## Warnings and scope limits

The existing symlink test skips where Windows does not permit symbolic links. The Starlette/httpx test-client deprecation warning is retained. Other OS/Python versions and current live-provider behavior were not certified. The generated configuration still requires the new operator's valid runtime values. These are disclosed limitations; no runtime or confidentiality blocker was found in the checked public scope.

The earlier publication decision and exact digest were recorded in a separate `RELEASE_ACCEPTANCE_REPORT.md` beside the prepared ZIP in the local release-output directory. That external report is not a tracked repository file and is not linked as though it were present. The report states that 56 selected original working-project files matched their pre-copy hashes. The frozen ZIP and current repository have separate checksum scopes described in [GITHUB.md](GITHUB.md#preserved-original-artifact).
