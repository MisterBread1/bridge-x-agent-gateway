"""A bounded, single-thread journal actor; whole transactions stay ordered."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
from .errors import BridgeError
from .observability import log_event


def storage_error(error):
    busy = isinstance(error, sqlite3.OperationalError) and any(word in str(error).lower() for word in ("locked", "busy"))
    return BridgeError("JOURNAL_BUSY" if busy else "JOURNAL_UNAVAILABLE",
                       "Local journal is busy; preserve state and retry later" if busy else "Local journal is unavailable; inspect permissions, free space and backup before retrying", 503, busy)


class JournalWorker:
    def __init__(self, journal, capacity=64):
        self.journal = journal
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bridge-journal")
        self.capacity = threading.BoundedSemaphore(capacity)
        self.pending_rate = []
        self.closed = False

    def submit(self, method, *args, **kwargs):
        if self.closed or not self.capacity.acquire(blocking=False):
            raise BridgeError("JOURNAL_BUSY", "Local journal queue is full; retry later without repeating uncertain tools", 503, True)
        def run():
            try:
                function = getattr(self.journal, method) if isinstance(method, str) else method
                return function(*args, **kwargs)
            except sqlite3.Error as error:
                raise storage_error(error) from None
        try:
            future = self.executor.submit(run)
        except BaseException:
            self.capacity.release()
            raise
        future.add_done_callback(lambda _: self.capacity.release())
        return future

    async def call(self, method, *args, **kwargs):
        return await asyncio.wrap_future(self.submit(method, *args, **kwargs))

    async def event(self, request_id, phase, error_code=None, **fields):
        # Reporting failure cannot mask a storage error or undo a dispatch.
        try:
            await self.call("diagnostic", request_id, phase, error_code, **fields)
        except BridgeError:
            log_event(request_id, phase, error_code, **fields)

    def load_provider_control(self, key):
        # Binding is startup-only, before the server begins accepting requests.
        return self.executor.submit(self.journal.load_provider_control, key).result()

    def save_provider_control(self, *args):
        self.pending_rate.append(self.submit("save_provider_control", *args))

    async def flush(self):
        pending, self.pending_rate = self.pending_rate, []
        for future in pending:
            await asyncio.wrap_future(future)

    async def close(self):
        try:
            await self.flush()
        finally:
            await self.call("close")
            self.closed = True
            self.executor.shutdown(wait=False)
