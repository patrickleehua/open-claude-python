"""AutoDream — background memory consolidation service."""

from __future__ import annotations

from .auto_dream import AutoDreamRunner, execute_auto_dream, init_auto_dream
from .config import is_auto_dream_enabled
from .consolidation_lock import (
    read_last_consolidated_at,
    record_consolidation,
    rollback_consolidation_lock,
    try_acquire_consolidation_lock,
)
from .consolidation_prompt import build_consolidation_prompt

__all__ = [
    "AutoDreamRunner",
    "build_consolidation_prompt",
    "execute_auto_dream",
    "init_auto_dream",
    "is_auto_dream_enabled",
    "read_last_consolidated_at",
    "record_consolidation",
    "rollback_consolidation_lock",
    "try_acquire_consolidation_lock",
]
