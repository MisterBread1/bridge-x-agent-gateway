# Bridge X 12.13.1 — Stable

Start **start.bat** to open the native Windows proxy monitor and start working. Existing Molab configuration and the model **molab-glm** remain compatible.

- **Native GUI:** no browser, window login or manual local.key setup. ENG/RUS switching preserves fields and filters. Start/Stop, connection import/save, port selection, diagnostics and safe report export are in one window.
- **Request visibility:** actual POST/HTTP status, active and error filters, queue/provider/total timing, first model output, payload byte counts and recovery attempts. An SSE failure with HTTP 200 is shown as a failure.
- **Persistent safe logs:** completed request metadata rotates at approximately 1 MiB with three backups. A bounded worker keeps disk IO off the HTTP loop; log failures are visible without stopping requests. No body text, credentials or private runtime URL is collected.
- **Short-request delay:** remove accumulated 30-60 second local spacing after throttling and reduce default foreground spacing to 1 second. Preserve genuine upstream cooldown deadlines, retry hints and failure pressure. Provider timing excludes the local admission queue.
- **Windows bootstrap repair:** recover a project environment missing pip using bundled ensurepip. Distinguish Python, environment, pip, dependency and Tcl/Tk errors. Preserve configuration and journal; never kill another server.
- **Configuration template:** `.molab.example` is in the ZIP root. The separate GitHub asset is labeled `.molab.example` and downloads as `molab.example`, because GitHub strips leading periods. Copy it privately to `.molab_local.json` or use the native configuration form.

The existing Node REPL title repair, long-session compaction, conservative native tool validation and durable receipt recovery are retained. Active instructions or pending executable input that cannot fit safely still return a typed error; they are not silently truncated.

Release gates run the complete offline suite in the source tree and a fresh extracted ZIP, real temporary HTTP/CSS/continuity checks, Windows launcher regressions and installed-package native/legacy UI probes. These validate local behavior with simulated upstreams; they do not certify live Molab speed or every installed ZCode build.

Close your old proxy before starting this build on the same port. Existing processes retain old code until restarted. Older published releases and assets remain unchanged.

[Native window and upgrade guide](docs/WORKBENCH.md) · [Configuration](docs/CONFIGURATION.md) · [Testing](docs/TESTING.md) · [Continuity investigation](docs/AGENT_CONTINUITY.md)
