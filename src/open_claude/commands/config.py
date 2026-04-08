"""/config command — show or edit runtime settings.

Mirrors ``Claude-Code-rev/src/commands/config/config.tsx`` (simplified for TUI).
"""

from __future__ import annotations

import json

from open_claude.commands.base import CommandResult, CommandResultType, LocalCommand


class ConfigCommand(LocalCommand):
    name = "config"
    description = "Show current configuration"
    aliases = ["settings"]

    async def execute(self, args: str, context) -> CommandResult:  # type: ignore[override]
        settings = context.load_settings()

        # Mask sensitive fields
        safe = dict(settings.get("raw", settings))
        for key in ("api_key", "apiKey", "ANTHROPIC_API_KEY"):
            if key in safe and isinstance(safe[key], str) and len(safe[key]) > 4:
                safe[key] = safe[key][:4] + "..." + safe[key][-4:]

        formatted = json.dumps(safe, indent=2, ensure_ascii=False)
        value = f"[bold]Current configuration:[/bold]\n{formatted}"
        return CommandResult(type=CommandResultType.TEXT, value=value)
