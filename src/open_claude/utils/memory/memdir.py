"""Core memory directory operations.

Ported from Claude-Code-rev/src/memdir/memdir.ts.

Builds the typed-memory behavioral instructions (without MEMORY.md content),
manages the MEMORY.md entrypoint, and provides the top-level `load_memory_prompt`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from open_claude.utils.memory.types import (
    MEMORY_FRONTMATTER_EXAMPLE,
    TRUSTING_RECALL_SECTION,
    TYPES_SECTION_INDIVIDUAL,
    WHAT_NOT_TO_SAVE_SECTION,
    WHEN_TO_ACCESS_SECTION,
)
from open_claude.utils.memory.paths import get_memory_dir, is_auto_memory_enabled

logger = logging.getLogger(__name__)

ENTRYPOINT_NAME = "MEMORY.md"
MAX_ENTRYPOINT_LINES = 200
MAX_ENTRYPOINT_BYTES = 25_000
_AUTO_MEM_DISPLAY_NAME = "auto memory"

DIR_EXISTS_GUIDANCE = (
    "This directory already exists — write to it directly with the Write tool "
    "(do not run mkdir or check for its existence)."
)


@dataclass
class EntrypointTruncation:
    content: str
    line_count: int
    byte_count: int
    was_line_truncated: bool
    was_byte_truncated: bool


def truncate_entrypoint_content(raw: str) -> EntrypointTruncation:
    """Truncate MEMORY.md content to the line AND byte caps."""
    trimmed = raw.strip()
    content_lines = trimmed.split("\n")
    line_count = len(content_lines)
    byte_count = len(trimmed.encode("utf-8"))

    was_line_truncated = line_count > MAX_ENTRYPOINT_LINES
    was_byte_truncated = byte_count > MAX_ENTRYPOINT_BYTES

    if not was_line_truncated and not was_byte_truncated:
        return EntrypointTruncation(
            content=trimmed,
            line_count=line_count,
            byte_count=byte_count,
            was_line_truncated=False,
            was_byte_truncated=False,
        )

    truncated = "\n".join(content_lines[:MAX_ENTRYPOINT_LINES]) if was_line_truncated else trimmed

    if len(truncated.encode("utf-8")) > MAX_ENTRYPOINT_BYTES:
        # Byte-truncate at last newline boundary
        cut_at = truncated.rfind("\n", 0, MAX_ENTRYPOINT_BYTES)
        if cut_at > 0:
            truncated = truncated[:cut_at]
        else:
            truncated = truncated[:MAX_ENTRYPOINT_BYTES]

    byte_str = f"{byte_count / 1024:.1f}KB"
    limit_str = f"{MAX_ENTRYPOINT_BYTES / 1024:.1f}KB"

    if was_byte_truncated and not was_line_truncated:
        reason = f"{byte_str} (limit: {limit_str}) — index entries are too long"
    elif was_line_truncated and not was_byte_truncated:
        reason = f"{line_count} lines (limit: {MAX_ENTRYPOINT_LINES})"
    else:
        reason = f"{line_count} lines and {byte_str}"

    truncated += (
        f"\n\n> WARNING: {ENTRYPOINT_NAME} is {reason}. "
        "Only part of it was loaded. Keep index entries to one line under ~200 chars; "
        "move detail into topic files."
    )

    return EntrypointTruncation(
        content=truncated,
        line_count=line_count,
        byte_count=byte_count,
        was_line_truncated=was_line_truncated,
        was_byte_truncated=was_byte_truncated,
    )


async def ensure_memory_dir_exists(memory_dir: Path) -> None:
    """Ensure the memory directory exists (recursive mkdir)."""
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.debug("ensure_memory_dir_exists failed for %s: %s", memory_dir, e)


def build_memory_lines(
    display_name: str,
    memory_dir: str,
    extra_guidelines: list[str] | None = None,
    skip_index: bool = False,
) -> list[str]:
    """Build the typed-memory behavioral instructions (without MEMORY.md content).

    Used by both build_memory_prompt (includes content) and load_memory_prompt
    (system prompt, content injected via user context instead).
    """
    if skip_index:
        how_to_save = [
            "## How to save memories",
            "",
            "Write each memory to its own file (e.g., `user_role.md`, `feedback_testing.md`) using this frontmatter format:",
            "",
            *MEMORY_FRONTMATTER_EXAMPLE,
            "",
            "- Keep the name, description, and type fields in memory files up-to-date with the content",
            "- Organize memory semantically by topic, not chronologically",
            "- Update or remove memories that turn out to be wrong or outdated",
            "- Do not write duplicate memories. First check if there is an existing memory you can update before writing a new one.",
        ]
    else:
        how_to_save = [
            "## How to save memories",
            "",
            "Saving a memory is a two-step process:",
            "",
            "**Step 1** — write the memory to its own file (e.g., `user_role.md`, `feedback_testing.md`) using this frontmatter format:",
            "",
            *MEMORY_FRONTMATTER_EXAMPLE,
            "",
            f"**Step 2** — add a pointer to that file in `{ENTRYPOINT_NAME}`. `{ENTRYPOINT_NAME}` is an index, not a memory — each entry should be one line, under ~150 characters: `- [Title](file.md) — one-line hook`. It has no frontmatter. Never write memory content directly into `{ENTRYPOINT_NAME}`.",
            "",
            f"- `{ENTRYPOINT_NAME}` is always loaded into your conversation context — lines after {MAX_ENTRYPOINT_LINES} will be truncated, so keep the index concise",
            "- Keep the name, description, and type fields in memory files up-to-date with the content",
            "- Organize memory semantically by topic, not chronologically",
            "- Update or remove memories that turn out to be wrong or outdated",
            "- Do not write duplicate memories. First check if there is an existing memory you can update before writing a new one.",
        ]

    lines: list[str] = [
        f"# {display_name}",
        "",
        f"You have a persistent, file-based memory system at `{memory_dir}`. {DIR_EXISTS_GUIDANCE}",
        "",
        "You should build up this memory system over time so that future conversations can have a complete picture of who the user is, how they'd like to collaborate with you, what behaviors to avoid or repeat, and the context behind the work the user gives you.",
        "",
        "If the user explicitly asks you to remember something, save it immediately as whichever type fits best. If they ask you to forget something, find and remove the relevant entry.",
        "",
        *TYPES_SECTION_INDIVIDUAL,
        *WHAT_NOT_TO_SAVE_SECTION,
        "",
        *how_to_save,
        "",
        *WHEN_TO_ACCESS_SECTION,
        "",
        *TRUSTING_RECALL_SECTION,
        "",
        "## Memory and other forms of persistence",
        "Memory is one of several persistence mechanisms available to you as you assist the user in a given conversation. The distinction is often that memory can be recalled in future conversations and should not be used for persisting information that is only useful within the scope of the current conversation.",
        "- When to use or update a plan instead of memory: If you are about to start a non-trivial implementation task and would like to reach alignment with the user on your approach you should use a Plan rather than saving this information to memory. Similarly, if you already have a plan within the conversation and you have changed your approach persist that change by updating the plan rather than saving a memory.",
        "- When to use or update tasks instead of memory: When you need to break your work in current conversation into discrete steps or keep track of your progress use tasks instead of saving to memory. Tasks are great for persisting information about the work that needs to be done in the current conversation, but memory should be reserved for information that will be useful in future conversations.",
        "",
        *(extra_guidelines or []),
        "",
    ]

    return lines


def build_memory_prompt(
    display_name: str,
    memory_dir: str,
    extra_guidelines: list[str] | None = None,
) -> str:
    """Build the typed-memory prompt with MEMORY.md content included."""
    entrypoint_path = Path(memory_dir) / ENTRYPOINT_NAME

    # Read existing MEMORY.md
    entrypoint_content = ""
    try:
        entrypoint_content = entrypoint_path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        pass

    lines = build_memory_lines(display_name, memory_dir, extra_guidelines)

    if entrypoint_content.strip():
        t = truncate_entrypoint_content(entrypoint_content)
        lines.extend([f"## {ENTRYPOINT_NAME}", "", t.content])
    else:
        lines.extend([
            f"## {ENTRYPOINT_NAME}",
            "",
            f"Your {ENTRYPOINT_NAME} is currently empty. When you save new memories, they will appear here.",
        ])

    return "\n".join(lines)


async def load_memory_prompt(cwd: str | None = None) -> str | None:
    """Load the unified memory prompt for inclusion in the system prompt.

    Returns None when auto memory is disabled.
    """
    if not is_auto_memory_enabled():
        return None

    auto_dir = get_memory_dir(cwd)
    await ensure_memory_dir_exists(auto_dir)

    return build_memory_prompt(
        _AUTO_MEM_DISPLAY_NAME,
        str(auto_dir),
    )
