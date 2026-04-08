"""Command registry — registration, discovery, and dispatch.

Mirrors ``getCommands``, ``findCommand``, ``hasCommand`` from
``Claude-Code-rev/src/commands.ts`` and the lazy-loading pattern used by
individual command modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from open_claude.commands.base import CommandBase, CommandResult

if TYPE_CHECKING:
    from open_claude.commands.base import CommandContext


class CommandRegistry:
    """Central registry for slash commands.

    Usage::

        from open_claude.commands import get_registry

        reg = get_registry()
        reg.register(HelpCommand())
        result = await reg.dispatch("/help", ctx)
    """

    def __init__(self) -> None:
        self._commands: dict[str, CommandBase] = {}
        self._alias_map: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, command: CommandBase) -> None:
        """Register a command and all its aliases."""
        if not command.name:
            raise ValueError("Command must have a non-empty name")
        self._commands[command.name] = command
        for alias in command.aliases:
            self._alias_map[alias] = command.name

    def unregister(self, name: str) -> None:
        """Remove a command by name or alias."""
        canonical = self._alias_map.pop(name, name)
        cmd = self._commands.pop(canonical, None)
        if cmd:
            for alias in cmd.aliases:
                self._alias_map.pop(alias, None)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def find(self, name: str) -> CommandBase | None:
        """Look up a command by name or alias (exact match)."""
        canonical = self._alias_map.get(name, name)
        return self._commands.get(canonical)

    def has(self, name: str) -> bool:
        return self.find(name) is not None

    def get(self, name: str) -> CommandBase:
        cmd = self.find(name)
        if cmd is None:
            raise KeyError(f"Unknown command: {name}")
        return cmd

    # ------------------------------------------------------------------
    # Enumeration
    # ------------------------------------------------------------------

    def get_all(self) -> list[CommandBase]:
        """All registered commands, including hidden ones."""
        return list(self._commands.values())

    def get_visible(self) -> list[CommandBase]:
        """Commands that should appear in help / auto-complete."""
        return [
            c for c in self._commands.values()
            if not c.is_hidden and c.is_enabled()
        ]

    def get_command_names(self) -> set[str]:
        """All canonical names plus aliases (for fast membership tests)."""
        names = set(self._commands.keys())
        names.update(self._alias_map.keys())
        return names

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, raw_input: str, context: CommandContext) -> CommandResult | None:
        """Parse *raw_input*, find the matching command, and execute it.

        Returns ``None`` if *raw_input* does not start with ``/`` or the
        command is not recognised.
        """
        parsed = _parse_slash_command(raw_input)
        if parsed is None:
            return None

        name, args = parsed
        cmd = self.find(name)
        if cmd is None:
            return None

        return await cmd.execute(args, context)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_slash_command(raw: str) -> tuple[str, str] | None:
    """Extract ``(command_name, args)`` from raw user input.

    Returns ``None`` if the input does not look like a slash command.
    Mirrors ``parseSlashCommand`` from ``slashCommandParsing.ts``.
    """
    text = raw.strip()
    if not text.startswith("/"):
        return None

    # Split once — "/compact custom instructions" → ("compact", "custom instructions")
    parts = text[1:].split(None, 1)
    if not parts:
        return None

    name = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    return name, args


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_registry: CommandRegistry | None = None


def get_registry() -> CommandRegistry:
    """Return the global command registry, creating and populating it on first call."""
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
        _register_builtin_commands(_registry)
    return _registry


def reset_registry() -> None:
    """Reset the global registry (useful for tests)."""
    global _registry
    _registry = None


def _register_builtin_commands(registry: CommandRegistry) -> None:
    """Import and register all built-in command modules."""
    # Local imports to keep startup cheap and avoid circular deps
    from open_claude.commands.help import HelpCommand
    from open_claude.commands.clear import ClearCommand
    from open_claude.commands.compact import CompactCommand
    from open_claude.commands.cost import CostCommand
    from open_claude.commands.config import ConfigCommand
    from open_claude.commands.commit import CommitCommand
    from open_claude.commands.memory import MemoryCommand
    from open_claude.commands.mcp import McpCommand
    from open_claude.commands.permissions import PermissionsCommand

    for cmd_cls in (HelpCommand, ClearCommand, CompactCommand, CostCommand, ConfigCommand, CommitCommand, MemoryCommand, McpCommand, PermissionsCommand):
        registry.register(cmd_cls())
