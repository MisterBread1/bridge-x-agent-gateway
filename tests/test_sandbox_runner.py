import hashlib
import os
import pytest
from bridge_x_test_runner.runner import Sandbox, SandboxError


def test_write_edit_read_patch_and_python(tmp_path):
    s = Sandbox(tmp_path)
    receipt = s.write("agent_check.py", "print(2 + 2)\n")
    assert receipt["success"] is True
    assert s.read("agent_check.py")["content"] == "print(2 + 2)\n"
    assert s.run_python("agent_check.py").stdout.strip() == "4"
    previous_hash = s.read("agent_check.py")["sha256"]
    s.edit("agent_check.py", "2 + 2", "3 + 3", previous_hash)
    assert s.run_python("agent_check.py").stdout.strip() == "6"
    patch = "--- a/agent_check.py\n+++ b/agent_check.py\n@@ -1,1 +1,1 @@\n-print(3 + 3)\n+print(4 + 4)\n"
    s.apply_patch(patch)
    assert s.run_python("agent_check.py").stdout.strip() == "8"


def test_unicode_file_and_nested_directory(tmp_path):
    s = Sandbox(tmp_path)
    s.write("проект/тест.py", "print('Привет 🧪')\n")
    assert "Привет" in s.run_python("проект/тест.py").stdout


def test_absolute_and_parent_traversal_forbidden(tmp_path):
    s = Sandbox(tmp_path)
    for name in ("../outside.txt", "/etc/passwd", "C:\\Windows\\file.txt"):
        with pytest.raises(SandboxError):
            s.write(name, "bad")


def test_symlink_escape_forbidden(tmp_path):
    s = Sandbox(tmp_path)
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    try:
        (tmp_path / "shortcut").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("This platform doesn't permit symlinks")
    with pytest.raises(SandboxError):
        s.write("shortcut/escape.txt", "bad")


def test_file_hash_precondition_and_edit_conflict(tmp_path):
    s = Sandbox(tmp_path)
    s.write("f.txt", "before")
    with pytest.raises(SandboxError):
        s.write("f.txt", "overwrite", "wrong_hash")
    assert s.read("f.txt")["content"] == "before"
    with pytest.raises(SandboxError):
        s.edit("f.txt", "missing", "new")
    assert s.read("f.txt")["content"] == "before"


def test_patch_wrong_context_rejected(tmp_path):
    s = Sandbox(tmp_path)
    s.write("f.txt", "hello\n")
    with pytest.raises(SandboxError):
        s.apply_patch("--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-not here\n+updated\n")
    assert s.read("f.txt")["content"] == "hello\n"


def test_nonzero_exit_not_success(tmp_path):
    s = Sandbox(tmp_path)
    s.write("f.py", "raise SystemExit(7)\n")
    receipt = s.run_python("f.py")
    assert receipt.status == "failed" and receipt.exit_code == 7


def test_test_runner_is_not_shell_executor(tmp_path):
    s = Sandbox(tmp_path)
    with pytest.raises(SandboxError):
        s.run_python("fake.bat")


def test_binary_file_rejected(tmp_path):
    (tmp_path / "binary").write_bytes(b"a\x00b")
    with pytest.raises(SandboxError):
        Sandbox(tmp_path).read("binary")
