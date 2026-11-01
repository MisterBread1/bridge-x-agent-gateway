"""Stable user data paths, with explicit legacy discovery and no silent moves."""
import os
from pathlib import Path


def data_dir():
    explicit = os.getenv("BRIDGEX_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser()
    base = os.getenv("LOCALAPPDATA") if os.name == "nt" else os.getenv("XDG_DATA_HOME")
    return Path(base) / "BridgeX" if base else Path.home() / ".local" / "share" / "BridgeX"


def config_path():
    legacy = Path(__file__).resolve().parents[1] / ".molab_local.json"
    target = data_dir() / ".molab_local.json"
    return legacy if legacy.is_file() and not target.is_file() else target


def journal_path():
    legacy = Path.cwd() / "bridge_x_state.sqlite3"
    return legacy if legacy.is_file() else data_dir() / "bridge_x_state.sqlite3"


class InstanceLock:
    """Process-held lock, independent of port selection. Never kills a process."""
    def __init__(self, filename):
        self.filename = filename
        self.file = None

    def __enter__(self):
        if self.filename == ":memory:":
            return self
        path = Path(self.filename).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = Path(str(path) + ".lock").open("a+b")
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            from .errors import BridgeError
            raise BridgeError("JOURNAL_IN_USE", "Another Bridge X owns this journal; use its window or a separate data directory", 409) from None
        return self

    def __exit__(self, *args):
        if self.file is not None:
            self.file.close()  # OS releases the process-held lock, including on crash
            self.file = None
