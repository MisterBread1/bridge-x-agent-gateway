"""Personal local authentication and consistent, non-overwriting backups."""
import os
from pathlib import Path
import secrets
import sqlite3
import time
from contextlib import closing
from .errors import BridgeError
from .paths import data_dir


def personal_key():
    explicit = os.getenv("BRIDGEX_LOCAL_KEY")
    if explicit and explicit != "molab-local":
        return explicit
    path = data_dir() / "local.key"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise OSError("symlink")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            value = path.read_text(encoding="ascii").strip()
        else:
            value = secrets.token_urlsafe(32)
            with os.fdopen(descriptor, "w", encoding="ascii") as output:
                output.write(value + "\n")
        if not 32 <= len(value) <= 256 or any(c.isspace() for c in value):
            raise ValueError("invalid key")
        return value
    except (OSError, ValueError, UnicodeError):
        raise BridgeError("LOCAL_KEY_FILE_INVALID", "Cannot create or read the personal local.key file", 503) from None


def backup_journal(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file() or source == destination:
        raise BridgeError("BACKUP_INVALID", "Choose an existing journal and a different new backup file", 400)
    owned = False
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        owned = True
        deadline = time.monotonic() + 30
        def progress(*args):
            if time.monotonic() > deadline:
                raise TimeoutError()
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=2)) as original:
            with closing(sqlite3.connect(destination)) as target:
                original.backup(target, pages=64, progress=progress)
                if target.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise sqlite3.DatabaseError("integrity")
    except (OSError, sqlite3.Error, TimeoutError):
        if owned:
            destination.unlink(missing_ok=True)
        raise BridgeError("BACKUP_FAILED", "Backup was not completed; use a new writable filename and preserve the original journal", 503) from None
