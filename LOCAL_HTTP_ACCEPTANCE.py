"""Start the actual gateway on a temporary loopback port and check HTTP/SSE.

Default: offline simulator. --live explicitly sends one text-only Molab call.
Does not interact with a process already running on port 8787.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import threading
import sqlite3
from contextlib import closing
import httpx
from bridge_x import __version__
from bridge_x.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--report", default="local_http_acceptance_result.json")
    parser.add_argument("--serve", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--inject-initial-rate-limit", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve is not None:
        if args.inject_initial_rate_limit:
            # Test-process fault injection only: the first model POST never
            # reaches Molab. Later requests use the real configured upstream.
            original_client = httpx.AsyncClient
            injected = False

            class InitialRateTransport(httpx.AsyncBaseTransport):
                def __init__(self):
                    self.real = httpx.AsyncHTTPTransport(retries=0)

                async def handle_async_request(self, request):
                    nonlocal injected
                    if request.method == "POST" and request.url.path == "/api/ai/chat" and not injected:
                        injected = True
                        return httpx.Response(429, json={"error": {"code": "rate_limit", "message": "Synthetic acceptance rejection"}})
                    return await self.real.handle_async_request(request)

                async def aclose(self):
                    await self.real.aclose()

            def injected_client(**kwargs):
                kwargs["transport"] = InitialRateTransport()
                return original_client(**kwargs)

            httpx.AsyncClient = injected_client
        import uvicorn
        server = uvicorn.Server(uvicorn.Config("bridge_x.gateway:create_app", factory=True,
                                               host="127.0.0.1", port=args.serve, log_level="warning"))
        def stop_on_parent_input():
            # A private pipe, not a remotely accessible shutdown API.
            sys.stdin.readline()
            server.should_exit = True
        threading.Thread(target=stop_on_parent_input, daemon=True).start()
        server.run()
        return 0
    provider = "molab" if args.live else "fake"
    report = {"version": __version__, "provider": provider, "real_http_server": True, "passed": False}
    with tempfile.TemporaryDirectory(prefix="bridge-x-http-") as folder:
        env = os.environ.copy()
        env.update(BRIDGEX_PROVIDER=provider, BRIDGEX_JOURNAL_PATH=str(Path(folder) / "http.sqlite3"))
        key = Settings.from_env().local_api_key
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", str(port)],
                                   cwd=Path(__file__).resolve().parent, env=env,
                                   stdin=subprocess.PIPE, text=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=100, trust_env=False) as client:
                deadline = time.monotonic() + 12
                while True:
                    try:
                        health = client.get("/health", timeout=0.5)
                        break
                    except httpx.TransportError:
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("Server did not start") from None
                        time.sleep(0.1)
                assert health.json()["version"] == __version__
                assert health.json()["provider"] == provider
                auth = {"Authorization": "Bearer " + key}
                assert client.get("/v1/models", headers=auth).status_code == 200
                assert client.get("/diagnostics").status_code == 401
                response = client.post("/v1/chat/completions", headers=auth, json={"model": "molab-glm" if args.live else "bridge-x-fake",
                    "messages": [{"role": "user", "content": "Reply with one short word: OK"}], "stream": True})
                report["http_status"] = response.status_code
                report["sse_done"] = "data: [DONE]" in response.text
                report["sse_error"] = "event: error" in response.text
                report["passed"] = response.status_code == 200 and report["sse_done"] and not report["sse_error"]
        except Exception as exc:
            report["exception_type"] = type(exc).__name__
        finally:
            report["forced_shutdown"] = False
            if process.poll() is None:
                try:
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                    process.stdin.close()
                    process.wait(timeout=8)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    pass
            if os.name == "nt" and process.poll() is None:
                report["forced_shutdown"] = True
                # A Windows venv executable can be a redirector with a child
                # interpreter. Terminating only the redirector leaves the
                # server alive and its temporary SQLite file locked.
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=8, check=False)
            elif process.poll() is None:
                report["forced_shutdown"] = True
                process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                report["forced_shutdown"] = True
                process.kill()
                process.wait(timeout=8)
            report["server_exit_code"] = process.returncode
            report["graceful_shutdown"] = process.returncode == 0 and not report["forced_shutdown"]
            with closing(sqlite3.connect(Path(folder) / "http.sqlite3")) as database:
                report["sqlite_reopen_ok"] = database.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            report["passed"] = report["passed"] and report["graceful_shutdown"] and report["sqlite_reopen_ok"]
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
