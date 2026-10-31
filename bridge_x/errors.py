"""Typed failures with sanitized output: no upstream bodies or credentials."""
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import time


@dataclass
class BridgeError(Exception):
    code: str
    message: str
    status: int = 502
    retryable: bool = False
    retry_after_s: float | None = None

    def public(self):
        kind = ("rate_limit_error" if self.code in ("UPSTREAM_RATE_LIMIT", "MOLAB_RATE_LIMIT", "MOLAB_COOLDOWN_ACTIVE", "MOLAB_QUEUE_TIMEOUT") else
                "insufficient_quota" if self.code == "UPSTREAM_QUOTA_EXHAUSTED" else "bridge_error")
        error = {"message": self.message, "type": kind, "code": self.code, "retryable": self.retryable}
        if self.retry_after_s is not None:
            delay = max(1, math.ceil(self.retry_after_s))
            error["retry_after_seconds"] = delay
            if delay < 366 * 86400:
                error["retry_at"] = datetime.fromtimestamp(time.time() + delay, timezone.utc).isoformat()
        return {"error": error}

    def headers(self):
        return {"Retry-After": str(max(1, math.ceil(self.retry_after_s)))} if self.retry_after_s is not None else {}


class UpstreamError(BridgeError):
    pass
