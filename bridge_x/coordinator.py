"""Client-owned sessions, dispatch deduplication and receipt recovery."""
from dataclasses import dataclass
import hashlib
import json
from .context import compact
from .journal import Journal
from .receipts import classify_result
from .schemas import ChatRequest
from .errors import BridgeError


@dataclass(frozen=True)
class AgentTurn:
    request_key: str | None
    conversation_id: str | None
    messages: list[dict]
    receipts: dict
    context_budget: dict
    execution_scope: str = "main_turn"
    history_call_ids: tuple[str, ...] = ()


class ToolCoordinator:
    def __init__(self, journal: Journal, max_context_chars: int):
        self.journal = journal
        self.max_context_chars = max_context_chars

    def prepare(self, req: ChatRequest, messages: list[dict], execution_scope="main_turn", request_id=None) -> AgentTurn:
        # Stream/non-stream retries represent the same operation. Full content
        # is hashed and is never stored in the dispatch ledger.
        # Transport/SDK options may change on a retry. Only the actual agent
        # input and execution branch identify an operation request.
        basis = {key: getattr(req, key) for key in ("model", "tool_choice", "parallel_tool_calls", "conversation_id")}
        basis["messages"] = [m.model_dump(exclude_none=True) for m in req.messages]
        basis["tools"] = [t.model_dump(exclude_none=True) for t in req.tools]
        basis["execution_scope"] = execution_scope
        if req.idempotency_key:
            basis = {"conversation_id": req.conversation_id, "idempotency_key": req.idempotency_key,
                     "execution_scope": execution_scope}
        key = (hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode("utf-8")).hexdigest()
               if req.conversation_id is not None or req.idempotency_key else None)
        receipts = self.journal.reconcile_client_history(messages, req.conversation_id, classify_result, request_id, execution_scope)
        if execution_scope == "main_turn" and key is not None:
            # Preserve the previous release's exact-request guard across the
            # fingerprint migration; a completed old side effect must not be
            # re-offered merely because this release hashes transport options
            # differently.
            legacy_basis = req.model_dump(exclude={"stream"}, exclude_none=True)
            if req.idempotency_key:
                legacy_basis = {"conversation_id": req.conversation_id, "idempotency_key": req.idempotency_key}
            legacy_key = hashlib.sha256(json.dumps(legacy_basis, ensure_ascii=False, sort_keys=True,
                                                   separators=(",", ":")).encode("utf-8")).hexdigest()
            if legacy_key != key:
                self.journal.ensure_new_turn(legacy_key, req.conversation_id, False, execution_scope=execution_scope)
        self.journal.ensure_new_turn(key, req.conversation_id, bool(req.tools and req.tool_choice != "none"), execution_scope=execution_scope)
        schema_chars = len(json.dumps([t.function for t in req.tools], ensure_ascii=False, separators=(",", ":"))) if req.tools and req.tool_choice != "none" else 0
        message_budget = self.max_context_chars - schema_chars - min(4096, self.max_context_chars // 10)
        if message_budget < 1:
            raise BridgeError("CONTEXT_BUDGET_EXCEEDED", "Declared tool schemas exceed the context budget; disable unused client tools or skills for this session", 413)
        bounded, budget = compact(messages, message_budget)
        call_ids = tuple({call.get("id") for m in messages for call in (m.get("tool_calls") or []) if isinstance(call.get("id"), str)})
        return AgentTurn(key, req.conversation_id, bounded, receipts, budget, execution_scope, call_ids)

    def dispatch(self, turn: AgentTurn, calls):
        self.journal.deliver(calls, turn.conversation_id, request_key=turn.request_key, execution_scope=turn.execution_scope, history_call_ids=turn.history_call_ids)
