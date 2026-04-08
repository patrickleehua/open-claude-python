"""File-based memory system.

Public API for the memory utilities package.
"""

from __future__ import annotations

from .age import memory_age, memory_age_days, memory_freshness_note, memory_freshness_text
from .frontmatter import parse_frontmatter
from .memdir import (
    DIR_EXISTS_GUIDANCE,
    ENTRYPOINT_NAME,
    MAX_ENTRYPOINT_BYTES,
    MAX_ENTRYPOINT_LINES,
    build_memory_lines,
    build_memory_prompt,
    ensure_memory_dir_exists,
    load_memory_prompt,
    truncate_entrypoint_content,
)
from .paths import get_memory_base_dir, get_memory_dir, get_memory_entrypoint, is_auto_mem_enabled, is_auto_mem_path, is_auto_memory_enabled
from .recall import RelevantMemory, find_relevant_memories
from .scanner import MemoryHeader, format_memory_manifest, scan_memory_files
from .types import MemoryType, parse_memory_type

__all__ = [
    # types
    "MemoryType",
    "parse_memory_type",
    # frontmatter
    "parse_frontmatter",
    # paths
    "get_memory_base_dir",
    "get_memory_dir",
    "get_memory_entrypoint",
    "is_auto_mem_enabled",
    "is_auto_mem_path",
    "is_auto_memory_enabled",
    # memdir
    "DIR_EXISTS_GUIDANCE",
    "ENTRYPOINT_NAME",
    "MAX_ENTRYPOINT_BYTES",
    "MAX_ENTRYPOINT_LINES",
    "build_memory_lines",
    "build_memory_prompt",
    "ensure_memory_dir_exists",
    "load_memory_prompt",
    "truncate_entrypoint_content",
    # scanner
    "MemoryHeader",
    "format_memory_manifest",
    "scan_memory_files",
    # recall
    "RelevantMemory",
    "find_relevant_memories",
    # age
    "memory_age",
    "memory_age_days",
    "memory_freshness_note",
    "memory_freshness_text",
]
