"""Command Frame v2: bounded, end-delimited plain text tool arguments.

No per-field closing tags: the *next* field heading closes the prior field.
The final @@END_CALL is mandatory. This is not an executable interpreter;
strict JSON Schema validation is applied by tools.parse_intent afterwards.

Format::
    @@CALL_V2 Write
    @@FIELD path
    example.py
    @@FIELD content
    print(2 + 2)
    @@END_CALL

For JSON-typed arguments replace @@FIELD with @@JSON. A literal line that
would be recognized as a protocol header must be escaped with a backslash.
Incomplete frames never become calls; no implicit EOF closure exists.
"""
from __future__ import annotations
import json
import re
from typing import Any

from .errors import BridgeError
from .json_utils import loads as strict_loads

_START = re.compile(r"@@CALL_V2[ \t]+([A-Za-z][A-Za-z0-9_.-]{0,127})[ \t]*\Z")
_FIELD = re.compile(r"@@(FIELD|JSON)[ \t]+([A-Za-z][A-Za-z0-9_.-]{0,127})[ \t]*\Z")
_END = re.compile(r"@@END_CALL[ \t]*\Z")


def _strict_constant(_):
    raise ValueError("non-finite JSON constant")


def protocol_lines(text: str) -> list[str]:
    """Only CR/LF delimit protocol lines; Unicode separators are file data."""
    return re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", text)[:-1]


def parse_frame_v2(text: str, max_args_bytes: int = 256_000) -> tuple[str, dict[str, Any]]:
    """Extract a single complete frame, never guess the missing end marker.

    A frame without its final terminator is invalid, even if every required
    field is present. Literal control-looking lines must be escaped. This is
    deliberately fail-closed; commands can have side effects once ZCode runs.
    """
    if len(text.encode("utf-8")) > max_args_bytes * 2:
        raise BridgeError("TOOL_FRAME_TOO_LARGE", "Tool frame exceeds size limit", 422)
    lines = protocol_lines(text)
    if not lines:
        raise BridgeError("INVALID_TOOL_FRAME", "Empty tool frame", 422)

    def control(line: str) -> str:
        return line.rstrip("\r\n")

    start = _START.fullmatch(control(lines[0]))
    if not start:
        raise BridgeError("INVALID_TOOL_FRAME", "Tool frame must begin with a command", 422)
    name = start.group(1)
    fields = {}
    current = None  # tuple: (kind, field, chunks)
    finished = False

    def flush():
        nonlocal current
        if current is None:
            return
        kind, key, chunks = current
        value = "".join(chunks)
        # Only drop the structural newline immediately before the next header.
        # Keep the rest verbatim (including Windows CRLF in file contents).
        if value.endswith("\r\n"):
            value = value[:-2]
        elif value.endswith(("\r", "\n")):
            value = value[:-1]
        if kind == "JSON":
            try:
                value = strict_loads(value)
            except (ValueError, RecursionError):
                raise BridgeError("INVALID_TOOL_VALUE", "Typed field is not valid JSON", 422) from None
        fields[key] = value
        current = None

    for index, line in enumerate(lines[1:], start=1):
        raw = control(line)
        # A leading backslash escapes *only* a real control line. Do not alter
        # arbitrary backslashes in Windows paths, regular expressions or HTML.
        if current is not None and raw.startswith("\\@@") and (
            _END.fullmatch(raw[1:]) or _FIELD.fullmatch(raw[1:])
        ):
            current[2].append(line[1:])
            continue
        if _END.fullmatch(raw):
            flush()
            if any(part.strip() for part in lines[index + 1:]):
                raise BridgeError("INVALID_TOOL_FRAME", "Unexpected text after command", 422)
            finished = True
            break
        header = _FIELD.fullmatch(raw)
        if header:
            flush()
            kind, key = header.groups()
            if key in fields or len(fields) >= 32:
                raise BridgeError("INVALID_TOOL_FRAME", "Duplicate or too many command fields", 422)
            current = (kind, key, [])
            continue
        if current is None:
            raise BridgeError("INVALID_TOOL_FRAME", "Expected a field or command terminator", 422)
        current[2].append(line)

    if not finished:
        raise BridgeError("INVALID_TOOL_FRAME", "Tool frame missing final @@END_CALL", 422)
    return name, fields
