"""Editor launching helpers."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path


def resolve_editor_command() -> tuple[list[str], str]:
    """Resolve the editor command from VISUAL/EDITOR or platform fallbacks."""
    for env_name in ("VISUAL", "EDITOR"):
        value = os.environ.get(env_name)
        if value:
            return shlex.split(value), env_name

    fallback = _platform_editor_fallback()
    if fallback:
        return fallback, "default"

    raise RuntimeError("No editor configured. Set $EDITOR or $VISUAL.")


def open_file_in_editor(path: str | Path) -> str:
    """Open a file in the configured editor and wait for it to exit."""
    file_path = str(Path(path))
    command, source = resolve_editor_command()
    subprocess.run([*command, file_path], check=True)
    return source


def _platform_editor_fallback() -> list[str] | None:
    candidates = [
        "code",
        "notepad",
        "nano",
        "vim",
        "vi",
    ]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return [resolved]
    return None
