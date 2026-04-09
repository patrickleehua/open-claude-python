"""Interactive permission UI components.

Ported from Claude-Code-rev src/components/permissions/.
In the Textual TUI, these would be actual widgets.
For now, implements a simple stdin/stdout prompt.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from open_claude.schemas.permissions import (
    PermissionAllowDecision,
    PermissionAskDecision,
    PermissionDecision,
    PermissionDenyDecision,
    PermissionUpdate,
    ToolPermissionContext,
)
from open_claude.hooks.tool_permission import create_permission_context
from open_claude.utils.diff import display_data_for_preview, preview_for_tool_input

logger = logging.getLogger(__name__)


class PermissionPromptResult:
    """Result from an interactive permission prompt."""

    def __init__(
        self,
        approved: bool,
        permanent: bool = False,
        feedback: str | None = None,
    ):
        self.approved = approved
        self.permanent = permanent
        self.feedback = feedback


async def prompt_for_permission(
    tool_name: str,
    tool_input: dict[str, Any],
    message: str,
    *,
    suggestions: list[PermissionUpdate] | None = None,
    timeout_seconds: float | None = None,
) -> PermissionPromptResult:
    """Show an interactive permission prompt in the terminal.

    Returns:
        PermissionPromptResult with the user's decision.
    """
    console = Console()

    # Display the permission request
    console.print()
    console.print(
        Panel(
            Text(message, style="yellow"),
            title=f"[Permission Required] {tool_name}",
            border_style="yellow",
        )
    )

    # Show tool input summary
    preview = preview_for_tool_input(tool_name, tool_input)
    preview_display = display_data_for_preview(
        preview,
        tool_name=tool_name,
        status="preview",
        dim=False,
    )
    input_summary = preview_display["markup"] if preview_display else _format_tool_input(tool_name, tool_input)
    if input_summary:
        console.print(input_summary)

    # Prompt the user
    console.print()
    console.print("  [1] Allow once  [2] Allow always (session)  [3] Deny")

    try:
        if timeout_seconds:
            choice = await asyncio.wait_for(
                _async_input("  Choose [1-3]: "),
                timeout=timeout_seconds,
            )
        else:
            choice = await _async_input("  Choose [1-3]: ")
    except asyncio.TimeoutError:
        console.print("\n  [red]Permission request timed out — denied.[/red]")
        return PermissionPromptResult(approved=False)
    except (EOFError, KeyboardInterrupt):
        console.print("\n  [red]Permission request cancelled.[/red]")
        return PermissionPromptResult(approved=False)

    choice = (choice or "").strip()

    if choice == "1":
        return PermissionPromptResult(approved=True, permanent=False)
    elif choice == "2":
        return PermissionPromptResult(approved=True, permanent=True)
    else:
        return PermissionPromptResult(approved=False)


async def _async_input(prompt: str) -> str:
    """Async wrapper around input()."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, input, prompt)


def _format_tool_input(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Format tool input for display in permission prompts."""
    if tool_name == "Bash":
        return tool_input.get("command", "")
    if tool_name in ("Read", "Write", "Edit"):
        return tool_input.get("file_path", "")
    if tool_name == "Glob":
        return tool_input.get("pattern", "")
    if tool_name == "Grep":
        return tool_input.get("pattern", "")
    return str(tool_input)[:200]


async def interactive_permission_check(
    tool_name: str,
    tool_input: dict[str, Any],
    permission_context: ToolPermissionContext,
    *,
    set_permission_context: Any = None,
    tool_use_id: str = "",
    decision: PermissionAskDecision | None = None,
    abort_signal: asyncio.Event | None = None,
) -> PermissionDecision:
    """Run the full interactive permission flow.

    If the decision is an 'ask', prompt the user interactively.
    If 'allow' or 'deny', pass through.
    """
    if decision is None:
        return PermissionDenyDecision(message="No permission decision provided.")

    if decision.behavior != "ask":
        return decision

    # Need to prompt the user
    result = await prompt_for_permission(
        tool_name=tool_name,
        tool_input=tool_input,
        message=decision.message,
        suggestions=getattr(decision, "suggestions", None),
    )

    if result.approved:
        updates: list[PermissionUpdate] = []
        if result.permanent:
            from open_claude.schemas.permissions import (
                AddRulesUpdate,
                PermissionBehavior,
                PermissionRuleValue,
                PermissionUpdateDestination,
            )

            updates.append(
                AddRulesUpdate(
                    destination=PermissionUpdateDestination.SESSION,
                    rules=[PermissionRuleValue(tool_name=tool_name)],
                    behavior=PermissionBehavior.ALLOW,
                )
            )

        ctx = create_permission_context(
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id=tool_use_id,
            permission_context=permission_context,
            set_permission_context=set_permission_context,
            abort_signal=abort_signal,
        )
        return await ctx.handle_user_allow(
            updated_input=tool_input,
            permission_updates=updates,
            feedback=result.feedback,
            decision_reason=getattr(decision, "decision_reason", None),
            display_data=preview_display,
        )
    else:
        return PermissionDenyDecision(
            message=f"User denied permission for {tool_name}."
            + (f" Feedback: {result.feedback}" if result.feedback else ""),
            display_data=display_data_for_preview(
                preview,
                tool_name=tool_name,
                status="rejected",
                dim=True,
            ),
        )
