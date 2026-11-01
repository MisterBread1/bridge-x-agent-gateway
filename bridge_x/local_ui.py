"""Authenticated loopback UI. No client tool executor and no secret URL bootstrap."""
import asyncio
import hmac
import json
import os
from pathlib import Path
import tempfile
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from . import __version__
from .errors import BridgeError
from .observability import safe_request

ASSETS = Path(__file__).parent / "ui"


def install_ui(app, settings, provider, storage):
    runtime_lock = asyncio.Lock()
    def authorize(request):
        host = request.url.hostname
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise BridgeError("UI_HOST_REJECTED", "Open the interface through its loopback address", 403)
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            raise BridgeError("UI_ORIGIN_REJECTED", "Cross-origin UI requests are disabled", 403)
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:].encode(), settings.local_api_key.encode()):
            raise BridgeError("LOCAL_AUTH", "Enter the local Bridge X key", 401)

    @app.middleware("http")
    async def ui_security(request, call_next):
        if request.url.path.startswith("/ui/"):
            if request.url.hostname not in ("127.0.0.1", "localhost", "::1"):
                return JSONResponse({"error": {"code": "UI_HOST_REJECTED"}}, status_code=403)
            if request.method not in ("GET", "HEAD"):
                origin = request.headers.get("origin")
                if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
                    return JSONResponse({"error": {"code": "UI_ORIGIN_REJECTED"}}, status_code=403)
            response = await call_next(request)
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        return await call_next(request)

    app.mount("/ui/assets", StaticFiles(directory=ASSETS), name="ui-assets")

    @app.get("/ui/", include_in_schema=False)
    async def ui_page():
        return FileResponse(ASSETS / "index.html")

    def read_snapshot(before):
        journal = storage.journal
        with journal.lock:
            rows = journal.db.execute("""SELECT rowid,call_id,name,state,result_kind,created_at,conversation_id,execution_scope
                FROM operations WHERE rowid<? ORDER BY rowid DESC LIMIT 50""", (before,)).fetchall()
            keys = ("cursor", "id", "name", "status", "result_kind", "created_at", "session", "scope")
            operations = [dict(zip(keys, row)) for row in rows]
            for operation in operations:
                operation["session"] = safe_request(operation["session"]) if operation["session"] else None
                operation["scope"] = "main_turn" if operation["scope"] == "main_turn" else "background"
            pending = journal.db.execute("SELECT count(*) FROM operations WHERE state IN ('DISPATCHED','EXECUTION_UNKNOWN','CANCELLED','TIMED_OUT') OR (state='ACKNOWLEDGED' AND result_kind='unknown')").fetchone()[0]
            mode = journal.db.execute("PRAGMA journal_mode").fetchone()[0]
            return {"operations": operations, "next_cursor": rows[-1][0] if len(rows) == 50 else None,
                    "unresolved": pending, "journal_mode": mode, "events": journal.safe_report()}

    @app.get("/ui/api/snapshot")
    async def snapshot(request: Request, before: int = 9_223_372_036_854_775_807):
        authorize(request)
        if not 1 <= before <= 9_223_372_036_854_775_807:
            raise BridgeError("INVALID_REQUEST", "Invalid history cursor", 400)
        data = await storage.call(read_snapshot, before)
        connection = provider.connection_status() if hasattr(provider, "connection_status") else {"verified": False}
        return {"version": __version__, "provider": settings.provider, "connection": connection,
                "rate_control": provider.rate_status() if hasattr(provider, "rate_status") else {"enabled": False},
                **data}

    @app.get("/ui/api/config")
    async def ui_config(request: Request):
        authorize(request)
        return {"provider": settings.provider, "mode": settings.molab_tool_mode,
                "config_present": Path(settings.molab_config_path).is_file(),
                "base_url": str(request.base_url).rstrip("/") + "/v1", "model": "molab-glm",
                "editable": settings.local_api_key != "molab-local"}

    async def body(request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65_536:
                raise BridgeError("REQUEST_TOO_LARGE", "UI request exceeds its limit", 413)
        from .json_utils import loads, valid_value
        try:
            value = loads(bytes(raw))
        except (ValueError, UnicodeError, RecursionError):
            raise BridgeError("INVALID_REQUEST", "Invalid UI JSON", 400) from None
        if not isinstance(value, dict) or not valid_value(value):
            raise BridgeError("INVALID_REQUEST", "Expected a bounded UI JSON object", 400)
        return value

    @app.post("/ui/api/config")
    async def save_config(request: Request):
        authorize(request)
        if settings.local_api_key == "molab-local":
            raise BridgeError("UI_PERSONAL_KEY_REQUIRED", "Start with --ui to create a personal key before changing configuration", 403)
        value = await body(request)
        allowed = {"chat_url", "marimo_session_id", "marimo_server_token", "http_headers", "notebook_url"}
        if not set(value) <= allowed:
            raise BridgeError("INVALID_REQUEST", "Unknown configuration field", 400)
        from .molab_provider import validate_molab_config
        config = validate_molab_config(value)
        if any("YOUR_" in field for field in (config.chat_url, config.session_id, config.server_token)):
            raise BridgeError("MOLAB_CONFIG_PLACEHOLDER", "Replace the template values locally", 400)
        def write():
            target = Path(settings.molab_config_path)
            if target.is_symlink():
                raise BridgeError("MOLAB_CONFIG_INVALID", "Configuration must be a regular local file", 400)
            target.parent.mkdir(parents=True, exist_ok=True)
            filename = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as output:
                    filename = output.name
                    json.dump(value, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(filename, target)
            except OSError:
                raise BridgeError("MOLAB_CONFIG_INVALID", "Cannot save configuration; check directory permissions", 503) from None
            finally:
                if filename is not None and Path(filename).exists():
                    Path(filename).unlink()
        await asyncio.to_thread(write)
        if hasattr(provider, "live_verified"):
            provider.live_verified = False
            provider.last_success_at = None
        # Private input is never reflected into JSON, diagnostics or URLs.
        return {"saved": True, "provider_restart_required": settings.provider != "molab"}

    @app.post("/ui/api/check-runtime")
    async def check_runtime(request: Request):
        authorize(request)
        value = await body(request)
        if set(value) - {"configure"} or type(value.get("configure", False)) is not bool:
            raise BridgeError("INVALID_REQUEST", "Expected an explicit configure boolean", 400)
        def check():
            from .molab_provider import read_molab_config
            from .molab_runtime import ensure_native_mode
            return ensure_native_mode(read_molab_config(settings.molab_config_path), configure=value.get("configure", False))
        if runtime_lock.locked():
            raise BridgeError("UI_CHECK_BUSY", "A runtime check is already in progress", 429)
        async with runtime_lock:
            result = await asyncio.to_thread(check)
        return {"mode": result["mode"], "changed": result["changed"], "runtime_access_checked": True, "model_generation_checked": False}

    @app.post("/ui/api/verify/{call_id}")
    async def verify(request: Request, call_id: str):
        authorize(request)
        from .schemas import OperationVerification
        from pydantic import ValidationError
        try:
            verification = OperationVerification.model_validate(await body(request))
        except ValidationError:
            raise BridgeError("INVALID_REQUEST", "Provide matching SHA-256 checks and confirm execution has stopped", 400) from None
        return await storage.call("verify", call_id, verification.conversation_id,
                                  verification.expected_sha256, verification.observed_sha256, verification.execution_stopped)
