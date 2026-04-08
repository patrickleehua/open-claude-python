"""Session Memory service — automatic conversation summarization."""

from __future__ import annotations

from .prompts import (
    DEFAULT_SESSION_MEMORY_TEMPLATE,
    build_session_memory_update_prompt,
    load_session_memory_prompt,
    load_session_memory_template,
    truncate_session_memory_for_compact,
)
from .session_memory import (
    ManualExtractionResult,
    extract_session_memory,
    manually_extract_session_memory,
    setup_session_memory_file,
    should_extract_memory,
)
from .utils import (
    SessionMemoryConfig,
    get_session_memory_config,
    get_session_memory_content,
    get_session_memory_dir,
    get_session_memory_path,
    is_session_memory_initialized,
    reset_session_memory_state,
    set_session_memory_config,
    wait_for_session_memory_extraction,
)

__all__ = [
    "DEFAULT_SESSION_MEMORY_TEMPLATE",
    "ManualExtractionResult",
    "SessionMemoryConfig",
    "build_session_memory_update_prompt",
    "extract_session_memory",
    "get_session_memory_config",
    "get_session_memory_content",
    "get_session_memory_dir",
    "get_session_memory_path",
    "is_session_memory_initialized",
    "load_session_memory_prompt",
    "load_session_memory_template",
    "manually_extract_session_memory",
    "reset_session_memory_state",
    "set_session_memory_config",
    "setup_session_memory_file",
    "should_extract_memory",
    "truncate_session_memory_for_compact",
    "wait_for_session_memory_extraction",
]
