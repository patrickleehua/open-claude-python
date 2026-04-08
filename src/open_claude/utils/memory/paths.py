"""Memory directory path resolution.

Ported from Claude-Code-rev/src/memdir/paths.ts.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_AUTO_MEM_DIRNAME = "memory"
_ENTRYPOINT_NAME = "MEMORY.md"


def _sanitize_path(path: str) -> str:
    """Sanitize a path for use as a directory name.

    Replaces path separators and special characters with underscores,
    producing a flat directory name suitable for nesting under projects/.
    """
    # Normalize separators, strip leading/trailing separators
    sanitized = re.sub(r"[/\\]+", "_", path.strip("/\\"))
    # Collapse repeated underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip("_")
    return sanitized or "default"


def get_memory_base_dir() -> Path:
    """Return the base directory for persistent memory storage.

    Resolution order:
      1. CLAUDE_CODE_REMOTE_MEMORY_DIR env var (explicit override)
      2. ~/.claude (default config home)
    """
    remote_dir = os.environ.get("CLAUDE_CODE_REMOTE_MEMORY_DIR")
    if remote_dir:
        return Path(remote_dir)
    return Path.home() / ".claude"


def _get_git_root(cwd: str) -> str | None:
    """Find the canonical git repo root for cwd.

    Walks up from cwd looking for .git directory.
    Returns the root path string, or None if not in a git repo.
    """
    current = Path(cwd).resolve()
    while True:
        if (current / ".git").exists():
            return str(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def get_memory_dir(cwd: str | None = None) -> Path:
    """Return the auto-memory directory path.

    Structure: <memoryBase>/projects/<sanitized-cwd>/memory/
    """
    work_dir = cwd or os.getcwd()
    git_root = _get_git_root(work_dir)
    base = git_root or work_dir
    sanitized = _sanitize_path(base)
    return get_memory_base_dir() / "projects" / sanitized / _AUTO_MEM_DIRNAME


def get_memory_entrypoint(cwd: str | None = None) -> Path:
    """Return the path to MEMORY.md inside the auto-memory directory."""
    return get_memory_dir(cwd) / _ENTRYPOINT_NAME


def is_auto_mem_path(path: str, cwd: str | None = None) -> bool:
    """Check if an absolute path is within the auto-memory directory."""
    normalized = os.path.normpath(path)
    return normalized.startswith(str(get_memory_dir(cwd)))


def is_auto_memory_enabled() -> bool:
    """Check if auto-memory features are enabled.

    Resolution order:
      1. CLAUDE_CODE_DISABLE_AUTO_MEMORY env var (1/true → OFF)
      2. Default: enabled
    """
    env_val = os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "").lower()
    if env_val in ("1", "true", "yes"):
        return False
    return True


# Alias used by extract_memories module
is_auto_mem_enabled = is_auto_memory_enabled
