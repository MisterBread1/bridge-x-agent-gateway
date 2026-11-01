"""Compatibility parsers; all actions use the shared schema engine."""
import json
import re
from typing import Any
from .errors import BridgeError
from .schemas import ChatRequest
from .tool_frames import parse_frame_v2, protocol_lines
from .json_utils import loads as strict_loads, valid_value
from .tool_models import ToolCall
from .schema_engine import registry, tool_choice_name, validate_specs as _validate_specs


def _parse_frame(text: str, req: ChatRequest, max_args_bytes: int):
    """Parse exactly one bounded text command, including argument-free calls.

    Command bodies are opaque literal strings: an `@@ARG ...` line *inside* a
    Write payload must never become a second argument. Escape any literal
    closing marker as `\\@@END_ARG` (or `\\@@END_VALUE`). The escape is
    removed from the actual string value before validating the tool schema.
    """
    if len(text.encode("utf-8")) > max_args_bytes * 2:
        raise BridgeError("TOOL_FRAME_TOO_LARGE", "Tool frame exceeds size limit", 422)
    # Keep CR/LF in the source file payload (Windows files may use CRLF).
    lines = protocol_lines(text)
    def marker(line):
        return line.rstrip("\r\n")
    if not lines:
        raise BridgeError("INVALID_TOOL_FRAME", "Empty tool frame", 422)
    start = re.fullmatch(r"@@TOOL_CALL[ \t]+([A-Za-z][A-Za-z0-9_.-]{0,127})[ \t]*", marker(lines[0]))
    if not start:
        raise BridgeError("INVALID_TOOL_FRAME", "Tool frame must begin with one declared command", 422)
    values = {}
    pos = 1
    closed = False
    while pos < len(lines):
        line = marker(lines[pos])
        if re.fullmatch(r"@@END_TOOL_CALL[ \t]*", line):
            if any(x.strip() for x in lines[pos+1:]):
                raise BridgeError("INVALID_TOOL_FRAME", "Unexpected text after command", 422)
            closed = True
            break
        found = re.fullmatch(r"@@(ARG|VALUE)[ \t]+([A-Za-z][A-Za-z0-9_.-]{0,127})[ \t]*", line)
        if not found:
            raise BridgeError("INVALID_TOOL_FRAME", "Expected an argument or command terminator", 422)
        kind, key = found.groups()
        if key in values or len(values) >= 32:
            raise BridgeError("INVALID_TOOL_FRAME", "Duplicate or too many argument fields", 422)
        closer = "@@END_ARG" if kind == "ARG" else "@@END_VALUE"
        pos += 1
        chunks = []
        ended = False
        while pos < len(lines):
            piece = lines[pos]
            literal = marker(piece)
            if literal == closer:
                ended = True
                pos += 1
                break
            if literal == "@@END_TOOL_CALL":
                raise BridgeError("INVALID_TOOL_FRAME", "Unterminated tool argument", 422)
            # A backslash quotes a line that equals a protocol marker. This
            # makes files containing the delimiter representable without JSON.
            if literal.startswith("\\@@") and literal[1:] in ("@@END_ARG", "@@END_VALUE", "@@END_TOOL_CALL"):
                piece = piece[1:]
            chunks.append(piece)
            pos += 1
        if not ended:
            raise BridgeError("INVALID_TOOL_FRAME", "Unterminated tool argument", 422)
        value = "".join(chunks)
        if value.endswith("\r\n"):
            value = value[:-2]
        elif value.endswith(("\n", "\r")):
            value = value[:-1]
        if kind == "ARG":
            values[key] = value
        else:
            try:
                values[key] = strict_loads(value)
            except (ValueError, RecursionError):
                raise BridgeError("INVALID_TOOL_VALUE", "Typed argument is not a valid JSON value", 422) from None
    if not closed:
        raise BridgeError("INVALID_TOOL_FRAME", "Tool frame missing end marker", 422)
    return _validate_specs([{"name": start.group(1), "arguments": values}], req, max_args_bytes,
                           normalize_text_scalars=True)


