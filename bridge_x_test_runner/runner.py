"""TEST-ONLY isolated filesystem & Python runner.

NOT imported by bridge_x.gateway. Never pointed at a user workspace.
It deliberately does not expose arbitrary shell execution.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import tempfile


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunReceipt:
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class Sandbox:
    def __init__(self, root: Path):
        root = Path(root)
        if not root.is_dir() or root.is_symlink():
            raise SandboxError("Sandbox root must be an existing, real directory")
        self.root = root.resolve(strict=True)

    def locate(self, rel: str) -> Path:
        if not isinstance(rel, str) or not rel or "\x00" in rel:
            raise SandboxError("Invalid relative path")
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts or (len(rel) > 1 and rel[1] == ":"):
            raise SandboxError("Absolute, drive and traversal paths are forbidden")
        # Reject symlinks at every parent component, including broken links.
        current = self.root
        for component in path.parts:
            current = current / component
            if current.is_symlink():
                raise SandboxError("Symlinks are forbidden in sandbox paths")
        final = current.resolve(strict=False)
        if not final.is_relative_to(self.root):
            raise SandboxError("Path escapes sandbox")
        return final

    @staticmethod
    def _sha(data: bytes):
        return hashlib.sha256(data).hexdigest()

    def read(self, rel: str):
        target = self.locate(rel)
        data = target.read_bytes()
        if b"\x00" in data:
            raise SandboxError("Binary file: use a binary-aware tool")
        return {"path": rel, "content": data.decode("utf-8"), "sha256": self._sha(data)}

    def write(self, rel: str, content: str, expected_sha: str | None = None):
        target = self.locate(rel)
        if not isinstance(content, str):
            raise SandboxError("Content must be text")
        if target.exists() and not target.is_file():
            raise SandboxError("Destination is not a file")
        old = target.read_bytes() if target.exists() else None
        if expected_sha is not None:
            if old is None or self._sha(old) != expected_sha:
                raise SandboxError("Precondition mismatch; file changed")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replacement for a single file; no claim of multi-file atomicity.
        new_data = content.encode("utf-8")
        handle, temp_name = tempfile.mkstemp(prefix=".bridge-x-", dir=target.parent)
        try:
            with os.fdopen(handle, "wb") as f:
                f.write(new_data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return {"success": True, "path": rel, "sha256": self._sha(new_data), "bytes": len(new_data)}

    def edit(self, rel: str, old: str, new: str, expected_sha: str | None = None):
        info = self.read(rel)
        if info["content"].count(old) != 1 or old == "":
            raise SandboxError("Edit precondition failed: old text must occur exactly once")
        result = info["content"].replace(old, new, 1)
        return self.write(rel, result, expected_sha if expected_sha is not None else info["sha256"])

    def apply_patch(self, patch: str):
        """Small strict unified diff, one existing UTF-8 file, no renames/binary changes."""
        lines = patch.splitlines(keepends=True)
        if len(lines) < 3 or not lines[0].startswith("--- a/") or not lines[1].startswith("+++ b/"):
            raise SandboxError("Expected single-file unified diff")
        old_path = lines[0][6:].strip()
        new_path = lines[1][6:].strip()
        if old_path != new_path:
            raise SandboxError("Renames are not supported")
        info = self.read(old_path)
        original = info["content"].splitlines(keepends=True)
        new_lines = []
        position = 0
        i = 2
        hunk_header = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
        count = 0
        while i < len(lines):
            match = hunk_header.match(lines[i])
            if not match:
                raise SandboxError("Malformed hunk header")
            start_old, size_old = int(match.group(1)), int(match.group(2) or "1")
            start_new, size_new = int(match.group(3)), int(match.group(4) or "1")
            target_pos = start_old - 1 if size_old else start_old
            if target_pos < position or target_pos > len(original):
                raise SandboxError("Conflicting hunk positions")
            new_lines.extend(original[position:target_pos])
            expected_new = start_new - 1 if size_new else start_new
            if expected_new != len(new_lines):
                raise SandboxError("Conflicting new hunk position")
            position = target_pos
            consumed = produced = 0
            i += 1
            while i < len(lines) and not lines[i].startswith("@@"):
                entry = lines[i]
                if entry.startswith("\\ No newline at end of file"):
                    raise SandboxError("No-newline markers are not supported")
                if not entry or entry[0] not in " +-":
                    raise SandboxError("Malformed patch line")
                if entry[0] in " -":
                    if position >= len(original) or original[position] != entry[1:]:
                        raise SandboxError("Patch context mismatch; file changed")
                    position += 1
                    consumed += 1
                if entry[0] in " +":
                    new_lines.append(entry[1:])
                    produced += 1
                i += 1
            if consumed != size_old or produced != size_new:
                raise SandboxError("Hunk length mismatch")
            count += 1
        if not count:
            raise SandboxError("Patch contained no hunks")
        new_lines.extend(original[position:])
        return self.write(old_path, "".join(new_lines), info["sha256"])

    def run_python(self, rel: str, timeout=10):
        if not (0.1 <= timeout <= 30):
            raise SandboxError("Timeout out of test limits")
        target = self.locate(rel)
        if target.suffix.lower() != ".py" or not target.is_file():
            raise SandboxError("Only existing Python test files may run")
        def bounded(stream):
            size = stream.tell()
            stream.seek(0)
            if size <= 100_000:
                return stream.read().decode("utf-8", errors="replace"), size, False
            head = stream.read(70_000)
            stream.seek(-29_800, os.SEEK_END)
            tail = stream.read(29_800)
            marker = f"\n[OUTPUT COMPACTED original_bytes={size}]\n".encode()
            return (head + marker + tail).decode("utf-8", errors="replace"), size, True

        # Drain to temporary files rather than retaining unbounded output in
        # RAM. The returned receipt contains bounded head/tail and byte counts.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            timed_out = False
            try:
                result = subprocess.run([sys.executable, "-I", "-X", "utf8", str(target)], cwd=self.root,
                                        stdout=out, stderr=err, timeout=timeout, check=False)
                exit_code = result.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = None
            except OSError:
                raise SandboxError("Python test process could not be started") from None
            stdout, stdout_size, stdout_cut = bounded(out)
            stderr, stderr_size, stderr_cut = bounded(err)
            status = "timeout" if timed_out else ("success" if exit_code == 0 else "failed")
            return RunReceipt(status, exit_code, stdout, stderr, timed_out,
                              stdout_size, stderr_size, stdout_cut, stderr_cut)
