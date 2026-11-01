"""Scripted native Molab wire fixture + real local filesystem/terminal tools.

No external network, real Molab account, or installed ZCode is used.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from bridge_x.molab_provider import MolabProvider

HTML = b'<!doctype html>\r\n<style>\r\n.panel { background: #f1f5f9; padding: 24px; }\r\n.footer { color: gray; }\r\n</style>\r\n<div class="panel">Keep unchanged</div>\r\n'


def tool(name, properties, required):
    return {"type": "function", "function": {"name": name, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}}


def main():
    original_client = httpx.AsyncClient
    steps = [("Read", {"path": "index.html"}),
             ("Edit", {"path": "index.html", "old": "#f1f5f9", "new": "#e0f2fe"}),
             ("Read", {"path": "index.html"}),
             ("Bash", {"command": "python verify_css.py"})]
    tools = [tool("Read", {"path": {"type": "string"}}, ["path"]),
             tool("Edit", {k: {"type": "string"} for k in ("path", "old", "new")}, ["path", "old", "new"]),
             tool("Bash", {"command": {"type": "string"}}, ["command"])]
    upstream_posts, results, terminal_code = [], [], None

    def upstream(request):
        if request.method == "GET":
            return httpx.Response(200, text='<div data-config=\'{"ai":{"mode":"manual"}}\'></div>')
        posted = json.loads(request.content)
        index = len(upstream_posts)
        upstream_posts.append(posted)
        assert all(t["source"] == "frontend" for t in posted["tools"])
        if index:
            outputs = [p for m in posted["messages"] for p in m["parts"] if p.get("state") == "output-available"]
            # All retained complete pairs remain native protocol data.
            assert len(outputs) == index
            assert outputs[-1]["output"]["success"] is True
        if index == len(steps):
            events = [{"type": "text-delta", "delta": "Verified"}, {"type": "finish", "finishReason": "stop"}]
        else:
            name, args = steps[index]
            cid = "fixture-call-" + str(index)
            events = [{"type": "tool-input-start", "toolCallId": cid, "toolName": name},
                      {"type": "tool-input-delta", "toolCallId": cid, "inputTextDelta": json.dumps(args)},
                      {"type": "tool-input-available", "toolCallId": cid, "toolName": name, "input": args},
                      {"type": "finish", "finishReason": "tool-calls"}]
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content="".join("data: " + json.dumps(e) + "\n\n" for e in events).encode())

    transport = httpx.MockTransport(upstream)
    with tempfile.TemporaryDirectory(prefix="bridge-css-") as temp:
        folder = Path(temp) / "project with spaces — проверка"
        folder.mkdir()
        (folder / "index.html").write_bytes(HTML)
        (folder / "neighbor.txt").write_bytes(b"unchanged\r\n")
        (folder / "verify_css.py").write_text("from pathlib import Path\ns=Path('index.html').read_bytes()\nassert b'background: #e0f2fe;' in s\nassert b'padding: 24px;' in s\nprint('CSS_OK')\n", encoding="utf-8")
        cfg = folder / "fixture.json"
        cfg.write_text(json.dumps({"chat_url": "https://fixture.sb.molab.run/api/ai/chat", "marimo_session_id": "DEMO_FIXTURE_SESSION"}), encoding="utf-8")
        settings = Settings(provider="molab", molab_tool_mode="native", verify_molab_native_mode=True,
                            molab_config_path=str(cfg), journal_path=str(folder / "state.sqlite3"))
        with patch("httpx.AsyncClient", lambda **kw: original_client(transport=transport, **kw)):
            with TestClient(create_app(settings, provider=MolabProvider(settings))) as client:
                messages = [{"role": "user", "content": "Change only the panel background; Read Edit Read Bash and verify"}]
                for index in range(5):
                    response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer molab-local"},
                                           json={"messages": messages, "tools": tools, "conversation_id": "demo-css"})
                    response.raise_for_status()
                    message = response.json()["choices"][0]["message"]
                    messages.append(message)
                    if index == 4:
                        assert not message.get("tool_calls") and message["content"] == "Verified"
                        break
                    calls = message["tool_calls"]
                    assert len(calls) == 1
                    call = calls[0]
                    name, args = call["function"]["name"], json.loads(call["function"]["arguments"])
                    assert (name, args) == steps[index]
                    if name == "Read":
                        body = (folder / "index.html").read_bytes()
                        assert body == (HTML if index == 0 else HTML.replace(b"#f1f5f9", b"#e0f2fe"))
                        result = {"success": True, "content": body.decode("utf-8")}
                    elif name == "Edit":
                        body = (folder / "index.html").read_bytes()
                        assert body.count(args["old"].encode()) == 1
                        (folder / "index.html").write_bytes(body.replace(args["old"].encode(), args["new"].encode(), 1))
                        result = {"success": True}
                    else:
                        # No arbitrary shell: execute exactly the fixture's checker.
                        run = subprocess.run([sys.executable, "verify_css.py"], cwd=folder, capture_output=True, timeout=10)
                        terminal_code = run.returncode
                        assert run.returncode == 0 and run.stdout.strip() == b"CSS_OK"
                        result = {"success": True, "exit_code": run.returncode, "stdout": "CSS_OK"}
                    results.append(name)
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
                assert client.app.state.journal.db.execute("SELECT count(*) FROM operations WHERE state IN ('DISPATCHED','PROPOSED','VALIDATED')").fetchone()[0] == 0
        exact = (folder / "index.html").read_bytes() == HTML.replace(b"#f1f5f9", b"#e0f2fe")
        neighbor = (folder / "neighbor.txt").read_bytes() == b"unchanged\r\n"
        assert exact and neighbor
    print(json.dumps({"passed": True, "kind": "scripted_local_native_wire", "real_zcode": False,
                      "live_molab": False, "tools_executed": results, "terminal_exit_code": terminal_code,
                      "exact_css_only": exact, "neighbor_unchanged": neighbor, "receipts_returned": 4,
                      "upstream_posts": len(upstream_posts), "unicode_and_spaces": True, "crlf_preserved": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
