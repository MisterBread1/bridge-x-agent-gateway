"""Bound historical tool output. Never truncate executable arguments or pending calls."""
import hashlib
import copy
import json
from .errors import BridgeError
from .json_utils import loads


def _elide(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    head = value[:limit // 4]
    tail = value[-(limit - len(head)):]
    return f"{head}\n[OLD TOOL OUTPUT COMPACTED original_chars={len(value)} sha256_prefix={digest}]\n{tail}"


def _length(messages):
    return len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")))


def _elide_result(value, limit):
    """Keep typed receipt fields intact when shortening an old JSON stdout."""
    if len(value) <= limit:
        return value
    try:
        receipt = loads(value)
    except (ValueError, RecursionError):
        return _elide(value, limit)
    if not isinstance(receipt, dict):
        return value  # archive the entire paired exchange if it cannot fit
    for key in ("stdout", "stderr", "content", "output"):
        if isinstance(receipt.get(key), str):
            receipt[key] = _elide(receipt[key], max(100, limit // 4))
    return json.dumps(receipt, ensure_ascii=False, separators=(",", ":"))


def compact(messages: list[dict], max_context_chars: int, max_single_tool: int = 12_000):
    """Return bounded transcript + metadata without mutating caller.

    Removes only old, fully paired assistant(tool_calls)+tool(result) cycles.
    Their receipts remain in the independent persistent journal, NOT fabricated
    in the abbreviated context. Never delete a pending or recent tool call.
    """
    result = copy.deepcopy(messages)
    before = _length(result)
    changed = archived_pairs = 0
    protected = set(range(max(0, len(result) - 4), len(result)))
    first_user = next((i for i, m in enumerate(result) if m.get("role") == "user"), None)
    if first_user is not None:
        protected.add(first_user)
    for idx, item in enumerate(result):
        if idx not in protected and item.get("role") in ("tool", "function") and isinstance(item.get("content"), str):
            new = _elide_result(item["content"], max_single_tool)
            changed += new != item["content"]
            item["content"] = new
    if _length(result) > max_context_chars:
        for idx, item in enumerate(result):
            if idx not in protected and item.get("role") in ("tool", "function") and isinstance(item.get("content"), str):
                item["content"] = _elide_result(item["content"], 1_500)
                if _length(result) <= max_context_chars:
                    break

    # Remove old, fully paired tool cycles as UNVERIFIED archived history.
    # Start from the oldest cycle and keep the user goal and latest four messages.
    if _length(result) > max_context_chars:
        drop = set()
        for i, assistant in enumerate(result):
            if i in protected or assistant.get("role") != "assistant" or not assistant.get("tool_calls"):
                continue
            calls = assistant.get("tool_calls")
            if not isinstance(calls, list) or not calls:
                continue
            wanted = {c.get("id") for c in calls if isinstance(c, dict) and c.get("id")}
            if len(wanted) != len(calls):
                continue
            matches = []
            for j in range(i + 1, min(i + len(calls) + 1, len(result))):
                item = result[j]
                if j in protected or item.get("role") not in ("tool", "function"):
                    break
                if item.get("tool_call_id") not in wanted:
                    break
                matches.append(j)
            if len(matches) != len(calls) or {result[j]["tool_call_id"] for j in matches} != wanted:
                continue
            drop.update([i, *matches])
            archived_pairs += 1
            # Only need a count and a neutral marker, not old prompt-injection text.
            temporary = [v for idx, v in enumerate(result) if idx not in drop]
            if _length(temporary) + 240 <= max_context_chars:
                break
        if drop:
            marker = {"role": "assistant", "content": (
                f"[Bridge X context archival: {archived_pairs} older complete tool-call/result "
                "exchange(s) omitted to fit context. Outcomes are not implied. "
                "Do not claim these actions succeeded without receipts.]"
            )}
            result = [v for idx, v in enumerate(result) if idx not in drop]
            first_remaining_user = next((i for i, m in enumerate(result) if m.get("role") == "user"), None)
            insert_at = first_remaining_user + 1 if first_remaining_user is not None else 0
            result.insert(insert_at, marker)

    # If large older assistant prose alone fills the context, shrink it (never
    # executable arguments, initial user goal, latest 4 messages or tool results).
    if _length(result) > max_context_chars:
        protected_now = set(range(max(0, len(result)-4), len(result)))
        first_now = next((i for i, m in enumerate(result) if m.get("role") == "user"), None)
        if first_now is not None:
            protected_now.add(first_now)
        for i, item in enumerate(result):
            if i not in protected_now and item.get("role") == "assistant" and not item.get("tool_calls") and isinstance(item.get("content"), str):
                item["content"] = _elide(item["content"], 500)
                if _length(result) <= max_context_chars:
                    break
    # Recent completed output can itself exceed the entire budget (for
    # example a large Read just before this turn). The old last-four-message
    # exemption made these sessions stop even though their history was safe
    # to shorten. Reconciliation already saw the original receipt. Retain its
    # typed outcome and an explicit elision marker; never alter pending input.
    if _length(result) > max_context_chars:
        declared = {c.get("id") for m in result for c in (m.get("tool_calls") or []) if isinstance(c, dict)}
        for item in result:
            if item.get("role") in ("tool", "function") and item.get("tool_call_id") in declared and isinstance(item.get("content"), str):
                new = _elide_result(item["content"], 1500)
                changed += new != item["content"]
                item["content"] = new
                if _length(result) <= max_context_chars:
                    break
    # Completed large Write/Edit inputs cannot be truncated. Archive the
    # whole original exchange instead, including interleaved/duplicate
    # receipts. Preserve every user/system instruction and each pending call.
    if _length(result) > max_context_chars:
        received = {}
        for i, item in enumerate(result):
            if item.get("role") in ("tool", "function"):
                received.setdefault(item.get("tool_call_id"), []).append(i)
        drop = set()
        for i, item in enumerate(result):
            calls = item.get("tool_calls") if item.get("role") == "assistant" else None
            if not calls or not all(isinstance(c, dict) and c.get("id") in received and all(j > i for j in received[c["id"]]) for c in calls):
                continue
            drop.add(i)
            for call in calls:
                drop.update(received[call["id"]])
            archived_pairs += 1
            candidate = [m for j, m in enumerate(result) if j not in drop]
            if _length(candidate) + 240 <= max_context_chars:
                break
        if drop:
            result = [m for j, m in enumerate(result) if j not in drop]
            marker = {"role": "assistant", "content": "[Bridge X context archival: older complete tool exchanges omitted. Original receipts remain in the local journal. Outcomes are not implied. Inspect current client state before repeating actions.]"}
            insert_at = next((i + 1 for i, m in enumerate(result) if m.get("role") == "user"), 0)
            result.insert(insert_at, marker)
    if _length(result) > max_context_chars:
        for i, item in enumerate(result):
            if i < len(result) - 1 and item.get("role") == "assistant" and not item.get("tool_calls") and isinstance(item.get("content"), str):
                item["content"] = _elide(item["content"], 500)
                if _length(result) <= max_context_chars:
                    break
    after = _length(result)
    if after > max_context_chars:
        raise BridgeError("CONTEXT_BUDGET_EXCEEDED", "Active instructions or unfinished tool inputs exceed the context budget after history compaction; reduce attached content or enabled client skills, preserving the original task and pending receipts", 413)
    return result, {"before_chars": before, "after_chars": after,
                    "compacted_tool_outputs": changed, "archived_completed_exchanges": archived_pairs}
