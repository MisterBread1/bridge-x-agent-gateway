import json
import pytest
from bridge_x.tools import parse_intent, validate_native, registry
from bridge_x.errors import BridgeError


def intent(name="Write", args=None):
    return json.dumps({"tool_calls": [{"name": name, "arguments": args if args is not None else {"path": "agent_check.py", "content": "print(2+2)"}}]})


def test_valid_write(request_factory):
    calls = parse_intent(intent(), request_factory())
    assert len(calls) == 1
    assert calls[0].name == "Write"
    assert calls[0].openai()["function"]["arguments"] == '{"path":"agent_check.py","content":"print(2+2)"}'


def test_unknown_tool(request_factory):
    with pytest.raises(BridgeError, match="not declared"):
        parse_intent(intent("DropDatabase"), request_factory())


def test_schema_rejects_missing_path(request_factory):
    with pytest.raises(BridgeError) as exc:
        parse_intent(intent(args={"content": "x"}), request_factory())
    assert exc.value.code == "TOOL_SCHEMA_MISMATCH"


def test_schema_rejects_extra_property(request_factory):
    with pytest.raises(BridgeError) as exc:
        parse_intent(intent(args={"path": "x", "content": "x", "undefined": "x"}), request_factory())
    assert exc.value.code == "TOOL_SCHEMA_MISMATCH"


def test_no_markdown_scavenging(request_factory):
    assert parse_intent('```json\n' + intent() + '\n```', request_factory()) is None


def test_rejects_partial_json(request_factory):
    with pytest.raises(BridgeError) as exc:
        parse_intent('{"tool_calls": [{"name":"Write","arguments":', request_factory())
    assert exc.value.code == "INVALID_TOOL_JSON"


def test_text_remains_text(request_factory):
    assert parse_intent("I will create a file", request_factory()) is None


def test_no_tools_when_disabled(request_factory):
    with pytest.raises(BridgeError) as exc:
        parse_intent(intent(), request_factory(tool_choice="none"))
    assert exc.value.code == "TOOL_CHOICE_NONE"


def test_forced_name_is_enforced(request_factory):
    choice = {"type": "function", "function": {"name": "Bash"}}
    with pytest.raises(BridgeError) as exc:
        parse_intent(intent(), request_factory(tool_choice=choice))
    assert exc.value.code == "WRONG_FORCED_TOOL"


def test_parallel_not_allowed(request_factory):
    env = {"tool_calls": [
        {"name": "Write", "arguments": {"path": "a", "content": "x"}},
        {"name": "Write", "arguments": {"path": "b", "content": "y"}}]}
    with pytest.raises(BridgeError) as exc:
        parse_intent(json.dumps(env), request_factory())
    assert exc.value.code == "PARALLEL_TOOLS_DISABLED"


def test_native_calls_are_validated(request_factory):
    calls = validate_native([{"function": {"name": "Bash", "arguments": '{"command":"python agent_check.py"}'}}], request_factory())
    assert calls[0].name == "Bash"


def test_native_calls_bad_json(request_factory):
    with pytest.raises(BridgeError) as exc:
        validate_native([{"function": {"name": "Write", "arguments": "{"}}], request_factory())
    assert exc.value.code == "INVALID_TOOL_JSON"


def test_duplicate_schemas_rejected(request_factory, tools):
    with pytest.raises(BridgeError):
        registry(request_factory(tools=[tools[0], tools[0]]))


def test_bad_schema_rejected(request_factory, tools):
    bad = json.loads(json.dumps(tools[0]))
    bad["function"]["parameters"]["type"] = "imaginary"
    with pytest.raises(BridgeError) as exc:
        registry(request_factory(tools=[bad]))
    assert exc.value.code == "INVALID_TOOL_SCHEMA"


def test_budget_never_truncates_argument(request_factory):
    with pytest.raises(BridgeError):
        parse_intent(intent(args={"path": "x", "content": "A" * 1000}), request_factory(), max_args_bytes=128)


def test_depth_limit(request_factory):
    nested = {}
    node = nested
    for _ in range(70):
        node["child"] = {}
        node = node["child"]
    with pytest.raises(BridgeError):
        parse_intent(intent(args=nested), request_factory())
