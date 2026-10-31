"""Keep independent ZCode agents separate without changing session ownership."""
import hashlib
import json
import re


def resolve_execution_scope(messages, query_source=None):
    source = query_source or "main_turn"
    if not isinstance(source, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", source):
        source = "other"
    if source == "main_turn":
        return source
    # The background job borrows the foreground transcript, then appends its
    # own user task. That prefix stays unchanged through its tool/result loop.
    # A later memory job has a different prefix and must not inherit a pending
    # operation from an older extraction that stopped at its turn budget.
    last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    prefix = messages[:last_user + 1]
    digest = hashlib.sha256(json.dumps(prefix, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8")).hexdigest()[:32]
    return source + ":" + digest
