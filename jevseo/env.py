"""Secret lookup. Values are returned to callers, never printed or written."""
from __future__ import annotations

import os
from pathlib import Path

KEY_FILES = [Path.home() / "Desktop" / "Keys" / ".env"]


def secret(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    for path in KEY_FILES:
        if not path.is_file():
            continue
        for line in path.read_text(errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    return None
