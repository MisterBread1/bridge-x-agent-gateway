"""Classify explicit client results without inferring success from stdout."""
from .json_utils import loads


def classify_result(message: dict) -> str:
    value = message.get("content")
    try:
        value = loads(value) if isinstance(value, str) else value
    except (ValueError, RecursionError):
        return "unknown"
    if not isinstance(value, dict):
        return "unknown"
    if value.get("cancelled") is True:
        return "cancelled"
    if value.get("timed_out") is True:
        return "timed_out"
    if value.get("success") is False:
        return "reported_failure"
    if type(value.get("exit_code")) is int:
        return "exit_zero" if value["exit_code"] == 0 else "exit_nonzero"
    if str(message.get("name", "")).lower() in {"bash", "terminal", "shell", "exec"}:
        return "unknown"  # no inferred shell exit status, even with generic success prose
    if value.get("success") is True:
        return "reported_success"
    return "unknown"
