"""Incremental SSE framing: UTF-8, CR/LF, comments, multiline data, size caps."""
from dataclasses import dataclass
import codecs
from .errors import BridgeError


@dataclass(frozen=True)
class SSEEvent:
    event: str
    data: str
    id: str | None = None


class SSEParser:
    def __init__(self, max_event_chars: int = 2_000_000):
        self.decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self.at_start = True  # UTF-8 BOM is permitted only at stream start.
        self.line = ""
        self.pending_cr = False
        self.data = []
        self.event = "message"
        self.id = None
        self.max_event_chars = max_event_chars
        self.event_chars = 0

    def _dispatch(self):
        if not self.data:
            self.event = "message"
            return []
        result = SSEEvent(self.event, "\n".join(self.data), self.id)
        self.data = []
        self.event = "message"
        self.event_chars = 0
        return [result]

    def _line(self, value):
        if value == "":
            return self._dispatch()
        if value.startswith(":"):
            return []
        field, sep, contents = value.partition(":")
        if sep and contents.startswith(" "):
            contents = contents[1:]
        if field == "data":
            self.data.append(contents)
            # Each data line adds a separator even when its content is empty.
            self.event_chars += len(contents) + 1
            if self.event_chars > self.max_event_chars:
                raise BridgeError("SSE_EVENT_TOO_LARGE", "Upstream SSE event is too large", 502)
        elif field == "event":
            self.event = contents
        elif field == "id" and "\x00" not in contents:
            self.id = contents
        return []

    def feed(self, chunk: bytes):
        try:
            text = self.decoder.decode(chunk)
        except UnicodeDecodeError:
            raise BridgeError("SSE_INVALID_UTF8", "Upstream SSE was not valid UTF-8", 502) from None
        if self.at_start and text:
            self.at_start = False
            if text.startswith("\ufeff"):
                text = text[1:]
        results = []
        for c in text:
            if self.pending_cr:
                self.pending_cr = False
                if c == "\n":
                    continue
            if c in "\r\n":
                results.extend(self._line(self.line))
                self.line = ""
                self.pending_cr = c == "\r"
            else:
                self.line += c
                if len(self.line) > self.max_event_chars:
                    raise BridgeError("SSE_LINE_TOO_LARGE", "Upstream SSE line too large", 502)
        return results

    def finish(self):
        """EOF is NOT a dispatch delimiter. Discard an unterminated SSE event.

        Per the HTML Living Standard an event is delivered only after a blank
        line. Without this rule a truncated `finish` could falsely authorize a
        half-generated Write or Bash command.
        """
        try:
            self.decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            raise BridgeError("SSE_INVALID_UTF8", "Truncated UTF-8 at end of stream", 502) from None
        self.line = ""
        self.data = []
        self.event = "message"
        self.event_chars = 0
        return []


def sse_data(payload: dict) -> str:
    import json
    return "data: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n\n"


def sse_error(payload: dict) -> str:
    import json
    return "event: error\ndata: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n\n"
