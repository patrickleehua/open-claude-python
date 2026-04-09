"""Local agent task state machine — ported from Claude-Code-rev LocalAgentTask.tsx.

Manages background/foreground agent lifecycle: registration, progress tracking,
completion, failure, kill, and notification.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------------------
# XML tag constants (matching TS constants/xml.ts)
# ---------------------------------------------------------------------------
TASK_NOTIFICATION_TAG = "task-notification"
TASK_ID_TAG = "taskId"
TOOL_USE_ID_TAG = "toolUseId"
OUTPUT_FILE_TAG = "output_file"
STATUS_TAG = "status"
SUMMARY_TAG = "summary"
WORKTREE_TAG = "worktree"
WORKTREE_PATH_TAG = "worktree_path"
WORKTREE_BRANCH_TAG = "worktree_branch"

PANEL_GRACE_MS = 5000  # grace period before evicting panel tasks

# ---------------------------------------------------------------------------
# Tool activity / agent progress dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ToolActivity:
    """A single tool invocation tracked for progress display."""

    tool_name: str
    input: dict[str, Any]
    activity_description: str | None = None
    is_search: bool | None = None
    is_read: bool | None = None


@dataclass
class AgentProgress:
    """Snapshot of an agent's progress at a point in time."""

    tool_use_count: int = 0
    token_count: int = 0
    last_activity: ToolActivity | None = None
    recent_activities: list[ToolActivity] = field(default_factory=list)
    summary: str | None = None


MAX_RECENT_ACTIVITIES = 5


@dataclass
class ProgressTracker:
    """Mutable accumulator for agent progress across turns."""

    tool_use_count: int = 0
    latest_input_tokens: int = 0
    cumulative_output_tokens: int = 0
    recent_activities: list[ToolActivity] = field(default_factory=list)


def create_progress_tracker() -> ProgressTracker:
    return ProgressTracker()


def get_token_count_from_tracker(tracker: ProgressTracker) -> int:
    return tracker.latest_input_tokens + tracker.cumulative_output_tokens


