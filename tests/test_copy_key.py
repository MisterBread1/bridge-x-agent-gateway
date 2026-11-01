"""Clipboard actions are operator-invoked; tests never touch the real clipboard."""
import subprocess
from types import SimpleNamespace
from tools import copy_key


def test_copy_uses_system_clipboard_without_printing_or_logging_the_key(monkeypatch, capsys):
    private = "LOCAL_KEY_FIXTURE_DO_NOT_PRINT_123456"
    called = []
    monkeypatch.setattr(copy_key, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(copy_key, "personal_key", lambda: private)
    monkeypatch.setattr(copy_key.subprocess, "run", lambda *args, **kwargs: called.append((args, kwargs)))
    assert copy_key.main() == 0
    assert private not in capsys.readouterr().out
    assert called[0][0][0][0].endswith("System32\\clip.exe") or called[0][0][0][0].endswith("System32/clip.exe")
    assert called[0][1]["input"].decode("utf-16") == private
    assert called[0][1]["timeout"] == 5


def test_clipboard_failure_does_not_echo_the_key(monkeypatch, capsys):
    private = "LOCAL_KEY_FIXTURE_DO_NOT_PRINT_123456"
    monkeypatch.setattr(copy_key, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(copy_key, "personal_key", lambda: private)
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("clip", 5)
    monkeypatch.setattr(copy_key.subprocess, "run", fail)
    assert copy_key.main() == 2
    output = capsys.readouterr().out
    assert "CLIPBOARD_UNAVAILABLE" in output and private not in output
