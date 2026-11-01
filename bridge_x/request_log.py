"""Bounded asynchronous request metadata log for the native console."""
import json
from logging.handlers import RotatingFileHandler
from pathlib import Path
import queue
import threading


class RequestLog:
    """One owner, three 1 MiB backups, no blocking disk IO on the HTTP loop."""
    def __init__(self, path, max_bytes=1024 * 1024, capacity=1000):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.queue = queue.Queue(maxsize=capacity)
        self.lock = threading.Lock()
        self.closed = False
        self.failed = False
        self.dropped = 0
        self.thread = threading.Thread(target=self._write, name="bridge-request-log", daemon=True)
        self.thread.start()

    def submit(self, row):
        # Only RequestMonitor's sanitized snapshot crosses this private boundary.
        with self.lock:
            if self.closed or self.failed:
                self.dropped += 1
                return
            try: self.queue.put_nowait(dict(row))
            except queue.Full: self.dropped += 1

    def _write(self):
        handler = None
        try:
            paths = [self.path, *(Path(str(self.path) + "." + str(index)) for index in range(1, 4))]
            if any(path.is_symlink() or (path.exists() and not path.is_file()) for path in paths):
                raise OSError("Not a regular request log")
            handler = RotatingFileHandler(self.path, maxBytes=self.max_bytes, backupCount=3, encoding="utf-8")
            while True:
                row = self.queue.get()
                if row is None: break
                payload = json.dumps({"schema": 1, **row}, ensure_ascii=True, allow_nan=False)
                # Write directly so failures are surfaced rather than printed to stderr by logging.
                if handler.stream.tell() + len(payload.encode("utf-8")) + 1 >= self.max_bytes:
                    handler.doRollover()
                handler.stream.write(payload + "\n")
                handler.flush()
        except (OSError, ValueError):
            with self.lock: self.failed = True
        finally:
            if handler is not None: handler.close()

    def status(self):
        with self.lock:
            return {"failed": self.failed, "dropped": self.dropped}

    def close(self):
        with self.lock:
            self.closed = True
        # Called by the owner worker after its HTTP server has stopped, never by Tk.
        while self.thread.is_alive():
            try:
                self.queue.put(None, timeout=.1)
                break
            except queue.Full: continue
        self.thread.join(timeout=5)
