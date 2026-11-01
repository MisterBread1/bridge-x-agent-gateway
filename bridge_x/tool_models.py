"""Tool proposals are data; execution remains in the requesting client."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
import json


class OperationState(StrEnum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    DISPATCHED = "DISPATCHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"
    RESOLVED_BY_CHECK = "RESOLVED_BY_CHECK"


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    schema_hash: str
    conversation_id: str | None = None
    status: OperationState = OperationState.VALIDATED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def schema_version(self):
        return self.schema_hash

    def openai(self):
        return {"id": self.id, "type": "function", "function": {
            "name": self.name,
            "arguments": json.dumps(self.arguments, ensure_ascii=False, separators=(",", ":"))}}
