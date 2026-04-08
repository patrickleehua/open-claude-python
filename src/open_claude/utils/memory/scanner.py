"""Memory directory scanning primitives.

Ported from Claude-Code-rev/src/memdir/memoryScan.ts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from open_claude.utils.memory.frontmatter import parse_frontmatter
from open_claude.utils.memory.types import MemoryType, parse_memory_type

MAX_MEMORY_FILES = 200
FRONTMATTER_MAX_LINES = 30


@dataclass
class MemoryHeader:
    """Parsed header from a memory .md file."""

    filename: str
    file_path: str
    mtime_ms: float
    description: str | None
    type: MemoryType | None


async def scan_memory_files(memory_dir: Path) -> list[MemoryHeader]:
    """Scan a memory directory for .md files and read their frontmatter.

    Returns headers sorted newest-first, capped at MAX_MEMORY_FILES.
    """
    if not memory_dir.is_dir():
        return []

    headers: list[MemoryHeader] = []
    for root, _dirs, files in os.walk(memory_dir):
        for fname in files:
            if not fname.endswith(".md") or fname == "MEMORY.md":
                continue

            file_path = os.path.join(root, fname)
            rel_path = os.path.relpath(file_path, memory_dir)

            try:
                stat_result = os.stat(file_path)
                mtime_ms = stat_result.st_mtime * 1000

                # Read only first N lines for frontmatter
                with open(file_path, encoding="utf-8") as f:
                    lines: list[str] = []
                    for i, line in enumerate(f):
                        if i >= FRONTMATTER_MAX_LINES:
                            break
                        lines.append(line)
                    content = "".join(lines)

                frontmatter, _body = parse_frontmatter(content)

                headers.append(MemoryHeader(
                    filename=rel_path.replace("\\", "/"),
                    file_path=file_path,
                    mtime_ms=mtime_ms,
                    description=frontmatter.get("description"),
                    type=parse_memory_type(frontmatter.get("type")),
                ))
            except (OSError, UnicodeDecodeError):
                continue

    # Sort newest-first and cap
    headers.sort(key=lambda h: h.mtime_ms, reverse=True)
    return headers[:MAX_MEMORY_FILES]


def format_memory_manifest(memories: list[MemoryHeader]) -> str:
    """Format memory headers as a text manifest.

    One line per file: [type] filename (timestamp): description
    """
    lines: list[str] = []
    for m in memories:
        tag = f"[{m.type}] " if m.type else ""
        ts = datetime.fromtimestamp(m.mtime_ms / 1000, tz=timezone.utc).isoformat()
        if m.description:
            lines.append(f"- {tag}{m.filename} ({ts}): {m.description}")
        else:
            lines.append(f"- {tag}{m.filename} ({ts})")
    return "\n".join(lines)
