"""Pacing, foreground priority and persistent recovery from explicit rate caps."""
from contextlib import asynccontextmanager
from email.utils import parsedate_to_datetime
import asyncio
import math
import time
from .errors import BridgeError


def retry_after_seconds(value, *, now=None):
    """HTTP Retry-After is either delay-seconds or an HTTP date."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and value >= 0 else None
    if not isinstance(value, str):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except ValueError:
        pass
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return max(0.0, date.timestamp() - (time.time() if now is None else now))
    except (ValueError, TypeError, OverflowError):
        return None


def event_retry_after(value):
    """Read only explicit numeric retry fields, never guess from prose."""
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if not isinstance(item, dict) or depth > 4:
            continue
        for key in ("retry_after", "retry_after_seconds", "retryAfter", "retryAfterSeconds", "retry-after"):
            if key in item:
                parsed = retry_after_seconds(item[key])
                if parsed is not None:
                    return parsed
        if "retryAfterMs" in item:
            parsed = retry_after_seconds(item["retryAfterMs"])
            if parsed is not None:
                return parsed / 1000
        pending.extend((item[k], depth + 1) for k in ("error", "cause", "data", "metadata", "details") if k in item)
    return None


def is_background(scope):
    return scope.split(":", 1)[0] in {"project_memory_extract", "project_memory_dream", "session_title", "goal_summary_title"}


class RateController:
    def __init__(self, settings):
        self.enabled = settings.molab_rate_control
        self.base_interval = settings.molab_request_interval_s
        self.interval = self.base_interval
        self.background_interval = settings.molab_background_interval_s
        self.background_idle = settings.molab_background_idle_s
        self.base_cooldown = settings.molab_cooldown_s
        self.max_wait = settings.molab_max_queue_wait_s
        self.recovery_window = settings.molab_rate_recovery_s
        self.turn_budget = settings.timeout_s
        self.retry_limit = settings.molab_rate_retries if settings.molab_tool_mode == "native" and settings.verify_molab_native_mode else 0
        self.condition = asyncio.Condition()
        self.busy = False
        self.foreground_waiters = 0
        self.background_waiters = 0
        self.last_start = 0.0
        self.last_background_start = 0.0
        self.last_foreground_activity = 0.0
        self.blocked_until = 0.0
        self.failures = 0
        self.last_limit = 0.0
        self.store = None
        self.key = None

    def bind(self, key, store=None):
        if self.key == key:
            return
        self.key, self.store = key, store
        state = store.load_provider_control(key) if store is not None and self.enabled else None
        if state:
            self.blocked_until = state["blocked_until"]
            self.last_start = state["last_start"]
            self.failures = state["failures"]
            self.interval = max(self.base_interval, state["interval_s"])
            self.last_limit = state["last_limit"]
            if not self.last_limit and self.interval > self.base_interval and self.blocked_until:
                self.last_limit = max(0, min(time.time(), self.blocked_until - self.base_cooldown))

    def _save(self):
        if self.enabled and self.store is not None and self.key:
            self.store.save_provider_control(self.key, self.blocked_until, self.last_start, self.failures, self.interval, self.last_limit)

    async def flush(self):
        if self.store is not None and hasattr(self.store, "flush"):
            await self.store.flush()

    def note_limit(self, hint=None):
        now = time.time()
        if now - self.last_limit >= self.recovery_window:
            self.failures = 0
        self.last_limit = now
        self.failures = min(self.failures + 1, 8)
        advisory = min(900.0, self.base_cooldown * (2 ** (self.failures - 1)))
        delay = max(advisory, hint or 0.0)
        if self.enabled:
            self.blocked_until = max(self.blocked_until, now + delay)
            self.interval = max(self.base_interval, min(60.0, self.base_interval * (2 ** min(self.failures, 2))))
            self._save()
        return delay

    def note_success(self):
        if self.enabled:
            if time.time() - self.last_limit >= self.recovery_window:
                self.failures = 0
                self.interval = max(self.base_interval, self.interval * 0.9)
            self._save()

    def status(self):
        return {"enabled": self.enabled, "request_interval_seconds": round(self.interval, 3),
                "cooldown_remaining_seconds": max(0, math.ceil(self.blocked_until - time.time())),
                "foreground_waiting": self.foreground_waiters, "background_waiting": self.background_waiters,
                "request_in_flight": self.busy, "automatic_upstream_retry": self.retry_limit > 0,
                "pre_output_rate_retry_limit": self.retry_limit, "unknown_outcome_retry": False,
                "recovery_remaining_seconds": max(0, math.ceil(self.last_limit + self.recovery_window - time.time()))}

    def preflight(self):
        remaining = self.blocked_until - time.time()
        wait_budget = self.turn_budget - min(10.0, self.turn_budget * 0.1) if self.retry_limit else self.max_wait
        if self.enabled and remaining > wait_budget:
            raise BridgeError("MOLAB_COOLDOWN_ACTIVE", "Local cooldown after a previous Molab limit is active; no new upstream request was sent", 429, True, remaining)

    @asynccontextmanager
    async def slot(self, scope, *, max_wait_s=None):
        if not self.enabled:
            yield
            return
        background = is_background(scope)
        deadline = time.monotonic() + (self.max_wait if max_wait_s is None else max_wait_s)
        admitted = False
        async with self.condition:
            if background:
                self.background_waiters += 1
            else:
                self.foreground_waiters += 1
            try:
                while True:
                    now = time.time()
                    allowed_at = max(self.blocked_until, self.last_start + self.interval)
                    if background:
                        allowed_at = max(allowed_at, self.last_background_start + self.background_interval,
                                         self.last_foreground_activity + self.background_idle)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        retry = max(1.0, allowed_at - now)
                        raise BridgeError("MOLAB_QUEUE_TIMEOUT", "Local pacing queue reached its wait limit; this request was not sent to Molab", 429, True, retry)
                    eligible = not self.busy and (not background or self.foreground_waiters == 0)
                    if eligible and allowed_at <= now:
                        self.busy = admitted = True
                        self.last_start = now
                        if background:
                            self.last_background_start = now
                        else:
                            self.last_foreground_activity = now
                        self._save()
                        break
                    wait = min(remaining, max(0.01, allowed_at - now)) if eligible else remaining
                    try:
                        await asyncio.wait_for(self.condition.wait(), timeout=wait)
                    except asyncio.TimeoutError:
                        pass
            except BaseException:
                if admitted:
                    self.busy = False
                raise
            finally:
                if background:
                    self.background_waiters -= 1
                else:
                    self.foreground_waiters -= 1
                self.condition.notify_all()
        try:
            await self.flush()
            yield
        finally:
            if admitted:
                async with self.condition:
                    self.busy = False
                    if not background:
                        self.last_foreground_activity = time.time()
                    self.condition.notify_all()
