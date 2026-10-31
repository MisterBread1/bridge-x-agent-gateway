"""Input schemas, permissive about ZCode extensions but strict for tools."""
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, PrivateAttr


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: Any = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    @field_validator("role")
    @classmethod
    def role_ok(cls, value):
        if value not in {"system", "developer", "user", "assistant", "tool", "function"}:
            raise ValueError("invalid role")
        return value


class ToolDeclaration(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["function"] = "function"
    function: dict[str, Any]

    @field_validator("function")
    @classmethod
    def valid_function(cls, value):
        if not isinstance(value.get("name"), str) or not value["name"]:
            raise ValueError("tool function.name required")
        if not isinstance(value.get("parameters", {"type": "object"}), dict):
            raise ValueError("tool parameters must be a JSON Schema object")
        return value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    _execution_scope: str = PrivateAttr(default="main_turn")
    model: str = "molab-glm"
    messages: list[ChatMessage] = Field(min_length=1)
    tools: list[ToolDeclaration] = Field(default_factory=list)
    stream: bool = False
    tool_choice: Any = "auto"
    parallel_tool_calls: bool = False
    conversation_id: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("tool_choice")
    @classmethod
    def choice_ok(cls, value):
        if isinstance(value, str) and value in ("auto", "none", "required"):
            return value
        if isinstance(value, dict) and value.get("type") == "function" and isinstance(value.get("function"), dict) and isinstance(value["function"].get("name"), str):
            return value
        raise ValueError("invalid tool_choice")


class OperationVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str | None = None
    expected_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    observed_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
