"""Slash command system — registration, discovery, and dispatch.

Public API::

    from open_claude.commands import get_registry, CommandResult

    registry = get_registry()
    result = await registry.dispatch("/help", ctx)
"""

from open_claude.commands.base import (
    CommandBase,
    CommandContext,
    CommandResult,
    CommandResultType,
    LocalCommand,
    PromptCommand,
)
from open_claude.commands.registry import (
    CommandRegistry,
    get_registry,
    reset_registry,
)

__all__ = [
    # base classes
    "CommandBase",
    "CommandContext",
    "CommandResult",
    "CommandResultType",
    "LocalCommand",
    "PromptCommand",
    # registry
    "CommandRegistry",
    "get_registry",
    "reset_registry",
]
