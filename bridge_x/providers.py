"""Provider-independent output events and two supported adapters.

The generic adapter requires an operator-supplied, documented HTTPS API.
No browser cookies/session scraping or undocumented Molab AI endpoint included.
"""
from dataclasses import dataclass
from typing import Any
import asyncio
import json
import httpx
from .errors import BridgeError, UpstreamError
from .sse import SSEParser
from .json_utils import loads as strict_loads, valid_value


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class NativeToolDelta:
    index: int
    id: str | None
    name: str | None
    arguments: str


@dataclass(frozen=True)
class Finish:
    reason: str


@dataclass(frozen=True)
class Failed:
    code: str
    message: str
    # Optional metrics are restricted to non-sensitive scalar metadata.
    diagnostics: dict | None = None
    retry_after_s: float | None = None
    safe_to_retry: bool = False


@dataclass(frozen=True)
class RateLimitWait:
    """Explicit pre-output rejection; recorded while the same client turn waits."""
    code: str
    diagnostics: dict | None = None


@dataclass(frozen=True)
class ContextRecovery:
    """One pre-output context rejection; complete old exchanges were archived."""
    before_chars: int
    after_chars: int


@dataclass(frozen=True)
class Done:
    """Provider SSE end marker, not evidence of success without finish_reason."""


def _extract_error_kind(value: Any) -> str:
    """Recognize conservative classifications without exposing upstream payload."""
    try:
        text = json.dumps(value, ensure_ascii=False).lower()[:4096]
    except (TypeError, ValueError):
        return "UPSTREAM_SSE_ERROR"
    if "context" in text or "token limit" in text or "maximum tokens" in text:
        return "UPSTREAM_CONTEXT_LIMIT"
    if "rate_limit" in text or "rate limit" in text or "quota" in text:
        return "UPSTREAM_RATE_LIMIT"
    if "overloaded" in text or "capacity" in text or "busy" in text:
        return "UPSTREAM_OVERLOADED"
    return "UPSTREAM_SSE_ERROR"


