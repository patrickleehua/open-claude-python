"""SendMessageTool - inter-agent communication for swarm mode.

Port of Claude-Code-rev SendMessageTool.ts.  Allows agents to send messages
to specific teammates or broadcast to the entire team.

Only enabled when swarm mode is active (``is_swarm_mode()`` returns True).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError
from open_claude.utils.swarm.mailbox import (
    TeammateMessage,
    write_to_mailbox,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class SendMessageInput(BaseModel):
    """Input schema for the SendMessage tool."""

    to: str = Field(
        description=(
            "The name of the teammate to send the message to, "
            'or "*" to broadcast to all teammates except yourself'
        ),
    )
    message: str = Field(
        description="The message content to send",
    )
    summary: str | None = Field(
        default=None,
        description="Optional short summary of the message for mailbox previews",
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


class SendMessageTool(Tool):
    """Send a message to a teammate or broadcast to the team."""

    @property
    def name(self) -> str:
        return "SendMessage"

    @property
    def input_schema(self) -> type[BaseModel]:
        return SendMessageInput

    @property
    def description(self) -> str:
        return (
            "Send a message to a teammate or broadcast to the team.\n"
            "\n"
            "Use this tool to communicate with other agents in your team. "
            'Send to a specific teammate by name, or use "*" to broadcast.\n'
            "\n"
            "IMPORTANT: This is the ONLY way to communicate with other agents. "
            "Just writing a response in text is NOT visible to others.\n"
            "\n"
            "Usage:\n"
            '- Use `to: "<name>"` to send a message to a specific teammate\n'
            '- Use `to: "*"` sparingly for team-wide broadcasts\n'
            "- Include a summary for longer messages so recipients can "
            "quickly scan their inbox"
        )

    def is_enabled(self) -> bool:
        """Only enabled when swarm mode is active."""
        from open_claude.utils.swarm.constants import is_swarm_mode

        return is_swarm_mode()

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return True

    def is_read_only(self, input_data: BaseModel) -> bool:
        data = input_data  # type: SendMessageInput
        return isinstance(data.message, str)

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: SendMessageInput
        sender = _get_current_identity()
        team_name = os.environ.get("CLAUDE_CODE_TEAM_NAME", "default")
        timestamp = datetime.now(timezone.utc).isoformat()

        msg = TeammateMessage(
            from_=sender,
            text=data.message,
            timestamp=timestamp,
            summary=data.summary,
        )

        # Broadcast path.
        if data.to == "*":
            return await self._broadcast(sender, msg, team_name)

        # Direct message path.
        return await self._send_direct(data.to, msg, team_name)

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def _broadcast(
        self,
        sender: str,
        msg: TeammateMessage,
        team_name: str,
    ) -> str:
        """Send to all registered teammates except *sender*."""
        from open_claude.tasks.local_agent_task import get_all_tasks

        tasks = get_all_tasks()
        recipients: list[str] = []
        errors: list[str] = []

        for task_id, task in tasks.items():
            name = _task_display_name(task)
            if not name or name == sender:
                continue
            if task.status != "running":
                continue
            try:
                await write_to_mailbox(name, msg, team_name)
                recipients.append(name)
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        parts: list[str] = []
        if recipients:
            parts.append(f"Broadcast sent to: {', '.join(recipients)}")
        else:
            parts.append("No active teammates found for broadcast.")
        if errors:
            parts.append(f"Errors: {'; '.join(errors)}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Direct message
    # ------------------------------------------------------------------

    async def _send_direct(
        self,
        recipient: str,
        msg: TeammateMessage,
        team_name: str,
    ) -> str:
        """Send a message to a specific teammate."""
        # First try to match by registered agent name.
        target_task = _find_task_by_name(recipient)
        if target_task is not None:
            from open_claude.tasks.local_agent_task import (
                queue_pending_message,
            )

            # For in-process teammates, also queue as a pending message so
            # it is picked up at the next tool-round boundary.
            queue_pending_message(target_task.task_id, msg.text)

        # Always write to the mailbox as the canonical delivery channel.
        try:
            await write_to_mailbox(recipient, msg, team_name)
            return f"Message sent to {recipient}."
        except Exception as exc:
            logger.exception("SendMessage: failed for %s", recipient)
            raise ToolError(f"Failed to send message to {recipient}: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_current_identity() -> str:
    """Return the current agent's identity name.

    Falls back to environment variable, then "team-lead".
    """
    return (
        os.environ.get("CLAUDE_CODE_AGENT_NAME")
        or os.environ.get("CLAUDE_CODE_TEAMMATE_NAME")
        or "team-lead"
    )


def _task_display_name(task) -> str:
    """Extract a display name from a task's stored metadata."""
    # description is used as the display name during registration.
    if task.description:
        return task.description
    selected = task.selected_agent or {}
    return selected.get("name", "")


def _find_task_by_name(name: str):
    """Find a running task whose display name matches *name*."""
    from open_claude.tasks.local_agent_task import get_all_tasks

    for task_id, task in get_all_tasks().items():
        if task.status != "running":
            continue
        display = _task_display_name(task)
        if display and display.lower() == name.lower():
            return task
    return None
