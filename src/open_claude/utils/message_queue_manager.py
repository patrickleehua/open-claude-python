"""Prioritized command queue shared by the chat UI and query engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Literal

QueuePriority = Literal["now", "next", "later"]
QueueMode = Literal["prompt", "slash", "task-notification"]

_PRIORITY_ORDER: dict[QueuePriority, int] = {
    "now": 0,
    "next": 1,
    "later": 2,
}


@dataclass(slots=True)
class QueuedCommand:
    value: str
    mode: QueueMode = "prompt"
    priority: QueuePriority = "next"
    uuid: str | None = None
    agent_id: str | None = None
    rendered: bool = False
    created_at: float = field(default_factory=monotonic)


_command_queue: list[QueuedCommand] = []


def enqueue(command: QueuedCommand) -> None:
    _command_queue.append(command)


def enqueue_task_notification(value: str, priority: QueuePriority = "later") -> None:
    enqueue(QueuedCommand(value=value, mode="task-notification", priority=priority))


def peek(filter_fn=None) -> QueuedCommand | None:
    best_idx = _find_best_index(filter_fn)
    if best_idx is None:
        return None
    return _command_queue[best_idx]


def dequeue(filter_fn=None) -> QueuedCommand | None:
    best_idx = _find_best_index(filter_fn)
    if best_idx is None:
        return None
    return _command_queue.pop(best_idx)


def get_commands_by_max_priority(
    max_priority: QueuePriority,
    *,
    filter_fn=None,
) -> list[QueuedCommand]:
    max_value = _PRIORITY_ORDER[max_priority]
    commands = [
        cmd
        for cmd in _command_queue
        if _PRIORITY_ORDER[cmd.priority] <= max_value and (filter_fn is None or filter_fn(cmd))
    ]
    return sorted(
        commands,
        key=lambda cmd: (_PRIORITY_ORDER[cmd.priority], cmd.created_at),
    )


def remove_commands(commands: list[QueuedCommand]) -> None:
    if not commands:
        return
    ids = {id(cmd) for cmd in commands}
    _command_queue[:] = [cmd for cmd in _command_queue if id(cmd) not in ids]


def has_commands(filter_fn=None) -> bool:
    return peek(filter_fn) is not None


def queue_length(filter_fn=None) -> int:
    if filter_fn is None:
        return len(_command_queue)
    return sum(1 for cmd in _command_queue if filter_fn(cmd))


def snapshot() -> list[QueuedCommand]:
    return list(_command_queue)


def clear() -> None:
    _command_queue.clear()


def drain_pending_task_notifications() -> list[QueuedCommand]:
    try:
        from open_claude.tasks.local_agent_task import drain_pending_notifications
    except Exception:
        return []

    drained = drain_pending_notifications()
    commands = [
        QueuedCommand(value=value, mode="task-notification", priority="later")
        for value in drained
    ]
    for cmd in commands:
        enqueue(cmd)
    return commands


def _find_best_index(filter_fn=None) -> int | None:
    best_idx: int | None = None
    best_priority = float("inf")

    for idx, cmd in enumerate(_command_queue):
        if filter_fn is not None and not filter_fn(cmd):
            continue
        priority = _PRIORITY_ORDER[cmd.priority]
        if priority < best_priority:
            best_priority = priority
            best_idx = idx

    return best_idx
