import pytest
from bridge_x.schemas import ChatRequest


WRITE = {"type": "function", "function": {"name": "Write", "parameters": {"type": "object", "properties": {
    "path": {"type": "string"}, "content": {"type": "string"}},
    "required": ["path", "content"], "additionalProperties": False}}}
BASH = {"type": "function", "function": {"name": "Bash", "parameters": {"type": "object", "properties": {
    "command": {"type": "string"}}, "required": ["command"], "additionalProperties": False}}}


@pytest.fixture
def tools():
    return [WRITE, BASH]


@pytest.fixture
def request_factory(tools):
    def factory(**overrides):
        data = {"model": "bridge-x-fake", "messages": [{"role": "user", "content": "agent_check.py"}],
                "tools": tools, "stream": False, "tool_choice": "auto"}
        data.update(overrides)
        return ChatRequest.model_validate(data)
    return factory
