"""/help command — show available commands."""

from __future__ import annotations

from open_claude.commands.base import CommandResult, CommandResultType, LocalCommand
from open_claude.commands.registry import get_registry


class HelpCommand(LocalCommand):
    name = "help"
    description = "Show help and available commands"
    aliases: list[str] = []

    async def execute(self, args: str, context) -> CommandResult:  # type: ignore[override]
        registry = get_registry()
        visible = registry.get_visible()

        lines = ["[bold]Available commands:[/bold]\n"]

        # Compute max name width for alignment
        max_name_w = max((len(f"/{c.name}") for c in visible), default=10)

        for cmd in sorted(visible, key=lambda c: c.name):
            label = f"/{cmd.name}"
            if cmd.argument_hint:
                label += f" {cmd.argument_hint}"
            lines.append(f"  {label:<{max_name_w + 4}} {cmd.description}")
            for alias in cmd.aliases:
                lines.append(f"  {f'  (alias: /{alias})':>{max_name_w + 4}}")

        lines.append("")
        lines.append("[dim]Type /<command> to run. Use ↑/↓ to browse history.[/dim]")

        return CommandResult(
            type=CommandResultType.TEXT,
            value="\n".join(lines),
        )
