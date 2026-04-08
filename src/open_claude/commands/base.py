"""Command base classes — mirrors Claude-Code-rev's slash-command architecture.

Three command types:
  - **LocalCommand**  — runs locally, returns text or compact result (e.g. /help, /clear)
  - **PromptCommand** — expands into a prompt sent to the model (e.g. /commit)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from open_claude.schemas.permissions import PermissionMode, ToolPermissionContext

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class CommandResultType(str, Enum):
    TEXT = "text"
    COMPACT = "compact"
    SKIP = "skip"


@dataclass
class CommandResult:
    """Unified result from a slash command."""
    type: CommandResultType = CommandResultType.TEXT
    value: str = ""
    # compact-specific fields
    compacted_messages: list | None = None
    display_text: str | None = None
    # prompt-specific fields
    should_query: bool = False
    prompt_content: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    # navigation hints
    next_input: str | None = None
    submit_next_input: bool = False


# ---------------------------------------------------------------------------
# Context passed to every command
# ---------------------------------------------------------------------------

@runtime_checkable
class CommandContext(Protocol):
    """Minimal protocol that the ChatApp (or test harness) must satisfy."""

    @property
    def messages(self) -> list[dict]:
        """Current conversation history."""
        ...

    @property
    def model_name(self) -> str:
        ...

    @property
    def token_usage(self) -> Any:
        ...

    def clear_conversation(self) -> None:
        ...

    def compact_conversation(self, instructions: str = "") -> CommandResult:
        ...

    def load_settings(self) -> dict:
        ...

    @property
    def permission_context(self) -> ToolPermissionContext:
        ...

    def set_permission_mode(self, mode: PermissionMode) -> None:
        ...

    async def refresh_tools(self) -> None:
        """Reload the active tool pool after config changes."""
        ...


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class CommandBase(ABC):
    """Abstract base for all slash commands.

    Mirrors ``CommandBase`` from ``Claude-Code-rev/src/types/command.ts``.
    """

    # --- metadata -----------------------------------------------------------
    name: str = ""
    description: str = ""
    aliases: list[str] = []
    argument_hint: str = ""
    is_hidden: bool = False
    source: str = "builtin"  # builtin | skill | plugin

    def is_enabled(self) -> bool:
        """Override to conditionally hide a command."""
        return True

    # --- abstract -----------------------------------------------------------
    @abstractmethod
    async def execute(self, args: str, context: CommandContext) -> CommandResult:
        """Run the command and return a result."""
        ...

    # --- helpers ------------------------------------------------------------
    @property
    def all_names(self) -> list[str]:
        return [self.name, *self.aliases]


# ---------------------------------------------------------------------------
# Convenience mixins — not strictly required but useful for documentation
# ---------------------------------------------------------------------------

class LocalCommand(CommandBase):
    """Command that runs entirely locally (no model call)."""


class PromptCommand(CommandBase):
    """Command that expands into a prompt for the model."""
