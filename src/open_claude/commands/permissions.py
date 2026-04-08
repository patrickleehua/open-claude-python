"""/permissions command — inspect and switch permission mode."""

from __future__ import annotations

from open_claude.commands.base import CommandResult, CommandResultType, LocalCommand
from open_claude.schemas.permissions import PermissionMode


class PermissionsCommand(LocalCommand):
    name = "permissions"
    description = "Show or change the current permission mode"
    aliases = ["permission", "perm"]
    argument_hint = "[mode <default|auto|bypassPermissions|dontAsk|acceptEdits|plan>]"

    async def execute(self, args: str, context) -> CommandResult:  # type: ignore[override]
        raw = args.strip()

        if not raw:
            return CommandResult(
                type=CommandResultType.TEXT,
                value=self._render_summary(context.permission_context.mode),
            )

        parts = raw.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "mode":
            return CommandResult(
                type=CommandResultType.TEXT,
                value=(
                    "[yellow]Usage:[/yellow] /permissions mode <mode>\n"
                    + self._render_summary(context.permission_context.mode)
                ),
            )

        requested = parts[1].strip()
        try:
            mode = PermissionMode(requested)
        except ValueError:
            supported = ", ".join(mode.value for mode in PermissionMode)
            return CommandResult(
                type=CommandResultType.TEXT,
                value=f"[yellow]Unknown permission mode:[/yellow] {requested}\nSupported: {supported}",
            )

        context.set_permission_mode(mode)
        return CommandResult(
            type=CommandResultType.TEXT,
            value=self._render_summary(mode),
        )

    def _render_summary(self, mode: PermissionMode) -> str:
        supported = ", ".join(value.value for value in PermissionMode)
        return (
            f"[bold]Permission mode:[/bold] {mode.value}\n"
            f"[dim]Modes:[/dim] {supported}\n"
            "[dim]Tip:[/dim] tool requests now prompt inline with 1 allow once, 2 allow tool for session, 3 deny."
        )
