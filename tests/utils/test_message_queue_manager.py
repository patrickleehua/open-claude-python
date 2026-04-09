from __future__ import annotations

from open_claude.utils.message_queue_manager import (
    QueuedCommand,
    clear,
    dequeue,
    drain_pending_task_notifications,
    enqueue,
    get_commands_by_max_priority,
    peek,
    remove_commands,
)


def setup_function() -> None:
    clear()


def teardown_function() -> None:
    clear()


def test_queue_prioritizes_now_then_next_then_later() -> None:
    enqueue(QueuedCommand(value="later", priority="later"))
    enqueue(QueuedCommand(value="next", priority="next"))
    enqueue(QueuedCommand(value="now", priority="now"))

    assert peek().value == "now"
    assert dequeue().value == "now"
    assert dequeue().value == "next"
    assert dequeue().value == "later"


def test_get_commands_by_max_priority_and_remove() -> None:
    prompt = QueuedCommand(value="prompt", priority="next", mode="prompt")
    notif = QueuedCommand(value="notif", priority="later", mode="task-notification")
    enqueue(prompt)
    enqueue(notif)

    assert [cmd.value for cmd in get_commands_by_max_priority("next")] == ["prompt"]
    assert [cmd.value for cmd in get_commands_by_max_priority("later")] == ["prompt", "notif"]

    remove_commands([prompt])

    assert dequeue().value == "notif"


def test_drain_pending_task_notifications_moves_task_messages_into_queue(monkeypatch) -> None:
    monkeypatch.setattr(
        "open_claude.tasks.local_agent_task.drain_pending_notifications",
        lambda: ["<task-notification>done</task-notification>"],
    )

    drained = drain_pending_task_notifications()

    assert len(drained) == 1
    assert drained[0].mode == "task-notification"
    assert drained[0].priority == "later"
    assert peek().value == "<task-notification>done</task-notification>"
