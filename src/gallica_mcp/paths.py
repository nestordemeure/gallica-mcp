"""Filesystem locations shared by the MCP server and the CLI.

The cache must not depend on the working directory: the CLI is installed
globally and invoked from whatever project the user happens to be in, so a
CWD-relative cache would scatter downloads and destroy the hit rate.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "gallica-mcp"
CACHE_DIR_ENV_VAR = "GALLICA_CACHE_DIR"


def cache_dir(override: str | Path | None = None) -> Path:
    """Resolve the download cache directory, creating it if needed.

    Precedence: explicit override, then ``GALLICA_CACHE_DIR``, then
    ``$XDG_CACHE_HOME/gallica-mcp`` (``~/.cache`` by default).
    """
    if override is not None:
        path = Path(override).expanduser()
    elif env_value := os.environ.get(CACHE_DIR_ENV_VAR):
        path = Path(env_value).expanduser()
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or "~/.cache").expanduser()
        path = base / APP_DIR_NAME

    path.mkdir(parents=True, exist_ok=True)
    return path
