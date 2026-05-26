"""Minimal .env loader (no external dependency).

Reads ``KEY=VALUE`` lines from a ``.env`` file at the project root and
populates ``os.environ`` for keys not already set. Lines starting with ``#``
and blank lines are ignored. Surrounding quotes around the value are stripped.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
