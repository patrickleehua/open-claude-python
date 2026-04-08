"""Extraction prompt templates for the background memory extraction agent.

Ported from Claude-Code-rev/src/services/extractMemories/prompts.ts.
"""

from __future__ import annotations

from open_claude.utils.memory.types import (
    MEMORY_FRONTMATTER_EXAMPLE,
    TYPES_SECTION_COMBINED,
    TYPES_SECTION_INDIVIDUAL,
    WHAT_NOT_TO_SAVE_SECTION,
)


def _build_opener(new_message_count: int, existing_memories: str) -> str:
    """Shared opener for both extract-prompt variants."""
    manifest = ""
    if existing_memories.strip():
        manifest = (
            f"\n\n## Existing memory files\n\n{existing_memories}\n\n"
            "Check this list before writing — update an existing file rather "
            "than creating a duplicate."
        )

    return "\n".join([
        f"You are now acting as the memory extraction subagent. Analyze the most "
        f"recent ~{new_message_count} messages above and use them to update your "
        f"persistent memory systems.",
        "",
        "Available tools: Read, Grep, Glob, read-only Bash "
        "(ls/find/cat/stat/wc/head/tail and similar), and Edit/Write for paths "
        "inside the memory directory only. Bash rm is not permitted. All other "
        "tools — MCP, Agent, write-capable Bash, etc — will be denied.",
        "",
        "You have a limited turn budget. Edit requires a prior Read of the same "
        "file, so the efficient strategy is: turn 1 — issue all Read calls in "
        "parallel for every file you might update; turn 2 — issue all "
        "Write/Edit calls in parallel. Do not interleave reads and writes "
        "across multiple turns.",
        "",
        f"You MUST only use content from the last ~{new_message_count} messages "
        "to update your persistent memories. Do not waste any turns attempting "
        "to investigate or verify that content further — no grepping source "
        "files, no reading code to confirm a pattern exists, no git commands."
        + manifest,
    ])


def build_extract_auto_only_prompt(
    new_message_count: int,
    existing_memories: str,
    skip_index: bool = False,
) -> str:
    """Build the extraction prompt for auto-only memory (no team memory).

    Four-type taxonomy, no scope guidance (single directory).
    """
    if skip_index:
        how_to_save = [
            "## How to save memories",
            "",
            "Write each memory to its own file (e.g., `user_role.md`, "
            "`feedback_testing.md`) using this frontmatter format:",
            "",
            *MEMORY_FRONTMATTER_EXAMPLE,
            "",
            "- Organize memory semantically by topic, not chronologically",
            "- Update or remove memories that turn out to be wrong or outdated",
            "- Do not write duplicate memories. First check if there is an existing "
            "memory you can update before writing a new one.",
        ]
    else:
        how_to_save = [
            "## How to save memories",
            "",
            "Saving a memory is a two-step process:",
            "",
            "**Step 1** — write the memory to its own file (e.g., `user_role.md`, "
            "`feedback_testing.md`) using this frontmatter format:",
            "",
            *MEMORY_FRONTMATTER_EXAMPLE,
            "",
            "**Step 2** — add a pointer to that file in `MEMORY.md`. `MEMORY.md` "
            "is an index, not a memory — each entry should be one line, under "
            "~150 characters: `- [Title](file.md) — one-line hook`. It has no "
            "frontmatter. Never write memory content directly into `MEMORY.md`.",
            "",
            "- `MEMORY.md` is always loaded into your system prompt — lines after "
            "200 will be truncated, so keep the index concise",
            "- Organize memory semantically by topic, not chronologically",
            "- Update or remove memories that turn out to be wrong or outdated",
            "- Do not write duplicate memories. First check if there is an existing "
            "memory you can update before writing a new one.",
        ]

    return "\n".join([
        _build_opener(new_message_count, existing_memories),
        "",
        "If the user explicitly asks you to remember something, save it "
        "immediately as whichever type fits best. If they ask you to forget "
        "something, find and remove the relevant entry.",
        "",
        *TYPES_SECTION_INDIVIDUAL,
        *WHAT_NOT_TO_SAVE_SECTION,
        "",
        *how_to_save,
    ])


def build_extract_combined_prompt(
    new_message_count: int,
    existing_memories: str,
    skip_index: bool = False,
) -> str:
    """Build the extraction prompt for combined auto + team memory.

    Four-type taxonomy with per-type <scope> guidance (directory choice
    is baked into each type block, no separate routing section needed).
    """
    if skip_index:
        how_to_save = [
            "## How to save memories",
            "",
            "Write each memory to its own file in the chosen directory (private "
            "or team, per the type's scope guidance) using this frontmatter format:",
            "",
            *MEMORY_FRONTMATTER_EXAMPLE,
            "",
            "- Organize memory semantically by topic, not chronologically",
            "- Update or remove memories that turn out to be wrong or outdated",
            "- Do not write duplicate memories. First check if there is an existing "
            "memory you can update before writing a new one.",
        ]
    else:
        how_to_save = [
            "## How to save memories",
            "",
            "Saving a memory is a two-step process:",
            "",
            "**Step 1** — write the memory to its own file in the chosen directory "
            "(private or team, per the type's scope guidance) using this frontmatter "
            "format:",
            "",
            *MEMORY_FRONTMATTER_EXAMPLE,
            "",
            "**Step 2** — add a pointer to that file in the same directory's "
            "`MEMORY.md`. Each directory (private and team) has its own `MEMORY.md` "
            "index — each entry should be one line, under ~150 characters: "
            "`- [Title](file.md) — one-line hook`. They have no frontmatter. Never "
            "write memory content directly into a `MEMORY.md`.",
            "",
            "- Both `MEMORY.md` indexes are loaded into your system prompt — lines "
            "after 200 will be truncated, so keep them concise",
            "- Organize memory semantically by topic, not chronologically",
            "- Update or remove memories that turn out to be wrong or outdated",
            "- Do not write duplicate memories. First check if there is an existing "
            "memory you can update before writing a new one.",
        ]

    return "\n".join([
        _build_opener(new_message_count, existing_memories),
        "",
        "If the user explicitly asks you to remember something, save it "
        "immediately as whichever type fits best. If they ask you to forget "
        "something, find and remove the relevant entry.",
        "",
        *TYPES_SECTION_COMBINED,
        *WHAT_NOT_TO_SAVE_SECTION,
        "- You MUST avoid saving sensitive data within shared team memories. For "
        "example, never save API keys or user credentials.",
        "",
        *how_to_save,
    ])
