"""TaskStopTool - stops a running background agent task.

Referenced by the coordinator system prompt as ``TaskStop``.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class TaskStopInput(BaseModel):
    """Input schema for TaskStopTool."""

    task_id: str = Field(
        description="The ID of the agent task to stop",
    )
    reason: str | None = Field(
        default=None,
        description="Optional reason for stopping the task",
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


class TaskStopTool(Tool):
    """Stop a running background agent task."""

    @property
    def name(self) -> str:
        return "TaskStop"

    @property
    def input_schema(self) -> type[BaseModel]:
        return TaskStopInput

    @property
    def description(self) -> str:
        return (
            "Stop a running background agent task.\n"
            "\n"
            "Use this tool to terminate an agent that was previously launched "
            "with the Agent tool (in background mode). The agent will be "
            "stopped immediately and any partial results will be preserved.\n"
            "\n"
            "This is a no-op if the task is already completed or failed."
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return True

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: TaskStopInput

        from open_claude.tasks.local_agent_task import (
            _get_task,
            kill_async_agent,
        )

        task = _get_task(data.task_id)
        if task is None:
            raise ToolError(f"Task '{data.task_id}' not found.")

        if task.status != "running":
            return f"Task '{data.task_id}' is not running (status: {task.status}). No action taken."

        await kill_async_agent(data.task_id)
        logger.info(
            "TaskStop: killed agent %s reason=%s",
            data.task_id,
            data.reason or "unspecified",
        )
        reason_suffix = f" Reason: {data.reason}" if data.reason else ""
        return f"Task '{data.task_id}' has been stopped.{reason_suffix}"
