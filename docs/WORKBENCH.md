# Local operator workbench

Start `start-ui.bat` on Windows, or `python -m bridge_x --ui`. Add `--no-browser` when opening the printed loopback URL yourself. This starts one gateway with its own local workbench; it does not stop an existing process. Choose another port and a separate data directory for a parallel test instance. A second CLI process cannot share the same journal.

## First connection

1. Open the personal `local.key` file on the login screen, or explicitly run `python -m bridge_x key` and paste the key locally. Startup logs and page URLs contain no key. An explicit nondefault `BRIDGEX_LOCAL_KEY` takes precedence.
2. Under **Connection**, enter the current Molab runtime chat URL, marimo session ID and optional server token. The whole new configuration is saved atomically to the configured private file. Existing values are never reflected into the browser. Saving does not send a provider request.
3. **Check runtime** reads access and AI mode only. A separate confirmed action can switch code mode to manual. A successful mode check does not establish model generation success.
4. Copy the displayed loopback Base URL and model `molab-glm` to ZCode, with the same personal local key. Client tools and permissions remain in ZCode.

The key stays in browser memory, with no localStorage or cookie persistence. Reloading requires login again. UI APIs require the key, loopback Host and same-origin requests. Assets have a restrictive CSP, no external fonts/scripts and no telemetry.

## Session and recovery

The action list reads the actual SQLite ledger, 50 entries per page. The inspector shows real state and outcome category. It does not show file content or execute commands. A missing receipt, unknown outcome, cancellation or timeout is displayed explicitly.

A later genuine receipt can resolve cancellation/timeout. Alternatively, check actual consequences in ZCode, stop the uncertain execution, and enter matching expected/observed SHA-256 digests under **Confirm check**. The ledger records `RESOLVED_BY_CHECK`; this establishes client-attested consequences, not an exit code or completion of the whole task. Continue from ZCode after inspecting the result.

**Diagnostics** exports only the allowlisted safe report. The journal's raw IDs and private configuration are not an Issue attachment.

## Upgrade and backup

Run `python -m bridge_x backup --output <new-backup.sqlite3>` with the old journal selected. SQLite's backup API includes committed WAL state; an existing destination is never overwritten. Keep backups private. Then finish or stop outstanding client actions and restart your gateway from the new build; already-running Python processes retain imported old code until restarted. No update command kills another server.

Without explicit paths, data lives under `%LOCALAPPDATA%/BridgeX` on Windows. Existing project configuration and working-directory journals are discovered without moving them. Keep an explicit `BRIDGEX_JOURNAL_PATH` when resuming an existing installation. Schema 5 adds check evidence and indexes in the same database. A newer unknown schema is rejected without resetting its version.

## Long sessions

Large completed outputs are compacted before provider submission, including recent tool outputs that previously bypassed shortening. Complete historical exchanges can be archived as whole pairs, with a neutral marker. Original receipts are reconciled first. The original goal, user/system instructions and pending arguments are retained. One smaller request may follow an explicit context rejection before output, with no client tool replay. Irreducibly large active input still needs fewer attachments or enabled tools; the bridge will not truncate a pending Edit/Bash command to make it fit.

## Installation

The complete ZIP includes UI assets and both Windows launchers. For an installed command, run `python -m pip install .` in the extracted directory, then `bridge-x --ui`. Build tooling is separate from gateway runtime dependencies. Release verification checks the installed UI outside the source directory.
