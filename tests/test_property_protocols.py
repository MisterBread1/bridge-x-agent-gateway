"""Generated round-trip and fragmentation checks without external services."""
import json
from hypothesis import given, settings, strategies as st
from bridge_x.schemas import ChatRequest
from bridge_x.sse import SSEParser, sse_data
from bridge_x.tools import parse_intent
from .conftest import WRITE

TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=500)


@settings(max_examples=150, deadline=None)
@given(TEXT, st.lists(st.integers(min_value=1, max_value=19), min_size=1, max_size=30))
def test_arbitrary_utf8_sse_chunk_boundaries(text, widths):
    wire = sse_data({"text": text}).encode("utf-8")
    expected = SSEParser().feed(wire)
    parser = SSEParser()
    actual = []
    position = 0
    index = 0
    while position < len(wire):
        width = widths[index % len(widths)]
        actual.extend(parser.feed(wire[position:position + width]))
        position += width
        index += 1
    actual.extend(parser.finish())
    assert actual == expected
    assert json.loads(actual[0].data)["text"] == text


@settings(max_examples=150, deadline=None)
@given(TEXT)
def test_json_tool_arguments_roundtrip_without_coercing_source(text):
    req = ChatRequest(messages=[{"role": "user"}], tools=[WRITE])
    call = parse_intent(json.dumps({"tool": "Write", "arguments": {"path": "a.txt", "content": text}}), req)[0]
    assert call.arguments["content"] == text


@settings(max_examples=150, deadline=None)
@given(st.integers(min_value=0, max_value=100000), st.sampled_from(["\n", "\r\n", "\r"]))
def test_integer_text_normalization_preserves_schema_constraints(value, newline):
    req = ChatRequest(messages=[{"role": "user"}], tools=[{"function": {"name": "Read", "parameters": {
        "type": "object", "properties": {"offset": {"type": "integer", "minimum": 0}}, "required": ["offset"]}}}])
    raw = newline.join(["@@CALL_V2 Read", "@@FIELD offset", str(value), "@@END_CALL"])
    assert parse_intent(raw, req)[0].arguments["offset"] == value
