"""Reproductions of boundary defects discovered during the full audit."""
import json
import math
import httpx
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.errors import BridgeError
from bridge_x.gateway import create_app
from bridge_x.molab_provider import MolabProvider, decode_molab_event, read_molab_config
from bridge_x.providers import Failed, Finish, GenericOpenAIProvider, NativeToolDelta, TextDelta
from bridge_x.receipts import classify_result
from bridge_x.schemas import ChatRequest
from bridge_x.sse import SSEEvent, SSEParser
from bridge_x.tools import parse_intent, registry, validate_native
from bridge_x_test_runner.runner import Sandbox, SandboxError
from .conftest import WRITE
from .test_molab_integration import mock_molab, save_config, response_stream
from .test_provider_transport import provider_for

AUTH = {"Authorization": "Bearer molab-local"}


@pytest.mark.parametrize("name", ["timeout_s", "heartbeat_s"])
@pytest.mark.parametrize("value", [0, -1, math.inf, math.nan, True])
def test_deadline_and_heartbeat_are_finite_positive(name, value):
    with pytest.raises(ValueError):
        Settings(**{name: value})


@pytest.mark.parametrize("value", ["", " "])
def test_empty_local_key_is_not_an_authentication_scheme(value):
    with pytest.raises(ValueError):
        Settings(local_api_key=value)


@pytest.mark.parametrize("content", [
    b'{"messages":[{"role":"user","content":NaN}]}',
    b'{"messages":[{"role":"user","content":1e9999}]}',
    b'{"messages":[{"role":"user","content":"\\ud800"}]}',
    b'{"messages":[{"role":"user","role":"assistant"}]}',
    b'{"messages":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}',
])
def test_invalid_json_values_rejected_before_provider(content):
    with TestClient(create_app(Settings(journal_path=":memory:"))) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, content=content)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("choice", ["required", {"type": "function", "function": {"name": "Missing"}}])
def test_impossible_tool_choice_is_rejected_before_generation(choice):
    with TestClient(create_app(Settings(journal_path=":memory:"))) as client:
        response = client.post("/v1/chat/completions", headers=AUTH,
                               json={"messages": [{"role": "user", "content": "hi"}], "tool_choice": choice})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "TOOL_NOT_AVAILABLE"


def test_empty_sse_data_lines_are_bounded():
    with pytest.raises(BridgeError) as exc:
        SSEParser(max_event_chars=30).feed(b"data:\n" * 31)
    assert exc.value.code == "SSE_EVENT_TOO_LARGE"


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85", "\x0b", "\x0c"])
def test_unicode_source_separators_are_not_protocol_lines(separator):
    req = ChatRequest(messages=[{"role": "user", "content": "test"}], tools=[WRITE])
    source = "before" + separator + "after"
    frame = "@@CALL_V2 Write\n@@FIELD path\na.txt\n@@FIELD content\n" + source + "\n@@END_CALL"
    assert parse_intent(frame, req)[0].arguments["content"] == source
    legacy = "@@TOOL_CALL Write\n@@ARG path\na.txt\n@@END_ARG\n@@ARG content\n" + source + "\n@@END_ARG\n@@END_TOOL_CALL"
    assert parse_intent(legacy, req)[0].arguments["content"] == source


def test_duplicate_keys_in_executable_json_are_not_silently_overwritten():
    req = ChatRequest(messages=[{"role": "user", "content": "test"}], tools=[WRITE])
    with pytest.raises(BridgeError) as exc:
        parse_intent('{"tool":"Write","arguments":{"path":"safe","path":"different","content":"x"}}', req)
    assert exc.value.code == "INVALID_TOOL_JSON"
    with pytest.raises(BridgeError) as exc:
        validate_native([{"function": {"name": "Write", "arguments": '{"path":"a","path":"b","content":"x"}'}}], req)
    assert exc.value.code == "INVALID_TOOL_JSON"


def test_dynamic_external_schema_reference_is_rejected():
    req = ChatRequest(messages=[{"role": "user"}], tools=[{"function": {
        "name": "Unsafe", "parameters": {"$dynamicRef": "https://example.invalid/private"}}}])
    with pytest.raises(BridgeError) as exc:
        registry(req)
    assert exc.value.code == "INVALID_TOOL_SCHEMA"


def test_ref_looking_data_inside_enum_is_not_a_schema_reference():
    req = ChatRequest(messages=[{"role": "user"}], tools=[{"function": {"name": "Config", "parameters": {
        "type": "object", "properties": {"data": {"enum": [{"$ref": "literal data"}]}}, "required": ["data"]}}}])
    assert parse_intent('{"tool":"Config","arguments":{"data":{"$ref":"literal data"}}}', req)


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", [
    b'data: {"choices":[{"delta":{"content":"late"}}]}\n\n',
    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
])
async def test_generic_stream_cannot_hide_invalid_events_after_finish(monkeypatch, suffix):
    wire = b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n' + suffix + b'data: [DONE]\n\n'
    provider = provider_for(monkeypatch, lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire))
    req = ChatRequest(messages=[{"role": "user"}])
    events = [e async for e in provider.generate(req, [])]
    assert isinstance(events[-1], Failed)
    assert not any(isinstance(e, Finish) for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["finish", "done"])
