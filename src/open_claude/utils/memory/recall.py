"""Find memory files relevant to a user query via LLM side-query.

Ported from Claude-Code-rev/src/memdir/findRelevantMemories.ts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from open_claude.utils.memory.scanner import MemoryHeader, scan_memory_files, format_memory_manifest

logger = logging.getLogger(__name__)

_SELECT_MEMORIES_SYSTEM_PROMPT = """You are selecting memories that will be useful to Claude Code as it processes a user's query. You will be given the user's query and a list of available memory files with their filenames and descriptions.

Return a list of filenames for the memories that will clearly be useful to Claude Code as it processes the user's query (up to 5). Only include memories that you are certain will be helpful based on their name and description.
- If you are unsure if a memory will be useful in processing the user's query, then do not include it in your list. Be selective and discerning.
- If there are no memories in the list that would clearly be useful, feel free to return an empty list.
- If a list of recently-used tools is provided, do not select memories that are usage reference or API documentation for those tools (Claude Code is already exercising them). DO still select memories containing warnings, gotchas, or known issues about those tools — active use is exactly when those matter.

Respond with JSON: {"selected_memories": ["file1.md", "file2.md"]}"""


@dataclass
class RelevantMemory:
    """A memory file deemed relevant to a query."""

    path: str
    mtime_ms: float


async def find_relevant_memories(
    query: str,
    memory_dir: Path,
    already_surfaced: set[str] | None = None,
    recent_tools: list[str] | None = None,
    *,
    side_query_fn=None,
) -> list[RelevantMemory]:
    """Find memory files relevant to a query.

    Scans memory file headers and asks the LLM to select the most relevant
    ones (up to 5). Excludes MEMORY.md (already loaded in system prompt)
    and files in already_surfaced.

    Args:
        query: The user's query text.
        memory_dir: Path to the memory directory.
        already_surfaced: Set of file paths already shown in prior turns.
        recent_tools: List of recently used tool names (for noise filtering).
        side_query_fn: Async callable for LLM side-query. Signature:
            (system: str, messages: list, max_tokens: int, output_format: dict) -> str
            If None, returns empty list (no LLM available).
    """
    surfaced = already_surfaced or set()
    tools = recent_tools or []

    memories = [m for m in await scan_memory_files(memory_dir) if m.file_path not in surfaced]
    if not memories:
        return []

    if side_query_fn is None:
        # No LLM available for side-query — return nothing
        return []

    selected_filenames = await _select_relevant_memories(
        query, memories, tools, side_query_fn,
    )
    by_filename = {m.filename: m for m in memories}
    selected = [by_filename[f] for f in selected_filenames if f in by_filename]

    return [RelevantMemory(path=m.file_path, mtime_ms=m.mtime_ms) for m in selected]


async def _select_relevant_memories(
    query: str,
    memories: list[MemoryHeader],
    recent_tools: list[str],
    side_query_fn,
) -> list[str]:
    """Ask the LLM to select relevant memories from the manifest."""
    valid_filenames = {m.filename for m in memories}
    manifest = format_memory_manifest(memories)

    tools_section = f"\n\nRecently used tools: {', '.join(recent_tools)}" if recent_tools else ""

    try:
        result_text = await side_query_fn(
            system=_SELECT_MEMORIES_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Query: {query}\n\nAvailable memories:\n{manifest}{tools_section}",
            }],
            max_tokens=256,
            output_format={
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "selected_memories": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["selected_memories"],
                    "additionalProperties": False,
                },
            },
        )

        parsed = json.loads(result_text)
        return [f for f in parsed.get("selected_memories", []) if f in valid_filenames]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.debug("selectRelevantMemories failed: %s", e)
        return []