def update_progress_from_message(
    tracker: ProgressTracker,
    message: dict[str, Any],
) -> None:
    """Update tracker from an assistant message's usage and tool_use blocks."""
    if message.get("type") != "assistant":
        return
    msg = message.get("message", message)
    usage = msg.get("usage", {})
    tracker.latest_input_tokens = (
        usage.get("input_tokens", 0)
        + (usage.get("cache_creation_input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0)
    )
    tracker.cumulative_output_tokens += usage.get("output_tokens", 0)

    content = msg.get("content", [])
    for block in content:
        if block.get("type") == "tool_use":
            tracker.tool_use_count += 1
            tracker.recent_activities.append(
                ToolActivity(
                    tool_name=block.get("name", ""),
                    input=block.get("input", {}),
                )
            )
    while len(tracker.recent_activities) > MAX_RECENT_ACTIVITIES:
        tracker.recent_activities.pop(0)


def get_progress_update(tracker: ProgressTracker) -> AgentProgress:
    return AgentProgress(
        tool_use_count=tracker.tool_use_count,
        token_count=get_token_count_from_tracker(tracker),
        last_activity=tracker.recent_activities[-1] if tracker.recent_activities else None,
        recent_activities=list(tracker.recent_activities),
    )


# ---------------------------------------------------------------------------
# Task state
# ---------------------------------------------------------------------------


@dataclass
class LocalAgentTaskState:
    """Full state for a running local_agent task."""

    type: str = "local_agent"
    status: str = "running"  # running | completed | failed | killed
    task_id: str = ""
    agent_id: str = ""
    prompt: str = ""
    description: str = ""
    agent_type: str = "general-purpose"
    model: str | None = None
    start_time: float = field(default_factory=lambda: time.time() * 1000)
    end_time: float | None = None
    tool_use_id: str | None = None

    # Agent definition (stored as dict to avoid circular imports)
    selected_agent: dict[str, Any] | None = None

    # Abort
    abort_event: asyncio.Event | None = None

    # Progress
    progress: AgentProgress | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    # Tracking
    retrieved: bool = False
    last_reported_tool_count: int = 0
    last_reported_token_count: int = 0
    is_backgrounded: bool = True
    pending_messages: list[str] = field(default_factory=list)
    retain: bool = False
    disk_loaded: bool = False
    evict_after: float | None = None
    notified: bool = False

    # Messages accumulated by the agent
    messages: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Module-level task store (replaces TS AppState.tasks)
# ---------------------------------------------------------------------------
_tasks: dict[str, LocalAgentTaskState] = {}
_tasks_lock = asyncio.Lock()


def _get_task(task_id: str) -> LocalAgentTaskState | None:
    return _tasks.get(task_id)


async def _set_task(task: LocalAgentTaskState) -> None:
    async with _tasks_lock:
        _tasks[task.task_id] = task


async def _remove_task(task_id: str) -> None:
    async with _tasks_lock:
        _tasks.pop(task_id, None)


def is_local_agent_task(task: Any) -> bool:
    return isinstance(task, LocalAgentTaskState)


def get_all_tasks() -> dict[str, LocalAgentTaskState]:
    return dict(_tasks)


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

# Pending notifications queue (consumed by the main loop)
_pending_notifications: list[str] = []


def enqueue_pending_notification(value: str, mode: str = "task-notification") -> None:
    _pending_notifications.append(value)


def drain_pending_notifications() -> list[str]:
    notifications = list(_pending_notifications)
    _pending_notifications.clear()
    return notifications


def enqueue_agent_notification(
    *,
    task_id: str,
    description: str,
    status: str,
    error: str | None = None,
    final_message: str | None = None,
    usage: dict[str, int] | None = None,
    tool_use_id: str | None = None,
    worktree_path: str | None = None,
    worktree_branch: str | None = None,
) -> None:
    """Build and enqueue a <task-notification> XML message."""
    task = _get_task(task_id)
    if task is not None and task.notified:
        return
    if task is not None:
        task.notified = True

    summary = (
        f'Agent "{description}" completed'
        if status == "completed"
        else f'Agent "{description}" failed: {error or "Unknown error"}'
        if status == "failed"
        else f'Agent "{description}" was stopped'
    )

    tool_use_id_line = (
        f"\n<{TOOL_USE_ID_TAG}>{tool_use_id}</{TOOL_USE_ID_TAG}>" if tool_use_id else ""
    )
    result_section = f"\n<result>{final_message}</result>" if final_message else ""
    usage_section = ""
    if usage:
        usage_section = (
            f"\n<usage>"
            f"<total_tokens>{usage.get('total_tokens', 0)}</total_tokens>"
            f"<tool_uses>{usage.get('tool_uses', 0)}</tool_uses>"
            f"<duration_ms>{usage.get('duration_ms', 0)}</duration_ms>"
            f"</usage>"
        )
    worktree_section = ""
    if worktree_path:
        branch_part = (
            f"<{WORKTREE_BRANCH_TAG}>{worktree_branch}</{WORKTREE_BRANCH_TAG}>"
            if worktree_branch
            else ""
        )
        worktree_section = (
            f"\n<{WORKTREE_TAG}>"
            f"<{WORKTREE_PATH_TAG}>{worktree_path}</{WORKTREE_PATH_TAG}>"
            f"{branch_part}"
            f"</{WORKTREE_TAG}>"
        )

    output_path = f".claude/tasks/{task_id}"

    message = (
        f"<{TASK_NOTIFICATION_TAG}>\n"
        f"<{TASK_ID_TAG}>{task_id}</{TASK_ID_TAG}>{tool_use_id_line}\n"
        f"<{OUTPUT_FILE_TAG}>{output_path}</{OUTPUT_FILE_TAG}>\n"
        f"<{STATUS_TAG}>{status}</{STATUS_TAG}>\n"
        f"<{SUMMARY_TAG}>{summary}</{SUMMARY_TAG}>"
        f"{result_section}{usage_section}{worktree_section}\n"
        f"</{TASK_NOTIFICATION_TAG}>"
    )

    enqueue_pending_notification(message)


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------


async def register_async_agent(
    *,
    agent_id: str,
    description: str,
    prompt: str,
    selected_agent: dict[str, Any] | None = None,
    parent_abort_event: asyncio.Event | None = None,
    tool_use_id: str | None = None,
) -> LocalAgentTaskState:
    """Register a new background agent task."""
    abort_event = asyncio.Event()

    task = LocalAgentTaskState(
        task_id=agent_id,
        agent_id=agent_id,
        description=description,
        prompt=prompt,
        selected_agent=selected_agent,
        agent_type=(selected_agent or {}).get("agent_type", "general-purpose"),
        abort_event=abort_event,
        is_backgrounded=True,
    )
    if tool_use_id:
        task.tool_use_id = tool_use_id

    await _set_task(task)
    return task


async def register_agent_foreground(
    *,
    agent_id: str,
    description: str,
    prompt: str,
    selected_agent: dict[str, Any] | None = None,
    tool_use_id: str | None = None,
    auto_background_ms: int | None = None,
) -> tuple[str, asyncio.Event, Callable[[], None] | None]:
    """Register a foreground agent task that may be backgrounded later.

    Returns (task_id, background_event, cancel_auto_background).
    """
    task = LocalAgentTaskState(
        task_id=agent_id,
        agent_id=agent_id,
        description=description,
        prompt=prompt,
        selected_agent=selected_agent,
        agent_type=(selected_agent or {}).get("agent_type", "general-purpose"),
        is_backgrounded=False,
    )
    if tool_use_id:
        task.tool_use_id = tool_use_id

    await _set_task(task)

    background_event = asyncio.Event()
    cancel_timer: Callable[[], None] | None = None

    if auto_background_ms and auto_background_ms > 0:

        async def _auto_background() -> None:
            await asyncio.sleep(auto_background_ms / 1000.0)
            t = _get_task(agent_id)
            if t and not t.is_backgrounded:
                t.is_backgrounded = True
                background_event.set()

        handle = asyncio.ensure_future(_auto_background())

        def _cancel() -> None:
            handle.cancel()

        cancel_timer = _cancel

    return agent_id, background_event, cancel_timer


async def complete_agent_task(result: dict[str, Any]) -> None:
    """Mark a task as completed with result."""
    task_id = result.get("agent_id", "")
    async with _tasks_lock:
        task = _tasks.get(task_id)
        if task is None or task.status != "running":
            return
        task.status = "completed"
        task.result = result
        task.end_time = time.time() * 1000
        task.abort_event = None
        task.selected_agent = None


async def fail_agent_task(task_id: str, error: str) -> None:
    """Mark a task as failed."""
    async with _tasks_lock:
        task = _tasks.get(task_id)
        if task is None or task.status != "running":
            return
        task.status = "failed"
        task.error = error
        task.end_time = time.time() * 1000
        task.abort_event = None
        task.selected_agent = None


async def kill_async_agent(task_id: str) -> None:
    """Kill a running agent. No-op if already terminal."""
    async with _tasks_lock:
        task = _tasks.get(task_id)
        if task is None or task.status != "running":
            return
        if task.abort_event:
            task.abort_event.set()
        task.status = "killed"
        task.end_time = time.time() * 1000
        task.abort_event = None
        task.selected_agent = None


async def kill_all_running_agent_tasks() -> None:
    """Kill all running agent tasks."""
    for task_id, task in list(_tasks.items()):
        if task.status == "running":
            await kill_async_agent(task_id)


def update_agent_progress(task_id: str, progress: AgentProgress) -> None:
    """Update progress, preserving any existing summary."""
    task = _get_task(task_id)
    if task is None or task.status != "running":
        return
    existing_summary = task.progress.summary if task.progress else None
    if existing_summary:
        progress.summary = existing_summary
    task.progress = progress


def queue_pending_message(task_id: str, msg: str) -> None:
    """Queue a message for delivery at the next tool-round boundary."""
    task = _get_task(task_id)
    if task is None:
        return
    task.pending_messages.append(msg)


def drain_pending_messages(task_id: str) -> list[str]:
    """Drain and return all pending messages for a task."""
    task = _get_task(task_id)
    if task is None or not task.pending_messages:
        return []
    drained = list(task.pending_messages)
    task.pending_messages.clear()
    return drained


def background_agent_task(task_id: str) -> bool:
    """Background a foreground agent task. Returns True if backgrounded."""
    task = _get_task(task_id)
    if task is None or task.is_backgrounded:
        return False
    task.is_backgrounded = True
    return True


async def unregister_agent_foreground(task_id: str) -> None:
    """Remove a foreground task that completed without being backgrounded."""
    task = _get_task(task_id)
    if task is None or task.is_backgrounded:
        return
    await _remove_task(task_id)
