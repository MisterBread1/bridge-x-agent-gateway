"""Create a local template without overwriting an existing file."""
from pathlib import Path
import shutil


def main():
    root = Path(__file__).resolve().parents[1]
    target = root / ".molab_local.json"
    try:
        with target.open("xb") as destination, (root / "examples/.molab_local.example.json").open("rb") as example:
            shutil.copyfileobj(example, destination)
    except FileExistsError:
        print("Local configuration already exists; it was not changed")
        return 0
    print("Created .molab_local.json with placeholders. Edit locally, then run python -m bridge_x --check-config")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
