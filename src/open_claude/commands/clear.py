"""/clear command — clear conversation history."""

from __future__ import annotations

from open_claude.commands.base import CommandResult, CommandResultType, LocalCommand


class ClearCommand(LocalCommand):
    name = "clear"
    description = "Clear conversation history and free up context"
    aliases = ["reset", "new"]

    async def execute(self, args: str, context) -> CommandResult:  # type: ignore[override]
        context.clear_conversation()
        return CommandResult(
            type=CommandResultType.TEXT,
            value="Conversation cleared.",
        )
