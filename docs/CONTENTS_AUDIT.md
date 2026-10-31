# Publication inventory

[README](../README.md) · [Complete current file guide](FILE_GUIDE.md) · [Repository review](DOCUMENTATION_QA.md)

This page records the **earlier public-ZIP selection**, not the current repository's exact file inventory. The latter is maintained in [FILE_GUIDE.md](FILE_GUIDE.md). Original working-project launchers described below were excluded before this documentation task; no files are deleted by the repository polish.

Only explicitly selected runtime, tests, and newly written publication files were copied. The working project, private configuration, database, Molab session, and listener on 8787 were not changed by this preparation.

| Category | Decision |
|---|---|
| `bridge_x/*.py` | Keep the complete runtime and its imports, including legacy compatibility parsers. |
| `tests/*.py` | Keep every existing test. Add release-only CLI checks. Replace developer home paths in synthetic fixtures with `C:\ExampleProject`; assertions and behavior remain. |
| `bridge_x_test_runner/*.py` | Keep: tests import its isolated filesystem/terminal helper. Not imported by the gateway. |
| `LOCAL_HTTP_ACCEPTANCE.py` | Keep: an existing test invokes its real loopback server and private shutdown pipe. Default is offline; explicit live modes are not run for this release. |
| `LIVE_CHECK.py` | Keep: a regression imports and mocks it. Its explicit manual command is not offline. |
| `requirements*.txt`, `pytest.ini` | Keep pinned runtime/test closures and test configuration. No development packages in runtime unless required transitively by a runtime distribution. |
| `tools/` | New local template creator, scripted native CSS acceptance, offline publication audit, and allowlisted ZIP builder. |
| `examples/` | Only supported configuration fields with obvious placeholders. No real local file. |
| `docs/`, README, release notes, security, changelog | New publication documentation. Historical reports inform the changelog but are not copied as current acceptance evidence. |

## Audited Windows launchers

One public `start.bat` is included at the user's request. It creates the local environment and installs pinned runtime dependencies if needed, forwards arguments to the Python CLI, and preserves its exit code. The following original launchers remain in the working source and are excluded:

| Original script | Reason |
|---|---|
| `START_WINDOWS.bat` | Combined installation/start with a fixed port; replaced in this copy by documented venv installation and `python -m bridge_x`. |
| `CHECK_ACTIVE_BRIDGE_WINDOWS.bat`, `CHECK_SERVER_WINDOWS.bat` | Fixed-port duplicate checks; health and version are available through the documented API. |
| `CHECK_MOLAB_CONFIG_WINDOWS.bat` | Replaced by syntax-only `--check-config`. |
| `IMPORT_CONFIG_WINDOWS.bat` | Transfers another private installation; the public template command creates a new example without overwriting. |
| `SETUP_NATIVE_MOLAB_WINDOWS.bat` | Native setup already occurs on explicit Molab CLI startup. |
| `TEST_WINDOWS.bat`, `TEST_REGRESSION_WINDOWS.bat`, `TEST_TOOL_RECEIPTS_WINDOWS.bat` | Duplicate dependency installers/test entry points; use the complete pytest suite. |
| `COMPARE_REQUEST_MODES_WINDOWS.bat`, `LOW_OUTPUT_MODE_WINDOWS.bat` | Experiment/advisory tuning conveniences, not required for runtime. |
| `LIVE_AGENT_ACCEPTANCE_WINDOWS.bat`, `LIVE_CHECK_WINDOWS.bat` | External-session checks excluded from offline release acceptance. |
| `RUN_AGENT_DEMO_WINDOWS.bat` | Legacy demonstration, replaced by explicit native CSS acceptance. |
| `SHOW_UPSTREAM_TRACE_WINDOWS.bat` | Fixed-port helper; authenticated `/diagnostics` is documented. |

There were no root CMD or PowerShell launchers to retain. Internal audit PowerShell files in the working audit directory were not copied. No installation script changes Windows security settings or installs components at runtime.

## Excluded categories

Real local configuration, environment files, database/WAL/SHM, logs, model transcripts, private acceptance records, prior archives, temporary reports, crash/debug output, virtual environments, caches, compiled bytecode, hidden Git history, and superseded historical documentation were excluded from the public ZIP selection. No original source file was deleted. That prepared folder originally had no Git history. The repository now retains its already-published ZIP and exposes its source in a separate documentation branch; the ZIP builder's narrower allowlist is documented in [DEVELOPMENT.md](DEVELOPMENT.md#publication-tooling).

This inventory is a dependency decision, not a claim that every excluded diagnostic was defective. The existing test imports are why the two root Python helpers remain.