def is_history_echo(text: str) -> bool:
    """Detect an old, prompt-serialized tool proposal replayed as assistant text.

    Not a tool instruction. Do not try to repair or execute it.
    """
    return bool(re.match(
        r"^(?:(?:\\)?<previous_tool_calls(?:\s|>)|\[Completed client tool history:)",
        text.lstrip("\ufeff \t\r\n"), re.I))


def parse_intent(text: str, req: ChatRequest, max_args_bytes=256_000) -> list[ToolCall] | None:
    """Accepted envelopes: {tool_calls:[{name,arguments}]} or {tool,arguments}.

    None means ordinary text. Malformed JSON-looking tool intent fails closed.
    No Markdown code fence scavenging, no loose JSON repair.
    """
    if not isinstance(text, str) or not valid_value(text):
        raise BridgeError("INVALID_TOOL_JSON", "Tool intent is not valid UTF-8 text", 422)
    # Strip only surrounding whitespace and an optional UTF-8 BOM. A tool
    # proposal is executable ONLY when the whole assistant reply is a single
    # explicit command envelope. Merely MENTIONING a protocol token in prose,
    # Markdown, a quoted example, or a legacy command argument is not enough.
    t = text.strip().lstrip("\ufeff").strip()
    # Never present serialized historical calls as a new assistant answer.
    # In older builds history contained <previous_tool_calls> with complete
    # argument JSON. Molab sometimes echoed it verbatim, including malformed
    # quoting. Replaying that text could duplicate edits or shell commands.
    # This is a protocol failure, not an instruction to repair JSON.
    if is_history_echo(t):
        raise BridgeError("UPSTREAM_HISTORY_ECHO",
                          "Model echoed earlier tool-call history instead of producing a new action", 502)
    if re.match(r"\A@@CALL_V2(?=[ \t\r\n]|$)", t):
        name, values = parse_frame_v2(t, max_args_bytes)
        # The same JSON Schema validator is the single point of truth for
        # both new text frames, legacy frames, and native function calls.
        return _validate_specs([{"name": name, "arguments": values}], req, max_args_bytes,
                               normalize_text_scalars=True)
    if re.match(r"\A@@TOOL_CALL(?=[ \t\r\n]|$)", t):
        return _parse_frame(t, req, max_args_bytes)
    if not t.startswith("{"):
        return None
    if len(t.encode("utf-8")) > max_args_bytes * 8:
        raise BridgeError("TOOL_ENVELOPE_TOO_LARGE", "Tool envelope exceeded size limit", 422)
    try:
        payload = strict_loads(t)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if '"tool"' in t or '"tool_calls"' in t:
            raise BridgeError("INVALID_TOOL_JSON", "Incomplete or invalid tool intent JSON", 422) from exc
        return None
    if not isinstance(payload, dict):
        return None
    if "tool_calls" in payload:
        if set(payload) != {"tool_calls"} or not isinstance(payload["tool_calls"], list):
            raise BridgeError("INVALID_TOOL_INTENT", "Tool envelope has invalid fields", 422)
        specs = payload["tool_calls"]
    elif "tool" in payload:
        if set(payload) != {"tool", "arguments"}:
            raise BridgeError("INVALID_TOOL_INTENT", "Single tool envelope must have tool and arguments", 422)
        specs = [{"name": payload["tool"], "arguments": payload["arguments"]}]
    else:
        return None
    return _validate_specs(specs, req, max_args_bytes)


def validate_native(calls: list[dict[str, Any]], req: ChatRequest, max_args_bytes: int = 256_000):
    """Native provider output must pass the SAME schema validation."""
    normalized = []
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
            raise BridgeError("INVALID_TOOL_INTENT", "Native tool call is malformed", 422)
        fn = call.get("function", {})
        args = fn.get("arguments", "")
        if not isinstance(args, str):
            raise BridgeError("INVALID_TOOL_JSON", "Native tool arguments must be JSON text", 422)
        try:
            a = strict_loads(args)
        except (ValueError, RecursionError):
            raise BridgeError("INVALID_TOOL_JSON", "Native tool arguments invalid JSON", 422) from None
        normalized.append({"name": fn.get("name"), "arguments": a})
    return _validate_specs(normalized, req, max_args_bytes)
