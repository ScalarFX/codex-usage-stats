"""Resolve the Codex data directory.

Priority:
  1. Explicit path argument (CLI --path)
  2. $CODEX_HOME
  3. ~/.codex
"""
from __future__ import annotations

import os
from pathlib import Path


def resolve_codex_home(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".codex"


def sessions_dir(codex_home: Path) -> Path:
    return codex_home / "sessions"
