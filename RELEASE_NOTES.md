# Bridge X 12.12.3-beta.1

This is a separate public distribution prepared from the existing working source. It keeps the native agent architecture and all source tests. No original local credentials, user database, transcripts, or server processes are part of the distribution.

## Included behavior

- OpenAI-compatible streaming/non-streaming chat and validated native frontend calls.
- Tool result reconciliation, independent execution scopes, and persistent operation states.
- Shared pacing and cooldown state; bounded pre-output rate recovery with a single total deadline.
- Correct distinction between expired runtimes, access errors, unreadable native mode, and notebook code mode.
- A loopback CLI with `--port` and offline `--check-config`, non-overwriting example setup, pinned dependencies, and an offline native CSS acceptance utility.

## Publication changes

The public copy removes accumulated launchers and historical private-workspace artifacts from its file selection. Existing parser compatibility code remains. Two root Python helpers remain because regression tests depend on them. Developer home paths in synthetic tests are replaced with generic fixture paths. The working source tree is preserved.

One optional Windows `start.bat` is included as a shortcut to the Python CLI, with initial environment/dependency setup, argument forwarding, and preserved exit codes. It does not overwrite local configuration or stop another server.

## Historical public-release validation

The earlier public-release report records a clean extracted installation on Windows 11 / Python 3.13.13: **468 tests passed, 1 skipped, 0 failures, 0 errors**. The skip is the existing platform-permission symlink test. A Starlette/httpx test-client deprecation warning remains visible. Runtime and test installation, `pip check`, compilation, real loopback HTTP/SSE, graceful shutdown/reopen, and scripted native CSS acceptance passed in that preparation. See [the preserved validation summary](docs/VALIDATION.md) for scope. These are historical observations, not new executions during documentation work.

An initial clean run found a temporary SQLite connection left open by the strengthened HTTP acceptance helper. The release copy now closes that diagnostic connection explicitly; both affected tests pass unchanged. The original working project was not modified. Historical private-workspace counts are not used as current acceptance.

## Known limits

Beta; Windows/Python 3.13 is the local acceptance platform. Upstream availability and quotas remain external. The local native CSS test executes real file operations and a terminal command against scripted upstream events; it is not an installed-ZCode or live-Molab certification. The public preparation does not contact the author's Molab session. See `SECURITY.md` for the scan scope and safe handling of local state.

## Repository documentation update

The repository now exposes the original ZIP's source, tests, example, launchers, and tooling for review alongside expanded English documentation. Runtime/test/tooling bytes and dependency pins remain unchanged from that archive. The original tracked ZIP remains immutable and does not contain later documentation edits. The root checksum manifest describes the checkout; the ZIP's internal manifest describes its original distribution.

Use the [README](README.md) to start, the [file guide](docs/FILE_GUIDE.md) to explore, and [current documentation QA](docs/DOCUMENTATION_QA.md) for checks actually executed in this task. No additional release tag or GitHub release asset is implied by this update.
