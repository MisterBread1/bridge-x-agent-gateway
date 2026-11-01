"""The shipped UI has complete labels and preserves form controls in both languages."""
import json
from html.parser import HTMLParser
from pathlib import Path
import re
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from bridge_x.observability import EVENTS, OUTCOMES
from bridge_x.tool_models import OperationState

ASSETS = Path(__file__).resolve().parents[1] / "bridge_x/ui"


def catalog():
    source = (ASSETS / "locales.js").read_text(encoding="utf-8")
    return json.loads(source.removeprefix("window.BridgeTranslations = ").strip().removesuffix(";"))


def test_translation_catalog_covers_every_static_label_state_outcome_and_event():
    translations = catalog()
    assert set(translations) == {"en", "ru"}
    assert set(translations["en"]) == set(translations["ru"])
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    keys = set(re.findall(r'data-i18n(?:-aria|-placeholder)?="([^"]+)"', html))
    keys |= {"state_" + state.value for state in OperationState}
    keys |= {"outcome_" + outcome for outcome in OUTCOMES}
    keys |= {"event_" + event for event in EVENTS}
    for language, messages in translations.items():
        assert keys <= messages.keys(), (language, keys - messages.keys())
        assert all(isinstance(value, str) and value.strip() for value in messages.values())
    for key in translations["en"]:
        assert set(re.findall(r'\{([a-z]+)\}', translations["en"][key])) == set(re.findall(r'\{([a-z]+)\}', translations["ru"][key])), key
    assert translations["en"]["session"] == "Session" and translations["ru"]["session"] == "Сеанс"


def test_translated_elements_do_not_contain_editable_controls_and_assets_load_in_order():
    class Document(HTMLParser):
        def __init__(self):
            super().__init__(); self.stack = []; self.scripts = []; self.controls = set()
        def handle_starttag(self, tag, attrs):
            assert len({key for key, _ in attrs}) == len(attrs), (tag, attrs)
            attributes = dict(attrs)
            if tag in {"input", "select", "textarea"}:
                assert not any("data-i18n" in ancestor for ancestor in self.stack)
                self.controls.add(attributes.get("id"))
            if tag == "script": self.scripts.append(attributes.get("src"))
            if tag not in {"input", "meta", "link", "br", "hr", "img"}: self.stack.append(attributes)
        def handle_endtag(self, tag):
            if self.stack: self.stack.pop()
    document = Document(); document.feed((ASSETS / "index.html").read_text(encoding="utf-8"))
    assert {"key", "key-file", "runtime-url", "session-id", "server-token", "expected", "observed", "stopped", "language"} <= document.controls
    assert document.scripts.index("/ui/assets/locales.js") < document.scripts.index("/ui/assets/app.js")


def test_translation_catalog_is_served_without_auth_and_has_no_private_config():
    with TestClient(create_app(Settings(journal_path=":memory:")), base_url="http://127.0.0.1") as client:
        response = client.get("/ui/assets/locales.js")
        assert response.status_code == 200 and "BridgeTranslations" in response.text
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
        assert "BRIDGEX_LOCAL_KEY" in response.text  # Instructions only, never a key value.
        assert client.get("/ui/api/snapshot").status_code == 401