async def test_molab_rejects_text_after_termination(monkeypatch, tmp_path, terminal):
    head = response_stream({"type": "finish", "finishReason": "stop"}) if terminal == "finish" else b'data: [DONE]\n\n'
    wire = head + response_stream({"type": "text-delta", "delta": "late action"})
    mock_molab(monkeypatch, lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire))
    provider = MolabProvider(Settings(provider="molab", molab_config_path=save_config(tmp_path)))
    req = ChatRequest(messages=[{"role": "user"}])
    events = [e async for e in provider.generate(req, [])]
    assert events[-1].code == "UPSTREAM_AFTER_FINISH"
    assert not any(isinstance(e, Finish) for e in events)


@pytest.mark.parametrize("decoder", [GenericOpenAIProvider._decode, lambda event: decode_molab_event(event.data, event.event)])
def test_error_event_containing_done_is_still_an_error(decoder):
    assert isinstance(decoder(SSEEvent("error", "[DONE]"))[0], Failed)


@pytest.mark.parametrize("raw", ["[]", '{"type":"text-delta","delta":42}', '{"type":"text-delta","delta":"\\ud800"}'])
def test_malformed_molab_events_do_not_become_empty_success(raw):
    assert isinstance(decode_molab_event(raw)[0], Failed)


@pytest.mark.parametrize("value", [None, False, 0, {}, []])
def test_native_arguments_require_json_text(value):
    output = GenericOpenAIProvider._decode(SSEEvent("message", json.dumps({"choices": [{"delta": {
        "tool_calls": [{"index": 0, "function": {"arguments": value}}]}}]})))
    assert isinstance(output[0], Failed)


@pytest.mark.parametrize("patch", [
    {"marimo_server_token": "bad\nheader"}, {"marimo_server_token": "\u043a\u043b\u044e\u0447"},
    {"http_headers": {"X-Test": "bad\x00value"}},
])
def test_invalid_headers_fail_as_config_errors(tmp_path, patch):
    with pytest.raises(BridgeError) as exc:
        read_molab_config(save_config(tmp_path, **patch))
    assert exc.value.code == "MOLAB_CONFIG_INVALID"


def test_bom_config_from_windows_is_supported(tmp_path):
    path = save_config(tmp_path)
    from pathlib import Path
    file = Path(path)
    file.write_text(file.read_text(encoding="utf-8"), encoding="utf-8-sig")
    assert read_molab_config(path).session_id == "s_correct"


@pytest.mark.parametrize("content,kind", [
    ('{"exit_code":false}', "unknown"), ('{"exit_code":0,"success":false}', "reported_failure"),
    ('{"timed_out":true,"exit_code":0}', "timed_out"), ('{"stdout":"done"}', "unknown"),
])
def test_only_explicit_typed_receipts_confirm_execution(content, kind):
    assert classify_result({"content": content}) == kind


def test_patch_rejects_inconsistent_new_line_position_without_writing(tmp_path):
    runner = Sandbox(tmp_path)
    runner.write("a.txt", "hello\n")
    with pytest.raises(SandboxError):
        runner.apply_patch("--- a/a.txt\n+++ b/a.txt\n@@ -1 +99 @@\n-hello\n+changed\n")
    assert runner.read("a.txt")["content"] == "hello\n"


def test_native_none_arguments_is_a_typed_error_not_gateway_500():
    class Bad:
        async def generate(self, req, messages):
            yield NativeToolDelta(0, "id", "Write", None)
            yield Finish("stop")
    with TestClient(create_app(Settings(journal_path=":memory:"), provider=Bad())) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user"}], "tools": [WRITE]})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_NATIVE_TOOL_DELTA"


def test_live_check_accepts_current_version_and_configured_key(monkeypatch):
    import LIVE_CHECK
    from bridge_x import __version__
    real_client = httpx.Client
    requests = []
    def handle(request):
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"version": __version__, "provider": "molab"})
        assert request.headers["authorization"] == "Bearer custom-local-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setenv("BRIDGEX_LOCAL_KEY", "custom-local-key")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    assert LIVE_CHECK.main() == 0
    assert len(requests) == 2


def test_large_terminal_output_is_bounded_and_retains_tail(tmp_path):
    runner = Sandbox(tmp_path)
    runner.write("large.py", "import sys\nprint('HEAD')\nprint('x' * 2_000_000)\nprint('TAIL')\nprint('ERROR-END', file=sys.stderr)\n")
    receipt = runner.run_python("large.py")
    assert receipt.exit_code == 0
    assert receipt.stdout_bytes > 2_000_000 and receipt.stdout_truncated
    assert len(receipt.stdout) <= 100_000
    assert receipt.stdout.startswith("HEAD") and receipt.stdout.rstrip().endswith("TAIL")
    assert "ERROR-END" in receipt.stderr


def test_terminal_timeout_keeps_partial_output_and_is_not_success(tmp_path):
    runner = Sandbox(tmp_path)
    runner.write("slow.py", "import time\nprint('STARTED', flush=True)\ntime.sleep(10)\n")
    receipt = runner.run_python("slow.py", timeout=0.5)
    assert receipt.timed_out and receipt.status == "timeout"
    assert receipt.exit_code is None
    assert "STARTED" in receipt.stdout


@pytest.mark.parametrize("text", ["\ud800", 42, None])
def test_invalid_provider_text_returns_a_sanitized_error(text):
    class BadText:
        async def generate(self, req, messages):
            yield TextDelta(text)
            yield Finish("stop")
    with TestClient(create_app(Settings(journal_path=":memory:"), provider=BadText())) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user"}]})
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "UPSTREAM_INVALID_TEXT_DELTA"
