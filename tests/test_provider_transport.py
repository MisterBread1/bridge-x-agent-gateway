import json
import httpx
import pytest
from bridge_x.config import Settings
from bridge_x.providers import GenericOpenAIProvider, TextDelta, Finish, Failed, NativeToolDelta
from bridge_x.schemas import ChatRequest


def provider_for(monkeypatch, responder):
    real = httpx.AsyncClient
    transport = httpx.MockTransport(responder)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=transport, **{k:v for k,v in kw.items() if k != "transport"}))
    return GenericOpenAIProvider(Settings(provider="openai-compatible", generic_url="https://example.test/v1/chat/completions", generic_model="example-model"))


@pytest.mark.asyncio
async def test_stream_defers_success_until_done(monkeypatch):
    data = b'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}\n\n'
    data += b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    data += b'data: [DONE]\n\n'
    provider = provider_for(monkeypatch, lambda req: httpx.Response(200, headers={"content-type":"text/event-stream"}, content=data))
    req = ChatRequest.model_validate({"model": "example-model", "messages": [{"role": "user", "content": "hi"}]})
    results = [e async for e in provider.generate(req, [m.model_dump(exclude_none=True) for m in req.messages])]
    assert [type(e) for e in results] == [TextDelta, Finish]


@pytest.mark.asyncio
async def test_late_error_after_finish_prevents_success(monkeypatch):
    data = b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    data += b'event: error\ndata: {"error":{"code":"internal"}}\n\n'
    data += b'data: [DONE]\n\n'
    provider = provider_for(monkeypatch, lambda req: httpx.Response(200, headers={"content-type":"text/event-stream"}, content=data))
    req = ChatRequest.model_validate({"messages": [{"role": "user", "content": "hi"}]})
    results = [e async for e in provider.generate(req, [m.model_dump(exclude_none=True) for m in req.messages])]
    assert all(not isinstance(r, Finish) for r in results)
    assert isinstance(results[-1], Failed)


@pytest.mark.asyncio
async def test_missing_done_returns_incomplete(monkeypatch):
    data = b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":"stop"}]}\n\n'
    provider = provider_for(monkeypatch, lambda req: httpx.Response(200, headers={"content-type":"text/event-stream"}, content=data))
    req = ChatRequest.model_validate({"messages": [{"role": "user", "content": "hi"}]})
    results = [e async for e in provider.generate(req, [m.model_dump(exclude_none=True) for m in req.messages])]
    assert isinstance(results[-1], Failed)
    assert results[-1].code == "UPSTREAM_INCOMPLETE"


@pytest.mark.asyncio
async def test_upstream_http_500_returns_safe_error(monkeypatch):
    provider = provider_for(monkeypatch, lambda req: httpx.Response(500, content=b'{"detail":"super secret data"}'))
    req = ChatRequest.model_validate({"messages": [{"role": "user", "content": "hi"}]})
    with pytest.raises(Exception) as exc:
        [e async for e in provider.generate(req, [m.model_dump(exclude_none=True) for m in req.messages])]
    assert "secret" not in str(exc.value)
