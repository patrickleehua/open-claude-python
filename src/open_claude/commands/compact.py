"""/compact command — compress conversation while preserving key context.

Mirrors ``Claude-Code-rev/src/commands/compact/compact.ts``.
"""

from __future__ import annotations

from open_claude.commands.base import CommandResult, CommandResultType, LocalCommand


class CompactCommand(LocalCommand):
    name = "compact"
    description = (
        "Clear conversation history but keep a summary in context. "
        "Optional: /compact [instructions for summarization]"
    )
    argument_hint = "<optional custom summarization instructions>"

    async def execute(self, args: str, context) -> CommandResult:  # type: ignore[override]
        from open_claude.services.compact import execute_compact

        instructions = args.strip() if args.strip() else ""
        result = await execute_compact(context.messages, instructions=instructions)
        return CommandResult(
            type=CommandResultType.COMPACT,
            compacted_messages=result.compacted_messages,
            display_text=result.display_text,
        )
