# Bridge X v12.12.3 — First Stable Release

## Overview

Bridge X is a local OpenAI-compatible AI agent gateway. It translates provider events, validates tool proposals against client schemas, and coordinates execution receipts in SQLite. Tools run in the client, not in the gateway.

This first stable release covers the verified local gateway workflow on Windows/Python 3.13. It does not certify current live-provider availability, every installed client, every operating system, or production workloads of arbitrary duration. The previous beta release is retained unchanged.

## Highlights

- Streaming and non-streaming Chat Completions with authenticated local endpoints.
- Native frontend tool inputs validated before client delivery.
- Sequential client workflows and separate foreground/background execution scopes.
- Durable receipts, duplicate-dispatch protection, and SQLite restart recovery.
- Bounded pre-output rate recovery, truthful terminal SSE errors, and sanitized diagnostics.
- Complete English documentation, structured issue forms, and two clearly labeled architecture GIFs.

## Native tool calling

Native start/delta/available events must form complete, consistent arguments and pass the declared JSON Schema. The client applies its permissions, executes the tool, and returns the actual result with the gateway's local call ID. A proposal or dispatch is never evidence of execution. Compatibility parsers remain available without becoming the default native path.

## SSE support

Strict incremental UTF-8 framing, bounded input, heartbeat comments, cancellation, and late-error handling are checked. An SSE error after HTTP 200 does not receive a fabricated successful DONE marker. Executable arguments stay buffered until safe terminal and schema validation.

## SQLite state recovery

The journal records operation transitions, receipt provenance, request fingerprints, scopes, and cooldown metadata. Original transcript call/result pairs are reconciled before context compaction. Unknown effects are not silently rerun. Verification compares digests supplied by the authenticated client; it does not independently inspect the client's filesystem.

## Installation

Extract `bridge-x-12.12.3-complete.zip`, open its project directory, then run in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m bridge_x --provider fake --port 18787
```

The fake provider is an offline simulator. Follow the README to create your own local runtime configuration and unique gateway key before using a real upstream. `start.bat` remains the optional Windows shortcut.

## Verification results

Publication is gated on a full source regression run and a **new Python environment from the extracted final ZIP**: dependency install, pip check, compileall, full pytest, HTTP/SSE smoke, native CSS/file/Python acceptance, and syntax-only fake startup. Schema, SQLite recovery, explicit 429 handling, receipt ownership, and stream failure cases are included in pytest. Final ZIP/file SHA-256 and offline secret scanning are checked. Exact observations and limitations are in [stable verification](docs/STABLE_RELEASE.md) and the matching GitHub Actions run; historical beta counts are not used as new stable results.

The local clean extracted candidate passed **478 tests**, with one Windows symlink-permission skip and one existing Starlette/httpx warning; all seven clean-environment gate commands succeeded. Hosted PR/main and final-ZIP checks run independently before publication. The independent CSS scenario uses scripted upstream events with genuine temporary client file operations and Python execution. No live Molab or installed-ZCode run is claimed for this release acceptance.

## Known limitations

Beta history is preserved, while stable scope is deliberately limited to tested functions. Provider quotas, runtime expiration, interface changes, process-local pacing, client permissions, and external connectivity remain constraints. Windows symlink permissions may cause the existing test to skip locally; the Starlette/httpx test-client warning remains visible. Other environments and sustained production loads are not universally certified.

## Download

The stable GitHub Release attaches `bridge-x-12.12.3-complete.zip` and `SHA256SUMS.txt`. The archive contains an independent per-file checksum manifest, source, tests, documentation, both GIFs, community configuration, and placeholder-only examples. It excludes credentials, local databases, logs, caches, environments, and older nested ZIPs.

## Documentation

Start with [README](README.md), then [configuration](docs/CONFIGURATION.md), [architecture](docs/ARCHITECTURE.md), [file guide](docs/FILE_GUIDE.md), [development](docs/DEVELOPMENT.md), [testing](docs/TESTING.md), and [community administration](docs/COMMUNITY_SETUP.md).
