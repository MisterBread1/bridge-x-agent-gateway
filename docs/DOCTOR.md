# Bridge X Doctor

[README](../README.md) · [Configuration](CONFIGURATION.md) · [Continuity investigation](AGENT_CONTINUITY.md)

Run from a complete checkout or extracted package:

```powershell
python -m bridge_x doctor
```

Doctor reports **PASS / WARNING / ERROR** with a concrete next action. It checks Python, installed dependency pins, local configuration/URL syntax, local authorization settings, provider mode, port availability and SQLite integrity/unresolved operations. It never prints configured private values, stops a server, starts a provider, changes runtime mode, runs client tools or migrates the journal. Configuration syntax does not establish remote availability. A busy port may simply mean your gateway is already running. A port probe binds and immediately releases a loopback socket; it accepts no requests.

To check an offline installation without Molab configuration:

```powershell
python -m bridge_x doctor --provider fake --port 0
```

Warnings do not fail the command; errors return exit code 2. Missing/mismatched runtime pins produce a warning and an installation recommendation. The command can run before server dependencies are installed; Molab syntax inspection then requires installing those dependencies first. Values from invalid environment settings are also hidden. No package installation happens automatically.

## Optional local network check

```powershell
python -m bridge_x doctor --network --port 8787
```

This explicitly probes **only `GET http://127.0.0.1:8787/health`**, with a two-second timeout, no authentication header and no redirects/proxy handling. It verifies the reported Bridge X version. It does not contact Molab, an external provider or a runtime URL, and does not test agent execution. Without `--network`, doctor makes no HTTP request.

## Sanitized Issue report

```powershell
python -m bridge_x doctor --report bridge-x-doctor-report.json
```

The file must be a new writable name; an existing report is never overwritten. It contains check statuses/recommendations, Bridge X/Python versions and up to 100 sanitized event rows from the existing journal. Unknown database fields and non-allowlisted event/error categories are not exported. Review it before attaching to an Issue. No report is uploaded automatically.

When a gateway is running, an authenticated `GET /diagnostics/report` also returns the sanitized timeline. Supply your local Bearer key privately through your client. The older `/diagnostics` route remains available for local operational inspection; use the new report for sharing because it uses a stricter export allowlist. Neither route proves task completion.

For a stopped agent, retain the report, safe error code and response finish reason. State whether the client returned a real exit code. Preserve the journal and investigate actual file/command effects before repeating a mutation with an unknown outcome.
