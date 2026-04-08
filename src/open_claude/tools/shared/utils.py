"""Shared utilities for file-related tools."""

from __future__ import annotations

import os
from pathlib import Path


# Binary extensions that should not be read as text
BINARY_EXTENSIONS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".bin", ".obj", ".o", ".a",
    ".lib", ".pyc", ".pyd", ".pyo", ".class", ".jar", ".war",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".wav",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".sqlite", ".db", ".iso", ".dmg",
})


def expand_path(path_str: str) -> Path:
    """Expand ~, env vars, and normalize a path string to an absolute Path."""
    return Path(os.path.expandvars(os.path.expanduser(path_str))).resolve()


def to_relative_path(path: Path, base: Path | None = None) -> str:
    """Convert an absolute path to relative from base (default cwd).

    Falls back to the absolute string if not sub-path of base.
    """
    if base is None:
        base = Path.cwd()
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def format_file_content(content: str, start_line: int = 1) -> str:
    """Format file content with line numbers in cat -n format.

    Lines are numbered starting from ``start_line`` with tab separation,
    matching the output format of ``cat -n``.
    """
    lines = content.split("\n")
    # Remove trailing empty line from split if content ends with newline
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines:
        return ""
    width = len(str(start_line + len(lines) - 1))
    result_lines = []
    for i, line in enumerate(lines):
        line_num = start_line + i
        result_lines.append(f"{line_num:>{width}}\t{line}")
    return "\n".join(result_lines)


def is_binary_extension(path: Path) -> bool:
    """Check if a file has a binary extension."""
    return path.suffix.lower() in BINARY_EXTENSIONS