class FakeProvider:
    """Deterministic offline-only agent simulator: tools are executed by client."""
    async def generate(self, req, messages):
        await asyncio.sleep(0)
        user_text = next((str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"), "")
        results = [m for m in messages if m.get("role") == "tool"]
        if "__test_sse_error__" in user_text:
            yield TextDelta("Partial synthetic response")
            yield Failed("UPSTREAM_SSE_ERROR", "Synthetic terminal SSE error")
            return
        if "agent_check.py" in user_text and req.tools and req.tool_choice != "none":
            names = [tool.function["name"] for tool in req.tools]
            if not results:
                name = "Write" if "Write" in names else names[0]
                proposal = {"tool_calls": [{"name": name, "arguments": {"path": "agent_check.py", "content": "print(2 + 2)\n"}}]}
            elif len(results) == 1:
                name = "Bash" if "Bash" in names else names[-1]
                proposal = {"tool_calls": [{"name": name, "arguments": {"command": "python agent_check.py"}}]}
            else:
                for ch in ["Результат", " выполнения", " проверен", "."]:
                    yield TextDelta(ch)
                yield Finish("stop")
                return
            text = json.dumps(proposal, ensure_ascii=False)
            for n in range(0, len(text), 17):
                yield TextDelta(text[n:n + 17])
            yield Finish("stop")
            return
        for chunk in ["Bridge X fake provider: ", "запрос обработан офлайн."]:
            yield TextDelta(chunk)
        yield Finish("stop")


class GenericOpenAIProvider:
    """OpenAI-compatible streaming adapter for explicitly authorized HTTPS endpoints."""
    def __init__(self, settings):
        self.settings = settings

    async def generate(self, req, messages):
        payload = {
            "model": self.settings.generic_model or req.model,
            "messages": messages,
            "stream": True,
        }
        if req.tools:
            payload["tools"] = [t.model_dump(exclude_none=True) for t in req.tools]
            payload["tool_choice"] = req.tool_choice
            payload["parallel_tool_calls"] = req.parallel_tool_calls
        headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
        if self.settings.generic_api_key:
            headers["Authorization"] = "Bearer " + self.settings.generic_api_key
        timeout = httpx.Timeout(connect=15, read=self.settings.timeout_s, write=30, pool=10)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                async with client.stream("POST", self.settings.generic_url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        status = response.status_code
                        if status in (401, 403):
                            raise UpstreamError("UPSTREAM_ACCESS_DENIED", "Provider did not authorize the request", 502)
                        if status == 429:
                            raise UpstreamError("UPSTREAM_RATE_LIMIT", "Provider rate limit", 503, True)
                        raise UpstreamError("UPSTREAM_HTTP_ERROR", f"Provider returned HTTP {status}", 502, status >= 500)
                    if "text/event-stream" not in response.headers.get("content-type", "").lower():
                        raise UpstreamError("UPSTREAM_BAD_CONTENT_TYPE", "Provider did not return SSE", 502)
                    parser = SSEParser(max_event_chars=self.settings.max_output_chars * 2)
                    pending_finish = None
                    done_seen = False
                    failed = False
                    total_bytes = 0
                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > self.settings.max_molab_response_bytes:
                            raise UpstreamError("UPSTREAM_RESPONSE_TOO_LARGE", "Provider SSE exceeded response size limit", 502)
                        for event in parser.feed(chunk):
                            for result in self._decode(event):
                                if isinstance(result, Failed):
                                    failed = True
                                    yield result
                                    return
                                if isinstance(result, Finish):
                                    if pending_finish is not None or done_seen:
                                        yield Failed("UPSTREAM_DUPLICATE_FINISH", "Provider returned an unexpected terminal event")
                                        return
                                    pending_finish = result
                                elif isinstance(result, Done):
                                    if done_seen or pending_finish is None:
                                        yield Failed("UPSTREAM_INCOMPLETE", "Provider returned DONE without a unique finish")
                                        return
                                    done_seen = True
                                else:
                                    if pending_finish is not None or done_seen:
                                        yield Failed("UPSTREAM_AFTER_FINISH", "Provider sent content after finish")
                                        return
                                    yield result
                    parser.finish()  # Check UTF-8; incomplete SSE events are discarded.
                    # A finish_reason alone is not enough: a later SSE error or
                    # truncated connection must not produce successful tool calls.
                    if done_seen and pending_finish and not failed:
                        yield pending_finish
                    else:
                        yield Failed("UPSTREAM_INCOMPLETE", "Provider stream ended without complete terminal SSE")
        except httpx.TransportError as exc:
            raise UpstreamError("UPSTREAM_TRANSPORT_ERROR", "Provider transport failed or timed out", 502, True) from exc

    @staticmethod
    def _decode(event):
        data = event.data
        if event.event == "error":
            try:
                shape = json.loads(data)
            except (ValueError, TypeError):
                shape = {}
            return [Failed(_extract_error_kind(shape), "Provider emitted SSE error event")]
        if data.strip() == "[DONE]":
            # DONE alone is not evidence of successful finish_reason.
            return [Done()]
        try:
            parsed = strict_loads(data)
        except (ValueError, RecursionError):
            return [Failed("UPSTREAM_INVALID_SSE_JSON", "Provider sent malformed SSE JSON")]
        if not valid_value(parsed):
            return [Failed("UPSTREAM_INVALID_SSE_JSON", "Provider sent invalid JSON values")]
        if isinstance(parsed, dict) and parsed.get("error"):
            return [Failed(_extract_error_kind(parsed["error"]), "Provider reported error")]
        if isinstance(parsed, dict) and parsed.get("finish_reason") in ("error", "failed"):
            return [Failed(_extract_error_kind(parsed), "Provider reported terminal error")]
        if not isinstance(parsed, dict):
            return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Provider returned a non-object SSE payload")]
        choices = parsed.get("choices", [])
        if not isinstance(choices, list):
            return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Provider returned malformed choices")]
        if len(choices) > 1:
            return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Multiple completion choices are not supported")]
        results = []
        for choice in choices:
            if not isinstance(choice, dict):
                return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Provider returned malformed choice")]
            if choice.get("index", 0) != 0:
                return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Provider returned an unexpected choice index")]
            delta = choice.get("delta")
            if delta is None:
                delta = {}
            if not isinstance(delta, dict):
                return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Provider returned malformed delta")]
            content = delta.get("content")
            if content is not None and not isinstance(content, str):
                return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Provider returned malformed text delta")]
            if content:
                results.append(TextDelta(content))
            calls = delta.get("tool_calls")
            if calls is None:
                calls = []
            if not isinstance(calls, list):
                return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Provider returned malformed tool delta")]
            for call in calls:
                if not isinstance(call, dict):
                    return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Provider returned malformed tool call")]
                fn = call.get("function")
                if fn is None:
                    fn = {}
                index = call.get("index", 0)
                if not isinstance(fn, dict) or type(index) is not int or not 0 <= index < 16:
                    return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Provider returned malformed tool parameters")]
                args = fn.get("arguments", "")
                if (not isinstance(args, str) or any(v is not None and not isinstance(v, str)
                                                    for v in (call.get("id"), fn.get("name")))):
                    return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Provider returned malformed tool arguments")]
                results.append(NativeToolDelta(index, call.get("id"), fn.get("name"), args))
            reason = choice.get("finish_reason")
            if reason:
                if reason in ("error", "failed"):
                    return [Failed(_extract_error_kind(choice), "Provider finish_reason=error")]
                if not isinstance(reason, str):
                    return [Failed("UPSTREAM_INVALID_SSE_EVENT", "Provider returned invalid finish reason")]
                results.append(Finish(reason))
        return results


def make_provider(settings):
    if settings.provider == "fake":
        return FakeProvider()
    if settings.provider == "molab":
        from .molab_provider import MolabProvider
        return MolabProvider(settings)
    return GenericOpenAIProvider(settings)
