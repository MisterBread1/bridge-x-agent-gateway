"""Configure the documented marimo AI mode required by frontend tools."""
import html
from html.parser import HTMLParser
import json
from urllib.parse import urlsplit, urlunsplit
import httpx
from .errors import BridgeError


class _ModeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.mode = None

    def handle_starttag(self, tag, attrs):
        value = dict(attrs).get("data-config")
        if value is None:
            return
        try:
            config = json.loads(html.unescape(value))
        except (ValueError, TypeError):
            return
        if isinstance(config, dict) and isinstance(config.get("ai"), dict):
            self.mode = config["ai"].get("mode")


def runtime_mode_from_html(value):
    parser = _ModeParser()
    parser.feed(value)
    return parser.mode if parser.mode in ("manual", "agent", "code_mode") else None


def ensure_native_mode(config, *, configure=True):
    url = urlsplit(config.chat_url)
    root = urlunsplit((url.scheme, url.netloc, "", "", ""))
    headers = {"Marimo-Session-Id": config.session_id, "Marimo-Server-Token": config.server_token,
               **config.http_headers}
    try:
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            def read_mode():
                response = client.get(root + "/", headers=headers)
                if response.status_code == 410:
                    raise BridgeError("MOLAB_RUNTIME_GONE", "Configured Molab runtime is no longer available; restart the notebook and update local connection configuration", 410)
                response.raise_for_status()
                parser = _ModeParser()
                parser.feed(response.text)
                if parser.mode not in ("manual", "agent", "code_mode"):
                    raise BridgeError("MOLAB_NATIVE_MODE_UNKNOWN", "Cannot determine Molab AI mode safely", 503)
                return parser.mode
            old = read_mode()
            if old == "code_mode" and configure:
                response = client.post(root + "/api/kernel/save_user_config", headers=headers,
                                       json={"config": {"ai": {"mode": "manual"}}})
                response.raise_for_status()
                observed = read_mode()
                if observed != "manual":
                    raise BridgeError("MOLAB_NATIVE_MODE_REQUIRED", "Molab AI mode did not change to manual", 503)
            else:
                observed = old
            return {"old_mode": old, "mode": observed, "changed": old != observed,
                    "native_frontend_tools_configured": observed != "code_mode"}
    except httpx.HTTPError:
        raise BridgeError("MOLAB_NATIVE_SETUP_FAILED", "Could not read or configure Molab AI mode; check runtime access", 503) from None
