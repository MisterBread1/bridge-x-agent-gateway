"""Allowlisted metadata only: suitable for ordinary logs and Issue reports."""
import hashlib
import json
import logging
import re

OUTCOMES = {"unknown", "exit_zero", "exit_nonzero", "reported_success", "reported_failure", "cancelled", "timed_out"}
FINISHES = {"stop", "tool_calls", "length", "content_filter", "error", "failed"}
STATES = {"awaiting_tool_result", "awaiting_agent_decision", "model_stopped_unverified", "execution_unknown", "recovery_required", "client_cancelled"}
EVENTS = {"request_received", "provider_generation_started", "native_tool_proposed", "tool_dispatched",
          "tool_receipt_received", "tool_outcome_classified", "history_compacted", "provider_finish_received",
          "completion_delivered", "recovery_required", "upstream_failure", "client_cancelled"}
EVENTS |= {"input_rejected", "failed", "rate_limit_retry_wait", "native_batch_serialized",
           "tool_history_recovered", "tool_receipt_unmatched", "context_recovery_before_output"}
ERROR_CODES = {"EXECUTION_UNKNOWN", "RECEIPT_UNVERIFIED", "UPSTREAM_HISTORY_ECHO", "UPSTREAM_DEADLINE",
               "MOLAB_CONFIG_MISSING", "MOLAB_CONFIG_INVALID", "MOLAB_CONFIG_PLACEHOLDER",
               "UPSTREAM_RATE_LIMIT", "UPSTREAM_QUOTA_EXHAUSTED", "UPSTREAM_CONTEXT_LIMIT", "UPSTREAM_OUTPUT_LIMIT",
               "UPSTREAM_CONTENT_FILTER", "UPSTREAM_INCOMPLETE", "UPSTREAM_UNRECOGNIZED_FINISH", "UPSTREAM_FINISH_ERROR",
               "UPSTREAM_AFTER_FINISH", "UPSTREAM_DUPLICATE_FINISH", "UPSTREAM_MISSING_TOOL_CALLS", "UPSTREAM_ABORTED",
               "UPSTREAM_EVENT_ERROR", "UPSTREAM_INVALID_SSE_JSON", "UPSTREAM_INVALID_TEXT_DELTA", "UPSTREAM_SSE_UNKNOWN",
               "UPSTREAM_SERVER_ERROR", "UPSTREAM_ACCESS_DENIED", "INTERNAL_ERROR", "INVALID_REQUEST", "TOOL_REQUIRED",
               "INVALID_NATIVE_TOOL_DELTA", "TOOL_ARGUMENTS_TOO_LARGE", "OUTPUT_TOO_LARGE", "CONTEXT_BUDGET_EXCEEDED",
               "MOLAB_RUNTIME_GONE", "MOLAB_ACCESS_DENIED", "MOLAB_HTTP_ERROR", "MOLAB_TRANSPORT_ERROR",
               "MOLAB_RATE_LIMIT", "MOLAB_NATIVE_MODE_REQUIRED", "MOLAB_NATIVE_MODE_UNKNOWN", "MOLAB_NATIVE_TOOL_EXPECTED",
               "MOLAB_INCOMPLETE_STREAM", "MOLAB_COOLDOWN_ACTIVE", "MOLAB_QUEUE_TIMEOUT", "TOOL_CALL_ID_CONFLICT",
               "CROSS_CONVERSATION_RECEIPT", "TOOL_RECEIPT_MISSING_ID", "TOOL_RECEIPT_CONFLICT",
               "TOOL_SCHEMA_MISMATCH", "JOURNAL_BUSY", "JOURNAL_UNAVAILABLE", "JOURNAL_NEWER_SCHEMA"}


def tool_type(name):
    return {"read": "read", "edit": "edit", "write": "write", "applypatch": "edit",
            "bash": "bash", "python": "python", "glob": "search", "grep": "search"}.get(str(name).lower(), "other")


def safe_fields(fields):
    allowed = {}
    for key, values in (("tool_type", {"read", "edit", "write", "bash", "python", "search", "other"}),
                        ("outcome", OUTCOMES), ("finish_reason", FINISHES), ("agent_state", STATES)):
        value = fields.get(key)
        if isinstance(value, str) and value in values:
            allowed[key] = value
    for key in ("pending_operations", "compacted_exchanges", "compacted_outputs"):
        value = fields.get(key)
        if type(value) is int and 0 <= value <= 2_000_000_000:
            allowed[key] = value
    return allowed


def safe_code(value):
    return value if isinstance(value, str) and value in ERROR_CODES else ("OTHER_ERROR" if value is not None else None)


def safe_request(value):
    # Old databases can contain operator/client-controlled correlation IDs.
    return "req_" + hashlib.sha256(str(value).encode()).hexdigest()[:16]


def log_event(request_id, event, error_code=None, **fields):
    if event not in EVENTS:
        return
    logging.getLogger("bridge_x.events").info(json.dumps({"request_id": safe_request(request_id),
        "event": event, "error_code": safe_code(error_code), **safe_fields(fields)}, sort_keys=True))


def configure_logging():
    logger = logging.getLogger("bridge_x.events")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)


def report_events(db, limit=100):
    """Read a legacy or upgraded database without returning arbitrary cell text."""
    columns = {r[1] for r in db.execute("PRAGMA table_info(diagnostics)")}
    if not {"request_id", "phase", "error_code", "created_at"} <= columns:
        return []
    extra = [key for key in ("tool_type", "outcome", "finish_reason", "agent_state", "pending_operations",
                             "compacted_exchanges", "compacted_outputs") if key in columns]
    rows = db.execute("SELECT request_id,phase,error_code,created_at" +
                      ("," + ",".join(extra) if extra else "") + " FROM diagnostics ORDER BY seq DESC LIMIT ?", (limit,))
    output = []
    for row in rows:
        if row[1] not in EVENTS:
            continue
        at = row[3] if isinstance(row[3], str) and re.fullmatch(r"[0-9T: .+Z-]{1,40}", row[3]) else None
        output.append({"request_id": safe_request(row[0]), "event": row[1], "error_code": safe_code(row[2]),
                       "at": at, **safe_fields(dict(zip(extra, row[4:])))})
    return output
