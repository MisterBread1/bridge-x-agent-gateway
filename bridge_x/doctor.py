"""Read-only local checks; never start a gateway, provider or client tool."""
import http.client
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from . import __version__
from .observability import report_events


def inspect(settings, port=8787, network=False):
    checks, events = [], []
    def add(code, status, recommendation):
        checks.append({"code": code, "status": status, "recommendation": recommendation})
    add("PYTHON", "PASS" if sys.version_info >= (3, 11) else "ERROR", "Use Python 3.11 or newer.")
    add("SQLITE_RUNTIME", "PASS", "SQLite " + sqlite3.sqlite_version + "; Bridge X uses rollback journaling on runtimes affected by the upstream WAL reset bug. Upgrade Python for a corrected SQLite runtime.")
    requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
    if not requirements.is_file():
        requirements = Path(__file__).parent / "runtime-requirements.txt"
    try:
        missing = []
        for line in requirements.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            name, version = line.strip().split("==", 1)
            try:
                if importlib.metadata.version(name) != version:
                    missing.append(name)
            except importlib.metadata.PackageNotFoundError:
                missing.append(name)
        add("DEPENDENCIES", "WARNING" if missing else "PASS", "Install the pinned requirements.txt in your project environment." if missing else "Pinned runtime packages are installed.")
    except (OSError, ValueError):
        add("DEPENDENCIES", "ERROR", "Run doctor from a complete Bridge X distribution with requirements.txt.")
    if settings is None:
        add("CONFIGURATION", "ERROR", "Check BRIDGEX settings: provider, numeric limits, HTTPS URL and a nonempty local key. Values are hidden.")
        return {"version": __version__, "python": ".".join(map(str, sys.version_info[:3])), "checks": checks, "events": events}
    add("LOCAL_AUTH", "WARNING" if settings.local_api_key == "molab-local" else "PASS",
        "Set a unique BRIDGEX_LOCAL_KEY for normal use; retain client tool permissions." if settings.local_api_key == "molab-local" else "A nondefault local key is configured; its value is hidden.")
    if settings.provider == "molab":
        from .errors import BridgeError
        try:
            from .molab_provider import read_molab_config
            cfg = read_molab_config(settings.molab_config_path)
            placeholder = any("YOUR_" in value for value in (cfg.chat_url, cfg.session_id, cfg.server_token))
            add("MOLAB_CONFIG", "ERROR" if placeholder else "PASS", "Replace template values locally." if placeholder else "Runtime URL and configuration syntax are valid; remote availability is untested.")
        except BridgeError as exc:
            add(exc.code, "ERROR", "Create or correct the local Molab configuration, then rerun doctor. Private values are hidden.")
        except ImportError:
            add("MOLAB_CONFIG", "ERROR", "Install runtime dependencies before checking Molab configuration; no provider was contacted.")
        add("PROVIDER_MODE", "PASS" if settings.molab_tool_mode == "native" else "WARNING", "Use native mode for ZCode. Runtime mode is not changed or contacted by doctor.")
    else:
        add("PROVIDER_MODE", "PASS", "Offline simulator selected." if settings.provider == "fake" else "HTTPS provider configuration is valid; native capability is not certified.")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", port))
        add("LOCAL_PORT", "PASS", "Selected local port is free at this instant; startup can still race another process.")
    except OSError:
        add("LOCAL_PORT", "WARNING", "Port is busy or unavailable. If your gateway is already running this is expected; otherwise choose --port. No server was stopped.")
    path = Path(settings.journal_path)
    if settings.journal_path == ":memory:":
        add("JOURNAL", "WARNING", "Use a persistent BRIDGEX_JOURNAL_PATH to retain recovery state after restart.")
    elif not path.exists():
        parent = path.resolve().parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        add("JOURNAL", "PASS" if parent.is_dir() and os.access(parent, os.W_OK) else "ERROR", "Journal does not exist. Startup creates its configured directory; doctor creates nothing.")
    else:
        try:
            db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
            try:
                ok = db.execute("PRAGMA quick_check").fetchone() == ("ok",)
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                add("JOURNAL", "PASS" if ok and "operations" in tables else "ERROR", "Existing SQLite integrity and operation ledger checked read-only; no migration was run.")
                if "operations" in tables:
                    pending = db.execute("SELECT count(*) FROM operations WHERE state IN ('DISPATCHED','EXECUTION_UNKNOWN') OR (state='ACKNOWLEDGED' AND (result_kind='unknown' OR result_kind IS NULL))").fetchone()[0]
                    add("PENDING_OPERATIONS", "WARNING" if pending else "PASS", "Unresolved execution exists. Inspect actual client state and supply real receipts; never blindly rerun a mutation." if pending else "No unresolved dispatch or unknown receipt in the ledger.")
                events = report_events(db)
            finally:
                db.close()
        except (OSError, sqlite3.Error):
            add("JOURNAL", "ERROR", "Cannot inspect SQLite safely. Check permissions or lock state; preserve the database and its recovery files.")
    if network:
        # Explicitly local, no authentication headers, redirects or proxy use.
        add("NETWORK_TARGET", "PASS", f"Explicit probe: GET http://127.0.0.1:{port}/health only; no upstream request.")
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                connection.request("GET", "/health")
                response = connection.getresponse()
                value = json.loads(response.read(4096))
                ok = response.status == 200 and isinstance(value, dict) and value.get("status") == "ok" and value.get("version") == __version__
                add("LOCAL_HEALTH", "PASS" if ok else "WARNING", "Local health response checked without printing its contents. Verify the running gateway version.")
            finally:
                connection.close()
        except (OSError, ValueError, http.client.HTTPException):
            add("LOCAL_HEALTH", "WARNING", "Local health probe failed. Start your gateway on the selected port, then retry.")
    return {"version": __version__, "python": ".".join(map(str, sys.version_info[:3])), "checks": checks, "events": events}


def run(port=8787, network=False, report=None):
    from .config import Settings
    try:
        settings = Settings.from_env()
    except ValueError:
        settings = None
    result = inspect(settings, port, network)
    print("Bridge X " + __version__ + " doctor - local checks; private values hidden")
    for check in result["checks"]:
        print(f"{check['status']} {check['code']}: {check['recommendation']}")
    if report:
        try:
            # Do not overwrite an existing operator artifact or follow symlinks.
            with Path(report).open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2)
            print("PASS REPORT: Sanitized Issue report created; review it before sharing.")
        except (OSError, ValueError):
            print("ERROR REPORT: Cannot create report; choose a new writable file name.")
            return 2
    return 2 if any(c["status"] == "ERROR" for c in result["checks"]) else 0
