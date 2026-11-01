"""Own one gateway worker for the native window; never stop another process."""
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
from dataclasses import replace
from .errors import BridgeError
from .monitoring import RequestMonitor


def desktop_settings(settings):
    """Reuse an existing 12.13 web-UI API key, without creating or asking for one."""
    if settings.provider != "molab" or "BRIDGEX_LOCAL_KEY" in os.environ or settings.local_api_key != "molab-local":
        return settings
    from .paths import data_dir
    path = data_dir() / "local.key"
    try:
        if path.is_symlink(): return settings
        value = path.read_text(encoding="ascii").strip()
        if 32 <= len(value) <= 256 and not any(char.isspace() for char in value):
            return replace(settings, local_api_key=value)
    except (OSError, UnicodeError): pass
    return settings


def save_connection(settings, values):
    from .molab_provider import validate_molab_config
    config = validate_molab_config(values)
    if any("YOUR_" in value for value in (config.chat_url, config.session_id, config.server_token)):
        raise BridgeError("MOLAB_CONFIG_PLACEHOLDER", "Replace example values", 400)
    target = Path(settings.molab_config_path)
    if target.is_symlink():
        raise BridgeError("MOLAB_CONFIG_INVALID", "Configuration must be a regular file", 400)
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as output:
            name = output.name; json.dump(values, output); output.flush(); os.fsync(output.fileno())
        os.replace(name, target); name = None
    finally:
        if name is not None: Path(name).unlink(missing_ok=True)


class GatewayHost:
    def __init__(self, settings, port=8787, provider=None):
        self.settings, self.port, self.provider = desktop_settings(settings), port, provider
        self.monitor = RequestMonitor()
        self.lock = threading.RLock()
        self.state, self.error = "stopped", None
        self.thread = self.server = self.app = None
        self.request_log = None
        self.stop_requested = threading.Event()

    def start(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive(): return False
            self.state, self.error = "starting", None
            self.server = self.app = None
            self.stop_requested.clear()
            self.request_log = None
            self.thread = threading.Thread(target=self._serve, name="bridge-proxy", daemon=True)
            self.thread.start()
            return True

    def _serve(self):
        listener = None
        try:
            import uvicorn
            from .gateway import create_app
            from .paths import InstanceLock
            from .request_log import RequestLog
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if os.name == "nt": listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                listener.bind(("127.0.0.1", self.port))
            except OSError:
                raise BridgeError("PORT_UNAVAILABLE", "Selected local port is already in use", 409) from None
            self.port = listener.getsockname()[1]
            with InstanceLock(self.settings.journal_path):
                try:
                    if self.settings.journal_path != ":memory:":
                        path = Path(self.settings.journal_path).with_suffix(".requests.jsonl")
                        path.parent.mkdir(parents=True, exist_ok=True)
                        self.request_log = self.monitor.writer = RequestLog(path)
                    app = create_app(self.settings, provider=self.provider, monitor=self.monitor)
                    config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_config=None, access_log=False, timeout_graceful_shutdown=5)
                    server = uvicorn.Server(config)
                    with self.lock: self.app, self.server = app, server
                    if self.stop_requested.is_set(): server.should_exit = True
                    server.run(sockets=[listener])
                finally:
                    if self.request_log is not None: self.request_log.close()
                    self.monitor.writer = None
            with self.lock:
                self.state = "stopped" if server.started or self.stop_requested.is_set() else "error"
                if self.state == "error": self.error = "INTERNAL_ERROR"
        except BridgeError as error:
            with self.lock: self.state, self.error = "error", error.code
        except OSError:
            with self.lock: self.state, self.error = "error", "LOCAL_STORAGE_UNAVAILABLE"
        except (Exception, SystemExit):
            with self.lock: self.state, self.error = "error", "INTERNAL_ERROR"
        finally:
            if listener is not None: listener.close()

    def stop(self):
        with self.lock:
            self.stop_requested.set()
            if self.server is not None and self.thread is not None and self.thread.is_alive():
                self.state = "stopping"; self.server.should_exit = True

    def snapshot(self):
        with self.lock:
            state = self.state
            if state == "starting" and self.server is not None and self.server.started: state = self.state = "running"
            provider = self.app.state.provider if self.app is not None else None
            result = {"state": state, "error": self.error, "port": self.port,
                      "logging": self.request_log.status() if self.request_log is not None else {"failed": False, "dropped": 0},
                      "provider": self.settings.provider,
                      "model": "molab-glm" if self.settings.provider == "molab" else "bridge-x-fake" if self.settings.provider == "fake" else self.settings.generic_model,
                      "rate": provider.rate_status() if provider is not None and hasattr(provider, "rate_status") else {},
                      "connection": provider.connection_status() if provider is not None and hasattr(provider, "connection_status") else {"verified": False}}
        return {**result, **self.monitor.snapshot()}

    def wait(self, timeout=10):
        thread = self.thread
        if thread is not None: thread.join(timeout)
        return thread is None or not thread.is_alive()
