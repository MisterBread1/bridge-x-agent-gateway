"""Bounded native-console telemetry. Never stores bodies, headers or URLs."""
from collections import OrderedDict, deque
from contextvars import ContextVar
from datetime import datetime, timezone
import threading
import time
from .observability import safe_code

PHASES = {"preparing", "queue", "runtime_check", "upstream", "receiving", "validating", "retry_wait", "context_retry", "done", "failed", "cancelled"}
ROUTES = {"/v1/chat/completions", "/v1/models", "/health", "/ready", "/diagnostics", "/diagnostics/report", "/v1/capabilities"}


class RequestMonitor:
    def __init__(self, capacity=500):
        self.capacity = capacity
        self.lock = threading.RLock()
        self.rows = OrderedDict()
        self.events = deque(maxlen=1000)
        self.current = ContextVar("bridge_console_request", default=None)
        self.sequence = 0
        self.clock = time.monotonic
        self.writer = None

    def begin(self, method, path):
        with self.lock:
            self.sequence += 1
            now = self.clock()
            row = {"id": self.sequence, "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                   "method": method if method in {"GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"} else "OTHER",
                   "path": path if path in ROUTES else "/other", "http": None, "phase": "preparing",
                   "error_code": None, "queue_ms": 0, "upstream_ms": 0, "total_ms": 0,
                   "first_output_ms": None, "retries": 0, "active": True, "scope": "foreground",
                   "request_bytes": 0, "response_bytes": 0,
                   "_start": now, "_phase_at": now}
            self.rows[row["id"]] = row
            while len(self.rows) > self.capacity:
                self.rows.popitem(last=False)
            return self.current.set(row["id"])

    def _accrue(self, row, now):
        elapsed = max(0, int((now - row["_phase_at"]) * 1000))
        if row["phase"] in {"queue", "retry_wait"}: row["queue_ms"] += elapsed
        if row["phase"] in {"runtime_check", "upstream", "receiving"}: row["upstream_ms"] += elapsed
        row["_phase_at"] = now

    def stage(self, phase, error_code=None):
        if phase not in PHASES: return
        with self.lock:
            row = self.rows.get(self.current.get())
            if row is None or not row["active"]: return
            now = self.clock(); self._accrue(row, now)
            row["phase"] = phase
            code = safe_code(error_code)
            if code: row["error_code"] = code
            if phase in {"retry_wait", "context_retry"}: row["retries"] += 1
            self.events.append({"at": datetime.now(timezone.utc).strftime("%H:%M:%S"), "request": row["id"], "phase": phase, "error_code": code})

    def first_output(self):
        with self.lock:
            row = self.rows.get(self.current.get())
            if row and row["first_output_ms"] is None:
                row["first_output_ms"] = max(0, int((self.clock() - row["_start"]) * 1000))
                return True
            return False

    def branch(self, background):
        with self.lock:
            row = self.rows.get(self.current.get())
            if row: row["scope"] = "background" if background else "foreground"

    def status(self, status):
        with self.lock:
            row = self.rows.get(self.current.get())
            if row and type(status) is int and 100 <= status <= 599:
                row["http"] = status
                if status >= 400 and row["error_code"] is None: row["error_code"] = "HTTP_" + str(status)

    def transferred(self, direction, size):
        if direction not in {"request_bytes", "response_bytes"} or type(size) is not int or size < 0: return
        with self.lock:
            row = self.rows.get(self.current.get())
            if row is not None: row[direction] += size

    def finish(self, token, cancelled=False):
        with self.lock:
            row = self.rows.get(self.current.get())
            if row:
                now = self.clock(); self._accrue(row, now)
                row["total_ms"] = max(0, int((now - row["_start"]) * 1000)); row["active"] = False
                # An earlier retry error is historical if the final response succeeded.
                row["phase"] = "cancelled" if cancelled else "failed" if row["phase"] == "failed" or (row["http"] or 0) >= 400 else "done"
                if row["phase"] == "done": row["error_code"] = None
                if self.writer is not None:
                    self.writer.submit({key: value for key, value in row.items() if not key.startswith("_")})
            self.current.reset(token)

    def snapshot(self):
        with self.lock:
            now = self.clock(); rows = []
            for original in reversed(self.rows.values()):
                row = dict(original)
                if row["active"]:
                    self._accrue(row, now)
                    row["total_ms"] = max(0, int((now - row["_start"]) * 1000))
                rows.append({key: value for key, value in row.items() if not key.startswith("_")})
            return {"requests": rows, "events": list(self.events)}


class MonitorMiddleware:
    def __init__(self, app, monitor):
        self.app, self.monitor = app, monitor

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token = self.monitor.begin(scope.get("method"), scope.get("path"))
        cancelled = False
        async def observed_send(message):
            if message["type"] == "http.response.start": self.monitor.status(message["status"])
            if message["type"] == "http.response.body": self.monitor.transferred("response_bytes", len(message.get("body", b"")))
            await send(message)
        async def observed_receive():
            message = await receive()
            if message["type"] == "http.request": self.monitor.transferred("request_bytes", len(message.get("body", b"")))
            return message
        try:
            await self.app(scope, observed_receive, observed_send)
        except BaseException as error:
            import asyncio
            cancelled = isinstance(error, asyncio.CancelledError)
            self.monitor.stage("cancelled" if cancelled else "failed", "INTERNAL_ERROR" if not cancelled else None)
            raise
        finally:
            self.monitor.finish(token, cancelled)
