"""Local metadata-only durable command ledger. Not a local command executor."""
from pathlib import Path
import sqlite3
import threading
import re
import hashlib
import json
from .errors import BridgeError
from .tool_models import OperationState
from .observability import log_event, safe_fields, report_events, tool_type
from .json_utils import loads


def argument_fingerprint(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


_RESULT_STATES = {
    "exit_zero": OperationState.EXECUTED, "reported_success": OperationState.EXECUTED,
    "exit_nonzero": OperationState.FAILED, "reported_failure": OperationState.FAILED,
    "cancelled": OperationState.CANCELLED, "timed_out": OperationState.TIMED_OUT,
}

_TRANSITIONS = {
    "PROPOSED": {"VALIDATED", "REJECTED", "CANCELLED"},
    "VALIDATED": {"DISPATCHED", "REJECTED", "CANCELLED"},
    "DISPATCHED": {"ACKNOWLEDGED", "EXECUTION_UNKNOWN", "CANCELLED", "TIMED_OUT"},
    "EXECUTION_UNKNOWN": {"ACKNOWLEDGED", "CANCELLED", "TIMED_OUT"},
    "ACKNOWLEDGED": {"EXECUTED", "FAILED", "CANCELLED", "TIMED_OUT"},
    "EXECUTED": {"VERIFIED"},
}


class Journal:
    def __init__(self, filename: str):
        self.db = sqlite3.connect(filename, check_same_thread=False, timeout=10, isolation_level="DEFERRED")
        self.lock = threading.RLock()
        with self.lock:
            self.db.execute("PRAGMA busy_timeout=10000")
            if filename != ":memory:":
                self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS intents(
                  call_id TEXT PRIMARY KEY, conversation_id TEXT, name TEXT NOT NULL,
                  schema_hash TEXT NOT NULL, status TEXT NOT NULL,
                  result_kind TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS upstream_failures(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT,
                  request_id TEXT NOT NULL, error_code TEXT NOT NULL,
                  upstream_event TEXT NOT NULL,
                  upstream_status INTEGER, sse_event_count INTEGER,
                  sse_partial_text_chars INTEGER, sse_body_bytes INTEGER,
                  elapsed_ms INTEGER, input_message_count INTEGER,
                  input_tool_count INTEGER, upstream_request_bytes INTEGER,
                  advisory_action_chars INTEGER,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS diagnostics(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT,
                  request_id TEXT NOT NULL, phase TEXT NOT NULL, error_code TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS operations(
                  call_id TEXT PRIMARY KEY, conversation_id TEXT, name TEXT NOT NULL,
                  schema_version TEXT NOT NULL, state TEXT NOT NULL, source TEXT NOT NULL,
                  result_kind TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS operation_events(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL,
                  state TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS dispatch_requests(
                  request_key TEXT PRIMARY KEY, conversation_id TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE INDEX IF NOT EXISTS operations_conversation ON operations(conversation_id, state);
                CREATE TABLE IF NOT EXISTS client_requests(
                  request_id TEXT PRIMARY KEY, client_request_id TEXT,
                  conversation_id TEXT, execution_scope TEXT NOT NULL,
                  query_source TEXT NOT NULL, tool_count INTEGER NOT NULL,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            """)
            # Upgrading an existing V12.9 SQLite journal must not require
            # deleting the user's state or restarting with a fresh database.
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(upstream_failures)")}
            if "advisory_action_chars" not in columns:
                self.db.execute("ALTER TABLE upstream_failures ADD COLUMN advisory_action_chars INTEGER")
            operation_columns = {row[1] for row in self.db.execute("PRAGMA table_info(operations)")}
            if "execution_scope" not in operation_columns:
                self.db.execute("ALTER TABLE operations ADD COLUMN execution_scope TEXT NOT NULL DEFAULT 'main_turn'")
            if "argument_hash" not in operation_columns:
                self.db.execute("ALTER TABLE operations ADD COLUMN argument_hash TEXT")
            diagnostic_columns = {row[1] for row in self.db.execute("PRAGMA table_info(diagnostics)")}
            for name, kind in (("tool_type", "TEXT"), ("outcome", "TEXT"), ("finish_reason", "TEXT"),
                               ("agent_state", "TEXT"), ("pending_operations", "INTEGER"),
                               ("compacted_exchanges", "INTEGER"), ("compacted_outputs", "INTEGER")):
                if name not in diagnostic_columns:
                    self.db.execute(f"ALTER TABLE diagnostics ADD COLUMN {name} {kind}")
            with self.db:
                self.db.execute("""INSERT OR IGNORE INTO operations
                    (call_id,conversation_id,name,schema_version,state,source,result_kind,created_at)
                    SELECT call_id,conversation_id,name,schema_hash,
                    CASE WHEN status='VERIFIED' THEN 'VERIFIED'
                         WHEN status='FAILED' THEN 'FAILED'
                         WHEN status='OFFERED_UNCONFIRMED' THEN 'DISPATCHED'
                         WHEN status='UNVERIFIED_CLIENT_RESULT' THEN 'EXECUTION_UNKNOWN'
                         WHEN result_kind IN ('exit_zero','reported_success') THEN 'EXECUTED'
                         WHEN result_kind IN ('exit_nonzero','reported_failure') THEN 'FAILED'
                         ELSE 'ACKNOWLEDGED' END,
                    'legacy_migration',result_kind,created_at FROM intents""")
                self.db.execute("PRAGMA user_version=4")

    def _transition(self, call_id, state):
        row = self.db.execute("SELECT state FROM operations WHERE call_id=?", (call_id,)).fetchone()
        if row is None:
            raise BridgeError("ORPHAN_TOOL_RESULT", "Operation does not exist", 409)
        if row[0] == state:
            return
        if state not in _TRANSITIONS.get(row[0], set()):
            raise BridgeError("INVALID_OPERATION_STATE", "Operation transition is not permitted", 409)
        self.db.execute("UPDATE operations SET state=?,updated_at=CURRENT_TIMESTAMP WHERE call_id=?", (state, call_id))
        self.db.execute("INSERT INTO operation_events(call_id,state) VALUES(?,?)", (call_id, state))

    def ensure_new_turn(self, request_key, conversation_id, tools_allowed=True, *, execution_scope="main_turn"):
        with self.lock:
            if request_key is not None and self.db.execute("SELECT 1 FROM dispatch_requests WHERE request_key=?", (request_key,)).fetchone():
                raise BridgeError("EXECUTION_UNKNOWN", "This request already dispatched tools; reconcile their results before retrying", 409)
            if tools_allowed and conversation_id is not None:
                pending = self.db.execute("SELECT 1 FROM operations WHERE conversation_id=? AND execution_scope=? AND state IN ('DISPATCHED','EXECUTION_UNKNOWN') AND source='gateway' LIMIT 1", (conversation_id, execution_scope)).fetchone()
                if pending:
                    raise BridgeError("EXECUTION_UNKNOWN", "Conversation has tools without execution receipts; provide their results before further actions", 409)

    def operation(self, call_id):
        with self.lock:
            columns = ("id", "conversation_id", "name", "schema_version", "status", "source", "result_kind", "created_at", "updated_at", "execution_scope")
            row = self.db.execute("SELECT call_id,conversation_id,name,schema_version,state,source,result_kind,created_at,updated_at,execution_scope FROM operations WHERE call_id=?", (call_id,)).fetchone()
            if row is None:
                return None
            result = dict(zip(columns, row))
            result["events"] = [r[0] for r in self.db.execute("SELECT state FROM operation_events WHERE call_id=? ORDER BY seq", (call_id,))]
            return result

    def verify(self, call_id, conversation_id, expected_sha256, observed_sha256):
        """Accept a client's explicit readback check, never infer it from text."""
        if (not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256)
                or not isinstance(observed_sha256, str) or expected_sha256.lower() != observed_sha256.lower()):
            raise BridgeError("VERIFICATION_FAILED", "Readback digests are invalid or differ", 409)
        with self.lock, self.db:
            operation = self.operation(call_id)
            if operation is None:
                raise BridgeError("ORPHAN_TOOL_RESULT", "Operation does not exist", 409)
            if operation["conversation_id"] != conversation_id:
                raise BridgeError("CROSS_CONVERSATION_RECEIPT", "Verification belongs to another conversation", 409)
            self._transition(call_id, "VERIFIED")
            return self.operation(call_id)

    def deliver(self, calls, conversation_id=None, request_key=None, *, execution_scope="main_turn"):
        with self.lock, self.db:
            # BEGIN IMMEDIATE serializes the check and write across processes.
            self.db.execute("BEGIN IMMEDIATE")
            self.guard_uncertain_replay(calls, conversation_id, execution_scope)
            if request_key is not None:
                self.ensure_new_turn(request_key, conversation_id, execution_scope=execution_scope)
                self.db.execute("INSERT INTO dispatch_requests(request_key,conversation_id) VALUES(?,?)", (request_key, conversation_id))
            for call in calls:
                if call.conversation_id is not None and call.conversation_id != conversation_id:
                    raise BridgeError("CROSS_CONVERSATION_RECEIPT", "Tool proposal belongs to another conversation", 409)
                self.db.execute("INSERT INTO intents(call_id,conversation_id,name,schema_hash,status) VALUES (?,?,?,?,?)",
                                (call.id, conversation_id, call.name, call.schema_hash, "OFFERED_UNCONFIRMED"))
                self.db.execute("INSERT INTO operations(call_id,conversation_id,name,schema_version,state,source,execution_scope) VALUES(?,?,?,?,?,?,?)",
                                (call.id, conversation_id, call.name, call.schema_hash, "PROPOSED", "gateway", execution_scope))
                self.db.execute("UPDATE operations SET argument_hash=? WHERE call_id=?", (argument_fingerprint(call.arguments), call.id))
                self.db.execute("INSERT INTO operation_events(call_id,state) VALUES(?,?)", (call.id, "PROPOSED"))
                self._transition(call.id, "VALIDATED")
                self._transition(call.id, "DISPATCHED")

    def guard_uncertain_replay(self, calls, conversation_id, execution_scope):
        # Read/search checks are client-owned too. Only block repeated mutations,
        # never schedule a verification tool or invent a new client request.
        for call in calls:
            if call.name.lower() in {"read", "glob", "grep", "list", "search"}:
                continue
            row = self.db.execute("""SELECT 1 FROM operations WHERE conversation_id IS ? AND execution_scope=? AND name=?
                AND (argument_hash=? OR argument_hash IS NULL)
                AND ((state='ACKNOWLEDGED' AND (result_kind='unknown' OR result_kind IS NULL))
                     OR state IN ('EXECUTION_UNKNOWN','TIMED_OUT','CANCELLED')) LIMIT 1""",
                (conversation_id, execution_scope, call.name, argument_fingerprint(call.arguments))).fetchone()
            if row:
                raise BridgeError("EXECUTION_UNKNOWN", "A matching mutation has an uncertain outcome; verify actual client state and supply a confirmed receipt before repeating it", 409)

    def continuity(self, conversation_id, execution_scope="main_turn"):
        with self.lock:
            rows = self.db.execute("SELECT state,result_kind FROM operations WHERE conversation_id IS ? AND execution_scope=?",
                                   (conversation_id, execution_scope)).fetchall()
        pending = sum(state in ("DISPATCHED", "EXECUTION_UNKNOWN") for state, _ in rows)
        unknown = sum(state == "EXECUTION_UNKNOWN" or (state == "ACKNOWLEDGED" and kind in (None, "unknown")) for state, kind in rows)
        return {"pending_operations": pending, "unknown_outcomes": unknown}

    def safe_report(self):
        with self.lock:
            return report_events(self.db)

    def record_client_request(self, request_id, client_request_id, conversation_id, execution_scope, query_source, tool_count):
        # Only correlation metadata; never headers, prompts or argument bodies.
        client_id = client_request_id if isinstance(client_request_id, str) and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,256}", client_request_id) else None
        source = query_source if isinstance(query_source, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", query_source) else "main_turn"
        with self.lock, self.db:
            self.db.execute("INSERT INTO client_requests(request_id,client_request_id,conversation_id,execution_scope,query_source,tool_count) VALUES(?,?,?,?,?,?)",
                            (request_id, client_id, conversation_id, execution_scope, source, tool_count))

    def _provider_control_table(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS provider_control(
            provider_key TEXT PRIMARY KEY, blocked_until REAL NOT NULL,
            last_start REAL NOT NULL, failures INTEGER NOT NULL, interval_s REAL NOT NULL,
            last_limit REAL NOT NULL DEFAULT 0)""")
        if "last_limit" not in {row[1] for row in self.db.execute("PRAGMA table_info(provider_control)")}:
            self.db.execute("ALTER TABLE provider_control ADD COLUMN last_limit REAL NOT NULL DEFAULT 0")

    def load_provider_control(self, key):
        with self.lock, self.db:
            self._provider_control_table()
            row = self.db.execute("SELECT blocked_until,last_start,failures,interval_s,last_limit FROM provider_control WHERE provider_key=?", (key,)).fetchone()
        return dict(zip(("blocked_until", "last_start", "failures", "interval_s", "last_limit"), row)) if row else None

    def save_provider_control(self, key, blocked_until, last_start, failures, interval_s, last_limit=0):
        with self.lock, self.db:
            self._provider_control_table()
            self.db.execute("INSERT OR REPLACE INTO provider_control(provider_key,blocked_until,last_start,failures,interval_s,last_limit) VALUES(?,?,?,?,?,?)",
                            (key, blocked_until, last_start, failures, interval_s, last_limit))

    def receive(self, call_id: str, conversation_id=None, result_kind="unknown"):
        with self.lock, self.db:
            row = self.db.execute("SELECT conversation_id,status FROM intents WHERE call_id=?", (call_id,)).fetchone()
            if row is None:
                raise BridgeError("ORPHAN_TOOL_RESULT", "Tool result references unknown tool call", 409)
            owner, status = row
            if conversation_id is not None and owner is not None and conversation_id != owner:
                raise BridgeError("CROSS_CONVERSATION_RECEIPT", "Result belongs to another conversation", 409)
            self.db.execute("UPDATE intents SET conversation_id=COALESCE(conversation_id, ?) WHERE call_id=?",
                            (conversation_id, call_id))
            self.db.execute("UPDATE operations SET conversation_id=COALESCE(conversation_id, ?) WHERE call_id=?", (conversation_id, call_id))
            if status in ("RESULT_RECEIVED", "VERIFIED", "FAILED", "UNVERIFIED_CLIENT_RESULT"):
                operation = self.operation(call_id)
                if (status == "RESULT_RECEIVED" and operation is not None and operation["status"] == "ACKNOWLEDGED"
                        and operation["result_kind"] == "unknown" and result_kind in _RESULT_STATES):
                    # A later genuine structured receipt may resolve an earlier
                    # text-only result. Existing confirmed outcomes are immutable.
                    self._transition(call_id, _RESULT_STATES[result_kind])
                    self.db.execute("UPDATE intents SET result_kind=? WHERE call_id=?", (result_kind, call_id))
                    self.db.execute("UPDATE operations SET result_kind=? WHERE call_id=?", (result_kind, call_id))
                    return True
                return False
            if status != "OFFERED_UNCONFIRMED":
                raise BridgeError("INVALID_RECEIPT_STATE", "Result cannot be accepted in current state", 409)
            self.db.execute("UPDATE intents SET status=?,result_kind=?,conversation_id=COALESCE(conversation_id, ?) WHERE call_id=?",
                            ("RESULT_RECEIVED", result_kind, conversation_id, call_id))
            if self.operation(call_id) is not None:
                self._transition(call_id, "ACKNOWLEDGED")
                state = _RESULT_STATES.get(result_kind)
                if state is not None:
                    self._transition(call_id, state)
                self.db.execute("UPDATE operations SET result_kind=? WHERE call_id=?", (result_kind, call_id))
            return True

    def restore_intent_from_history(self, call_id: str, name: str, conversation_id=None, argument_hash=None):
        """Rebuild metadata for a call visible in the *preceding assistant transcript*.

        The history proves only that the client presented a tool proposal, not
        that a file was written or a command ran. No executable code is run here.
        """
        if (not isinstance(call_id, str) or not call_id or len(call_id) > 256
                or not isinstance(name, str) or not name or len(name) > 256):
            return False
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT conversation_id,name,status FROM intents WHERE call_id=?", (call_id,)
            ).fetchone()
            if row:
                if argument_hash is not None:
                    self.db.execute("UPDATE operations SET argument_hash=COALESCE(argument_hash,?) WHERE call_id=?", (argument_hash, call_id))
                owner, known_name, status = row
                if owner is not None and conversation_id is not None and owner != conversation_id:
                    raise BridgeError("CROSS_CONVERSATION_RECEIPT", "Result belongs to another conversation", 409)
                if known_name not in (name, "(unmatched)"):
                    raise BridgeError("TOOL_CALL_ID_CONFLICT", "Conflicting tool call ID in conversation history", 409)
                self.db.execute("UPDATE intents SET conversation_id=COALESCE(conversation_id, ?) WHERE call_id=?",
                                (conversation_id, call_id))
                self.db.execute("UPDATE operations SET conversation_id=COALESCE(conversation_id, ?) WHERE call_id=?", (conversation_id, call_id))
                if status == "UNVERIFIED_CLIENT_RESULT":
                    self.db.execute(
                        "UPDATE intents SET name=?,schema_hash=?,status=?,conversation_id=COALESCE(conversation_id, ?) WHERE call_id=?",
                        (name, "recovered-from-client-history", "RESULT_RECEIVED", conversation_id, call_id),
                    )
                    operation = self.operation(call_id)
                    if operation is not None:
                        self.db.execute("UPDATE operations SET name=?,schema_version=?,source='client_history' WHERE call_id=?",
                                        (name, "recovered-from-client-history", call_id))
                        self._transition(call_id, "ACKNOWLEDGED")
                        recovered_state = _RESULT_STATES.get(operation["result_kind"])
                        if recovered_state is not None:
                            self._transition(call_id, recovered_state)
                return False
            self.db.execute(
                "INSERT INTO intents(call_id,conversation_id,name,schema_hash,status) VALUES(?,?,?,?,?)",
                (call_id, conversation_id, name, "recovered-from-client-history", "OFFERED_UNCONFIRMED"),
            )
            self.db.execute("INSERT INTO operations(call_id,conversation_id,name,schema_version,state,source) VALUES(?,?,?,?,?,?)",
                            (call_id, conversation_id, name, "recovered-from-client-history", "DISPATCHED", "client_history"))
            self.db.execute("UPDATE operations SET argument_hash=? WHERE call_id=?", (argument_hash, call_id))
            return True

    def accept_unmatched_client_result(self, call_id: str, conversation_id=None, result_kind="unknown"):
        """Accept an externally provided result without inventing missing intent.

        Some clients omit old assistant messages after compaction or switch
        gateway processes. The result remains unverified in the ledger; refusing
        it would break the agent even though this gateway executes no commands.
        An existing call belonging to another conversation is still rejected.
        """
        if not isinstance(call_id, str) or not call_id or len(call_id) > 256:
            raise BridgeError("TOOL_RECEIPT_MISSING_ID", "Tool result lacks a valid tool_call_id", 409)
        with self.lock, self.db:
            row = self.db.execute("SELECT conversation_id FROM intents WHERE call_id=?", (call_id,)).fetchone()
            if row is not None:
                if row[0] is not None and conversation_id is not None and row[0] != conversation_id:
                    raise BridgeError("CROSS_CONVERSATION_RECEIPT", "Result belongs to another conversation", 409)
                return False
            self.db.execute(
                "INSERT INTO intents(call_id,conversation_id,name,schema_hash,status,result_kind) VALUES(?,?,?,?,?,?)",
                (call_id, conversation_id, "(unmatched)", "unknown", "UNVERIFIED_CLIENT_RESULT", result_kind),
            )
            self.db.execute("INSERT INTO operations(call_id,conversation_id,name,schema_version,state,source,result_kind) VALUES(?,?,?,?,?,?,?)",
                            (call_id, conversation_id, "(unmatched)", "unknown", "EXECUTION_UNKNOWN", "unmatched_client_result", result_kind))
            return True

    def reconcile_client_history(self, messages: list[dict], conversation_id=None, classify_result=None, request_id=None):
        """Recover call/result relationships from the *original*, un-compacted chat.

        Chronological ordering matters: an assistant tool_call must precede its
        matching tool result to count as a recovered proposal. If no proposal is
        available, the tool output remains client-provided/unverified; no 409 is
        produced just because the local SQLite ledger was reset or relocated.
        """
        observed, fingerprints = {}, {}
        recovered = unmatched = receipts = duplicates = 0
        for message in messages:
            role = message.get("role")
            if role == "assistant":
                for call in message.get("tool_calls") or []:
                    if not isinstance(call, dict):
                        continue
                    call_id = call.get("id")
                    function = call.get("function")
                    name = function.get("name") if isinstance(function, dict) else None
                    if (isinstance(call_id, str) and call_id and len(call_id) <= 256
                            and isinstance(name, str) and name and len(name) <= 256):
                        if call_id in observed and observed[call_id] != name:
                            raise BridgeError("TOOL_CALL_ID_CONFLICT", "Conflicting tool call IDs in transcript", 409)
                        observed[call_id] = name
                        try:
                            arguments = loads(function.get("arguments", ""))
                            if isinstance(arguments, dict):
                                fingerprints[call_id] = argument_fingerprint(arguments)
                        except (ValueError, TypeError, RecursionError):
                            pass
                continue
            if role not in ("tool", "function"):
                continue
            call_id = message.get("tool_call_id")
            if role == "function" and not call_id:
                # Legacy OpenAI `function` messages have a name but no call_id.
                # They carry history context; never invent a tool receipt ID.
                unmatched += 1
                continue
            if not isinstance(call_id, str) or not call_id or len(call_id) > 256:
                raise BridgeError("TOOL_RECEIPT_MISSING_ID", "Tool result lacks a valid tool_call_id", 409)
            if call_id in observed:
                recovered += self.restore_intent_from_history(call_id, observed[call_id], conversation_id, fingerprints.get(call_id))
            operation = self.operation(call_id)
            name = observed.get(call_id) or (operation["name"] if operation else "(unmatched)")
            result_kind = classify_result({**message, "name": name}) if classify_result else "unknown"
            try:
                new_result = self.receive(call_id, conversation_id, result_kind)
                receipts += int(new_result)
                duplicates += int(not new_result)
                if new_result and request_id:
                    self.diagnostic(request_id, "tool_receipt_received", tool_type=tool_type(name))
                    self.diagnostic(request_id, "tool_outcome_classified", tool_type=tool_type(name), outcome=result_kind)
            except BridgeError as exc:
                if exc.code != "ORPHAN_TOOL_RESULT":
                    raise
                unmatched += int(self.accept_unmatched_client_result(call_id, conversation_id, result_kind))
        return {"recovered": recovered, "unmatched": unmatched,
                "receipts": receipts, "duplicates": duplicates}

    def status(self, call_id):
        with self.lock:
            row = self.db.execute("SELECT status FROM intents WHERE call_id=?", (call_id,)).fetchone()
            return row[0] if row else None

    def upstream_failure(self, request_id, code, metrics):
        """Persist only fixed-shape, bounded, non-secret SSE counters.

        The raw SSE event, JSON body, user messages, URLs, cookies, token values
        and arbitrary remote error strings are NEVER persisted.
        """
        allowed_events = {"error", "abort", "finish", "legacy-error", "legacy-finish", "unknown"}
        kind = metrics.get("upstream_event", "unknown")
        if kind not in allowed_events:
            kind = "unknown"
        fields = ("upstream_status", "sse_event_count", "sse_partial_text_chars",
                  "sse_body_bytes", "elapsed_ms", "input_message_count",
                  "input_tool_count", "upstream_request_bytes", "advisory_action_chars")
        nums = []
        for field in fields:
            v = metrics.get(field)
            nums.append(min(v, 2_000_000_000) if type(v) is int and v >= 0 else None)
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO upstream_failures(request_id,error_code,upstream_event,"
                "upstream_status,sse_event_count,sse_partial_text_chars,sse_body_bytes,"
                "elapsed_ms,input_message_count,input_tool_count,upstream_request_bytes,advisory_action_chars) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (request_id, code, kind, *nums),
            )

    def latest_upstream_failures(self, limit=6):
        keys = ("request_id", "error_code", "upstream_event", "upstream_status",
                "sse_event_count", "sse_partial_text_chars", "sse_body_bytes",
                "elapsed_ms", "input_message_count", "input_tool_count",
                "upstream_request_bytes", "advisory_action_chars", "at")
        with self.lock:
            rows = self.db.execute(
                "SELECT request_id,error_code,upstream_event,upstream_status,"
                "sse_event_count,sse_partial_text_chars,sse_body_bytes,elapsed_ms,"
                "input_message_count,input_tool_count,upstream_request_bytes,advisory_action_chars,created_at "
                "FROM upstream_failures ORDER BY seq DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(zip(keys, row)) for row in rows]

    def diagnostic(self, request_id, phase, error_code=None, **fields):
        fields = safe_fields(fields)
        with self.lock, self.db:
            keys = ["request_id", "phase", "error_code", *fields]
            self.db.execute("INSERT INTO diagnostics(" + ",".join(keys) + ") VALUES(" + ",".join("?" for _ in keys) + ")",
                            (request_id, phase, error_code, *fields.values()))
        log_event(request_id, phase, error_code, **fields)

    def latest(self, limit=8):
        with self.lock:
            return [{"phase": row[0], "error_code": row[1], "at": row[2]} for row in self.db.execute(
                "SELECT phase,error_code,created_at FROM diagnostics ORDER BY seq DESC LIMIT ?", (limit,))]

    def close(self):
        with self.lock:
            self.db.close()
