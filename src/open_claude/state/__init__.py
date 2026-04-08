"""Application state management with singleton pattern."""

from dataclasses import dataclass, field
from pathlib import Path

from open_claude.constants import DEFAULT_MAX_TOKENS, DEFAULT_MODEL


@dataclass
class AppState:
    """Holds runtime application state."""

    model: str = DEFAULT_MODEL
    working_dir: Path = field(default_factory=Path.cwd)
    verbose: bool = False
    max_tokens: int = DEFAULT_MAX_TOKENS
    conversation_history: list = field(default_factory=list)
    is_running: bool = False


_instance: AppState | None = None


def get_state() -> AppState:
    """Return the singleton AppState instance, creating it if needed."""
    global _instance
    if _instance is None:
        _instance = AppState()
    return _instance


def reset_state() -> None:
    """Reset the singleton so the next get_state() creates a fresh instance."""
    global _instance
    _instance = None
