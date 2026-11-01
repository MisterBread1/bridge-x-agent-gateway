# Native proxy monitor

Double-click **start.bat** on Windows. It repairs missing project pip when possible, installs missing runtime dependencies and opens a native Tk window using `pythonw`. The Molab proxy starts automatically in a worker thread; this shortcut explicitly selects Molab even if a simulator was set in the environment. Python 3.11+ with Tcl/Tk is required; the standard Windows Python installer includes Tcl/Tk as an optional component.

`start-ui.bat`, `python -m bridge_x --desktop` and `python -m bridge_x --ui` open the same window. `python -m bridge_x --headless` starts the terminal server. Explicit arguments passed to `start.bat` use the terminal interpreter; add `--desktop` when a window is wanted.

## First launch

1. Existing local Molab configuration is discovered automatically. If it is missing, use **Connection** to enter the runtime URL, session ID and optional server token, or import an existing JSON configuration.
2. **Save connection** validates the values and atomically replaces the private configuration. Example placeholders are refused. This affects the next request; it does not generate a model response. The token field is masked.
3. **Check Molab access** explicitly reads runtime access and AI mode. It does not start model generation or change mode. Actual native requests check mode and can switch code mode to manual, as before.
4. Keep ZCode's model **molab-glm** and Base URL **http://127.0.0.1:8787/v1**. **Copy API address** copies this address only.

The desktop requires no key entry. Fresh installs keep the existing `molab-local` API default. An explicit `BRIDGEX_LOCAL_KEY` takes precedence. An existing valid 12.13.0 `local.key` is reused automatically for Molab, preserving a client's configured authentication; no new key file is created. A local API key and Molab's server token are separate values. Advanced key helpers remain available for legacy installations.

Choose **ENG / RUS** in the top right. Switching preserves fields, request selection and filters. Only the language preference is saved to `desktop.json` in the user data directory.

## Requests and delays

Each actual HTTP request has a row with method, allowlisted route, status and state. GET health polling is hidden by default; enable **Include health checks** to see it. Filter all, active, or failed/cancelled requests. The monitor retains the most recent 500 rows and 1,000 stage events.

| Measurement | Meaning |
|---|---|
| Queue | Local admission and explicit retry waits. |
| Molab | Runtime-mode check plus upstream transport/stream reception. This includes stream delivery backpressure, not solely model compute time. |
| First model output | Time from local request arrival to first actual upstream text/tool input, including queue time. |
| Total | Complete local HTTP lifetime, including input validation and response delivery. |
| Request / response size | Bytes consumed and emitted by the HTTP application; no body content is retained. |

Select a row for first-output timing, byte counts, recovery attempts and an error code. A failed SSE stream remains **Failed** even when HTTP headers were already sent with status 200. Unknown URL paths appear as `/other`; query strings, headers and request/response text are not collected.

The default foreground start spacing is now **1 second**. Old inflated 30-60 second spacing is discarded on restart; actual persisted cooldown deadlines and rate-limit failure pressure are preserved. Genuine Molab throttling, model time and network delays still apply. The window shows an active cooldown separately.

## Diagnostics and logs

**Run diagnostics** checks Python, pinned dependencies, configuration, journal integrity and unresolved client operations in a worker thread. It does not contact Molab or execute client tools. The port owned by this window is reported as expected. **Check Molab access** is the separate network action.

**Save report** exports recent safe request metadata, stage events, log health and local checks as JSON. It omits chat text, tool arguments, file contents, connection values, local keys and raw client identifiers. The original SQLite journal is private and is not a shareable report.

Native mode writes completed request metadata beside the selected journal: a journal named `journal.sqlite3` produces `journal.requests.jsonl`. Each file is limited to approximately **1 MiB**, with three rotating backups. Disk IO runs in a separate bounded worker queue; log failure does not stop HTTP requests. A footer warning reports unavailable logging or dropped records. In-memory journals do not produce disk logs. The terminal server retains its existing sanitized event logging.

## Stop, restart and upgrade

**Stop** shuts down only the proxy owned by this window. Active requests require confirmation because they will be cancelled. Closing the window waits for that proxy to shut down while keeping the UI responsive. An occupied port or journal produces an actionable error; no existing process is killed. Choose another port under **Connection** if needed. Independent simultaneous instances also require separate journals.

Before upgrading, use `python -m bridge_x backup --output <new-backup.sqlite3>` with the existing journal selected. SQLite's backup API includes committed WAL state and refuses an existing destination. Finish outstanding client actions, close your old proxy and start the new build. Already-running Python processes retain old imported code until restarted. Keep your private configuration and journal.

Without explicit paths, state lives under `%LOCALAPPDATA%/BridgeX` on Windows. Existing project configuration and working-directory journals are discovered without moving them. Keep an explicit `BRIDGEX_JOURNAL_PATH` when resuming an existing installation. Unknown newer database schemas are rejected without resetting their version.

The 12.13.0 authenticated web endpoints remain available in terminal mode for compatibility. Desktop mode does not install those endpoints. Tool execution and permission controls remain in ZCode.
