"""Real cmd/venv bootstrap regression; no package network or live gateway."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv
import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows batch launcher")
ROOT = Path(__file__).resolve().parents[1]


def fixture_project(tmp_path):
    folder = tmp_path / "project with spaces — запуск"
    folder.mkdir()
    for name in ("start.bat", "start-ui.bat"):
        shutil.copyfile(ROOT / name, folder / name)
    (folder / "requirements.txt").write_text("# Offline launcher fixture; no dependencies\n")
    (folder / "bridge_x").mkdir()
    (folder / "bridge_x/__init__.py").write_text("")
    (folder / "bridge_x/__main__.py").write_text(
        'import sys\nprint("LAUNCHER_ENTRY", "|".join(sys.argv[1:]))\n'
        'raise SystemExit(7 if "--fixture-error" in sys.argv else 0)\n')
    (folder / ".molab_local.json").write_bytes(b"PRIVATE_CONFIGURATION_FIXTURE")
    (folder / "bridge_x_state.sqlite3").write_bytes(b"EXISTING_JOURNAL_FIXTURE")
    return folder


def launch(folder, *arguments, extra_env=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BRIDGEX_", "PIP_")) and k not in ("PYTHONPATH", "PYTHONHOME")}
    env.update(PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONUTF8="1")
    env.update(extra_env or {})
    return subprocess.run([os.environ["COMSPEC"], "/d", "/c", *arguments], cwd=folder,
                          env=env, input="\n", capture_output=True, encoding="utf-8", errors="replace", timeout=90)


def assert_private_state_untouched(folder):
    assert (folder / ".molab_local.json").read_bytes() == b"PRIVATE_CONFIGURATION_FIXTURE"
    assert (folder / "bridge_x_state.sqlite3").read_bytes() == b"EXISTING_JOURNAL_FIXTURE"


@pytest.mark.parametrize("exit_code", [0, 7])
def test_existing_python_without_pip_is_repaired_and_arguments_exit_status_preserved(tmp_path, exit_code):
    folder = fixture_project(tmp_path)
    venv.create(folder / ".venv", with_pip=False)
    python = folder / ".venv/Scripts/python.exe"
    before = subprocess.run([str(python), "-m", "pip", "--version"], capture_output=True)
    assert before.returncode != 0  # Reproduce the user's actual missing-pip condition.
    args = ["start-ui.bat", "--fixture-error"] if exit_code else ["start.bat", "--fixture-ok"]
    result = launch(folder, *args)
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert "Restoring missing pip" in result.stdout
    assert "LAUNCHER_ENTRY" in result.stdout
    if exit_code:
        assert "--desktop|--fixture-error" in result.stdout
    assert subprocess.run([str(python), "-m", "pip", "--version"], capture_output=True).returncode == 0
    assert_private_state_untouched(folder)


def test_first_start_creates_environment_and_bootstraps_pip_offline(tmp_path):
    folder = fixture_project(tmp_path)
    result = launch(folder, "start.bat", "--fixture-ok")
    assert result.returncode == 0 and "LAUNCHER_ENTRY --fixture-ok" in result.stdout, result.stdout + result.stderr
    assert (folder / ".venv/Scripts/python.exe").is_file()
    assert_private_state_untouched(folder)


def test_unavailable_ensurepip_reports_pip_problem_without_claiming_python_is_missing(tmp_path):
    folder = fixture_project(tmp_path)
    venv.create(folder / ".venv", with_pip=False)
    # Fault injection shadows only ensurepip in this disposable fixture.
    (folder / "ensurepip.py").write_text('raise SystemExit(3)\n')
    result = launch(folder, "start.bat")
    assert result.returncode == 1
    assert "PIP_BOOTSTRAP_FAILED: Python runs" in result.stdout
    assert "Install Python 3.11 or newer" not in result.stdout
    assert "LAUNCHER_ENTRY" not in result.stdout
    assert_private_state_untouched(folder)


def test_copy_key_launcher_needs_no_pip_and_preserves_helper_failure(tmp_path):
    folder = fixture_project(tmp_path)
    shutil.copyfile(ROOT / "copy-key.bat", folder / "copy-key.bat")
    venv.create(folder / ".venv", with_pip=False)
    (folder / "tools").mkdir()
    (folder / "tools/__init__.py").write_text("")
    (folder / "tools/copy_key.py").write_text('print("COPY_KEY_FIXTURE"); raise SystemExit(7)\n')
    result = launch(folder, "copy-key.bat")
    assert result.returncode == 7 and "COPY_KEY_FIXTURE" in result.stdout
    assert subprocess.run([str(folder / ".venv/Scripts/python.exe"), "-m", "pip", "--version"], capture_output=True).returncode != 0
    assert_private_state_untouched(folder)


def test_default_start_uses_native_pythonw_entry_without_browser_or_console(tmp_path):
    folder = fixture_project(tmp_path)
    venv.create(folder / ".venv", with_pip=False)
    (folder / "bridge_x/__main__.py").write_text('import json,sys\nfrom pathlib import Path\nPath("desktop-start.json").write_text(json.dumps(sys.argv[1:]))\n')
    result = launch(folder, "start.bat", extra_env={"BRIDGEX_PROVIDER": "fake"})
    assert result.returncode == 0, result.stdout + result.stderr
    import json, time
    deadline = time.monotonic() + 10
    while not (folder / "desktop-start.json").exists() and time.monotonic() < deadline:
        time.sleep(.02)
    assert json.loads((folder / "desktop-start.json").read_text()) == ["--desktop", "--provider", "molab"]
    assert_private_state_untouched(folder)
