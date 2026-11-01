"""Explicit operator action: copy the local gateway key without printing it."""
import os
from pathlib import Path
import subprocess
import sys
from bridge_x.errors import BridgeError
from bridge_x.user_state import personal_key


def main():
    if sys.platform != "win32":
        print("Use python -m bridge_x key to obtain your local key on this platform.")
        return 2
    try:
        key = personal_key()
        clip = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "clip.exe"
        subprocess.run([str(clip)], input=key.encode("utf-16"), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True, timeout=5)
    except BridgeError as error:
        print(error.code + ": " + error.message)
        return 2
    except (OSError, subprocess.SubprocessError):
        print("CLIPBOARD_UNAVAILABLE: Run python -m bridge_x key to obtain the key locally.")
        return 2
    print("Local key copied. Paste it into Bridge X and ZCode.\nКлюч скопирован. Вставьте его в Bridge X и ZCode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
