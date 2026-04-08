"""Session memory utility functions.

Ported from Claude-Code-rev/src/services/SessionMemory/sessionMemoryUtils.ts.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

from open_claude.utils.memory.paths import get_memory_base_dir

_EXTRACTION_WAIT_TIMEOUT_MS = 15_000
_EXTRACTION_STALE_THRESHOLD_MS = 60_000  # 1 minute


@dataclass
class SessionMemoryConfig:
    """Configuration for session memory extraction thresholds."""

    minimum_message_tokens_to_init: int = 10_000
    minimum_tokens_between_update: int = 5_000
    tool_calls_between_updates: int = 3


# ---------------------------------------------------------------------------
# Module-level mutable state
# ---------------------------------------------------------------------------

_session_memory_config: SessionMemoryConfig = SessionMemoryConfig()

_last_summarized_message_id: str | None = None
_extraction_started_at: float | None = None
_tokens_at_last_extraction: int = 0
_session_memory_initialized: bool = False


def get_last_summarized_message_id() -> str | None:
    return _last_summarized_message_id


def set_last_summarized_message_id(message_id: str | None) -> None:
    global _last_summarized_message_id
    _last_summarized_message_id = message_id


def mark_extraction_started() -> None:
    global _extraction_started_at
    import time
    _extraction_started_at = time.time() * 1000


def mark_extraction_completed() -> None:
    global _extraction_started_at
    _extraction_started_at = None


async def wait_for_session_memory_extraction(timeout_ms: int = _EXTRACTION_WAIT_TIMEOUT_MS) -> None:
    """Wait for any in-progress extraction to complete (with timeout)."""
    import time
    start = time.time() * 1000
    while _extraction_started_at is not None:
        age = time.time() * 1000 - _extraction_started_at
        if age > _EXTRACTION_STALE_THRESHOLD_MS:
            return
        if time.time() * 1000 - start > timeout_ms:
            return
        await asyncio.sleep(1.0)


def get_session_memory_path() -> Path:
    """Return the path to the session memory file."""
    return get_session_memory_dir() / "session-notes.md"


def get_session_memory_dir() -> Path:
    """Return the directory for session memory files."""
    return get_memory_base_dir() / "session-memory"


async def get_session_memory_content() -> str | None:
    """Read the current session memory content."""
    path = get_session_memory_path()
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except PermissionError:
        return None


def set_session_memory_config(config: dict) -> None:
    global _session_memory_config
    for key, value in config.items():
        if hasattr(_session_memory_config, key):
            setattr(_session_memory_config, key, value)


def get_session_memory_config() -> SessionMemoryConfig:
    return SessionMemoryConfig(
        minimum_message_tokens_to_init=_session_memory_config.minimum_message_tokens_to_init,
        minimum_tokens_between_update=_session_memory_config.minimum_tokens_between_update,
        tool_calls_between_updates=_session_memory_config.tool_calls_between_updates,
    )


def record_extraction_token_count(current_token_count: int) -> None:
    global _tokens_at_last_extraction
    _tokens_at_last_extraction = current_token_count


def is_session_memory_initialized() -> bool:
    return _session_memory_initialized


def mark_session_memory_initialized() -> None:
    global _session_memory_initialized
    _session_memory_initialized = True


def has_met_initialization_threshold(current_token_count: int) -> bool:
    return current_token_count >= _session_memory_config.minimum_message_tokens_to_init


def has_met_update_threshold(current_token_count: int) -> bool:
    return (current_token_count - _tokens_at_last_extraction) >= _session_memory_config.minimum_tokens_between_update


def get_tool_calls_between_updates() -> int:
    return _session_memory_config.tool_calls_between_updates


def reset_session_memory_state() -> None:
    """Reset all session memory state (useful for testing)."""
    global _session_memory_config, _tokens_at_last_extraction
    global _session_memory_initialized, _last_summarized_message_id, _extraction_started_at

    _session_memory_config = SessionMemoryConfig()
    _tokens_at_last_extraction = 0
    _session_memory_initialized = False
    _last_summarized_message_id = None
    _extraction_started_at = None
