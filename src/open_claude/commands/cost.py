"""/cost command — show session token usage and estimated cost.

Mirrors ``Claude-Code-rev/src/commands/cost/cost.ts``.
"""

from __future__ import annotations

from open_claude.commands.base import CommandResult, CommandResultType, LocalCommand


# Rough per-1K-token USD prices (Claude Sonnet 4 pricing as of 2025-06).
# Users can override via settings.json if needed.
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {
        "input": 3.0 / 1_000_000,
        "output": 15.0 / 1_000_000,
    },
    "default": {
        "input": 3.0 / 1_000_000,
        "output": 15.0 / 1_000_000,
    },
}


def _format_cost(usage, model: str) -> str:
    """Build a human-readable cost string from a TokenUsage object."""
    prices = _DEFAULT_PRICES.get(model, _DEFAULT_PRICES["default"])
    input_cost = usage.input_tokens * prices["input"]
    output_cost = usage.output_tokens * prices["output"]
    total_cost = input_cost + output_cost

    lines = [
        f"[bold]Session Usage[/bold]",
        f"  Input tokens:  {usage.input_tokens:,}",
        f"  Output tokens: {usage.output_tokens:,}",
        f"  Total tokens:  {usage.get_total_tokens():,}",
    ]

    cache_total = usage.get_total_cache_tokens()
    if cache_total > 0:
        lines.append(f"  Cache tokens:  {cache_total:,}")

    lines.append("")
    lines.append(f"[bold]Estimated cost:[/bold] ${total_cost:.4f}")

    return "\n".join(lines)


class CostCommand(LocalCommand):
    name = "cost"
    description = "Show the total cost and duration of the current session"

    async def execute(self, args: str, context) -> CommandResult:  # type: ignore[override]
        usage = context.token_usage
        model = getattr(context, "model_name", "unknown")
        value = _format_cost(usage, model)
        return CommandResult(type=CommandResultType.TEXT, value=value)
