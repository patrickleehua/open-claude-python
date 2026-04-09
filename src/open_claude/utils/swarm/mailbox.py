"""Teammate Mailbox — file-based messaging system for agent swarms.

Each teammate has an inbox file at ``~/.claude/teams/{team_name}/inboxes/{agent_name}.json``.
Other teammates can write messages to it, and the recipient reads them as attachments.

Ported from ``Claude-Code-rev/src/utils/teammateMailbox.ts``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from filelock import FileLock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEAMMATE_MESSAGE_TAG: str = "teammate-message"

_LOCK_TIMEOUT: float = 10.0
"""Seconds to wait when acquiring a file lock."""

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_SANITISE_RE = re.compile(r"[^\w.\-]")


def _sanitize_component(name: str) -> str:
    """Return a filesystem-safe version of *name*."""
    return _SANITISE_RE.sub("_", name)


def _get_teams_dir() -> Path:
    """Return the base directory for team data (``~/.claude/teams``)."""
    return Path.home() / ".claude" / "teams"


def get_inbox_path(agent_name: str, team_name: str | None = None) -> Path:
    """Return the path to a teammate's inbox JSON file.

    Structure: ``~/.claude/teams/{team}/inboxes/{agent}.json``
    """
    team = team_name or os.environ.get("CLAUDE_CODE_TEAM_NAME", "default")
    safe_team = _sanitize_component(team)
    safe_agent = _sanitize_component(agent_name)
    return _get_teams_dir() / safe_team / "inboxes" / f"{safe_agent}.json"


async def _ensure_inbox_dir(team_name: str | None = None) -> None:
    """Create the inbox directory for a team if it doesn't exist."""
    team = team_name or os.environ.get("CLAUDE_CODE_TEAM_NAME", "default")
    safe_team = _sanitize_component(team)
    inbox_dir = _get_teams_dir() / safe_team / "inboxes"
    inbox_dir.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Core data model
# ---------------------------------------------------------------------------


@dataclass
class TeammateMessage:
    """A single message in a teammate's inbox."""

    from_: str
    text: str
    timestamp: str
    read: bool = False
    color: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Rename from_ -> from for JSON serialization
        d["from"] = d.pop("from_")
        # Drop None optional fields for cleaner JSON
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TeammateMessage:
        data = dict(data)
        data.setdefault("from_", data.pop("from", ""))
        data.setdefault("read", False)
        data.setdefault("color", None)
        data.setdefault("summary", None)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Mailbox read / write operations
# ---------------------------------------------------------------------------


async def read_mailbox(
    agent_name: str, team_name: str | None = None
) -> list[TeammateMessage]:
    """Read all messages from a teammate's inbox."""
    inbox_path = get_inbox_path(agent_name, team_name)
    try:
        raw = inbox_path.read_text(encoding="utf-8")
        items: list[dict[str, Any]] = json.loads(raw)
        return [TeammateMessage.from_dict(m) for m in items]
    except FileNotFoundError:
        return []
    except Exception:
        logger.exception("Failed to read inbox for %s", agent_name)
        return []


async def read_unread_messages(
    agent_name: str, team_name: str | None = None
) -> list[TeammateMessage]:
    """Return only unread messages from a teammate's inbox."""
    messages = await read_mailbox(agent_name, team_name)
    return [m for m in messages if not m.read]


async def write_to_mailbox(
    recipient_name: str,
    message: TeammateMessage,
    team_name: str | None = None,
) -> None:
    """Write a message to a teammate's inbox using file locking."""
    await _ensure_inbox_dir(team_name)
    inbox_path = get_inbox_path(recipient_name, team_name)
    lock_path = inbox_path.with_suffix(inbox_path.suffix + ".lock")

    # Ensure inbox file exists before locking
    if not inbox_path.exists():
        try:
            inbox_path.write_text("[]", encoding="utf-8")
        except OSError:
            logger.exception("Failed to create inbox file for %s", recipient_name)
            return

    lock = FileLock(str(lock_path), timeout=_LOCK_TIMEOUT)
    try:
        with lock:
            messages = await read_mailbox(recipient_name, team_name)
            new_msg = TeammateMessage(
                from_=message.from_,
                text=message.text,
                timestamp=message.timestamp,
                read=False,
                color=message.color,
                summary=message.summary,
            )
            messages.append(new_msg)
            inbox_path.write_text(
                json.dumps([m.to_dict() for m in messages], indent=2),
                encoding="utf-8",
            )
    except Exception:
        logger.exception("Failed to write to inbox for %s", recipient_name)


async def mark_message_as_read_by_index(
    agent_name: str,
    team_name: str | None,
    message_index: int,
) -> None:
    """Mark a specific message (by index) as read using file locking."""
    inbox_path = get_inbox_path(agent_name, team_name)
    lock_path = inbox_path.with_suffix(inbox_path.suffix + ".lock")
    lock = FileLock(str(lock_path), timeout=_LOCK_TIMEOUT)

    try:
        with lock:
            messages = await read_mailbox(agent_name, team_name)
            if message_index < 0 or message_index >= len(messages):
                return
            msg = messages[message_index]
            if msg.read:
                return
            messages[message_index] = TeammateMessage(
                from_=msg.from_,
                text=msg.text,
                timestamp=msg.timestamp,
                read=True,
                color=msg.color,
                summary=msg.summary,
            )
            inbox_path.write_text(
                json.dumps([m.to_dict() for m in messages], indent=2),
                encoding="utf-8",
            )
    except FileNotFoundError:
        return
    except Exception:
        logger.exception("mark_message_as_read_by_index failed for %s", agent_name)


async def mark_messages_as_read(
    agent_name: str, team_name: str | None = None
) -> None:
    """Mark all messages in a teammate's inbox as read using file locking."""
    inbox_path = get_inbox_path(agent_name, team_name)
    lock_path = inbox_path.with_suffix(inbox_path.suffix + ".lock")
    lock = FileLock(str(lock_path), timeout=_LOCK_TIMEOUT)

    try:
        with lock:
            messages = await read_mailbox(agent_name, team_name)
            if not messages:
                return
            for m in messages:
                m.read = True
            inbox_path.write_text(
                json.dumps([m.to_dict() for m in messages], indent=2),
                encoding="utf-8",
            )
    except FileNotFoundError:
        return
    except Exception:
        logger.exception("mark_messages_as_read failed for %s", agent_name)


async def mark_messages_as_read_by_predicate(
    agent_name: str,
    predicate: Any,  # Callable[[TeammateMessage], bool]
    team_name: str | None = None,
) -> None:
    """Mark only messages matching *predicate* as read, leaving others unread."""
    inbox_path = get_inbox_path(agent_name, team_name)
    lock_path = inbox_path.with_suffix(inbox_path.suffix + ".lock")
    lock = FileLock(str(lock_path), timeout=_LOCK_TIMEOUT)

    try:
        with lock:
            messages = await read_mailbox(agent_name, team_name)
            if not messages:
                return
            updated = [
                (
                    TeammateMessage(
                        from_=m.from_,
                        text=m.text,
                        timestamp=m.timestamp,
                        read=True,
                        color=m.color,
                        summary=m.summary,
                    )
                    if (not m.read and predicate(m))
                    else m
                )
                for m in messages
            ]
            inbox_path.write_text(
                json.dumps([m.to_dict() for m in updated], indent=2),
                encoding="utf-8",
            )
    except FileNotFoundError:
        return
    except Exception:
        logger.exception(
            "mark_messages_as_read_by_predicate failed for %s", agent_name
        )


async def clear_mailbox(
    agent_name: str, team_name: str | None = None
) -> None:
    """Clear a teammate's inbox (delete all messages).

    Only writes if the file already exists — never creates a new one.
    """
    inbox_path = get_inbox_path(agent_name, team_name)
    if not inbox_path.exists():
        return
    try:
        inbox_path.write_text("[]", encoding="utf-8")
    except Exception:
        logger.exception("Failed to clear inbox for %s", agent_name)


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


def format_teammate_messages(
    messages: list[TeammateMessage],
) -> str:
    """Format teammate messages as XML for attachment display."""
    parts: list[str] = []
    for m in messages:
        color_attr = f' color="{m.color}"' if m.color else ""
        summary_attr = f' summary="{m.summary}"' if m.summary else ""
        parts.append(
            f'<{TEAMMATE_MESSAGE_TAG} teammate_id="{m.from_}"'
            f"{color_attr}{summary_attr}>\n{m.text}\n</{TEAMMATE_MESSAGE_TAG}>"
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# TypedDict message types (structured protocol messages)
# ---------------------------------------------------------------------------


class IdleNotificationMessage(TypedDict, total=False):
    type: str  # 'idle_notification'
    from_: str
    timestamp: str
    idleReason: str  # 'available' | 'interrupted' | 'failed'
    summary: str
    completedTaskId: str
    completedStatus: str  # 'resolved' | 'blocked' | 'failed'
    failureReason: str


class PermissionRequestMessage(TypedDict, total=False):
    type: str  # 'permission_request'
    request_id: str
    agent_id: str
    tool_name: str
    tool_use_id: str
    description: str
    input: dict[str, Any]
    permission_suggestions: list[Any]


class PermissionResponseSuccess(TypedDict, total=False):
    type: str  # 'permission_response'
    request_id: str
    subtype: str  # 'success'
    response: dict[str, Any]


class PermissionResponseError(TypedDict, total=False):
    type: str  # 'permission_response'
    request_id: str
    subtype: str  # 'error'
    error: str


PermissionResponseMessage = PermissionResponseSuccess | PermissionResponseError


class ShutdownRequestMessage(TypedDict, total=False):
    type: str  # 'shutdown_request'
    requestId: str
    from_: str
    reason: str
    timestamp: str


class ShutdownApprovedMessage(TypedDict, total=False):
    type: str  # 'shutdown_approved'
    requestId: str
    from_: str
    timestamp: str
    paneId: str
    backendType: str


class ShutdownRejectedMessage(TypedDict, total=False):
    type: str  # 'shutdown_rejected'
    requestId: str
    from_: str
    reason: str
    timestamp: str


class PlanApprovalRequestMessage(TypedDict, total=False):
    type: str  # 'plan_approval_request'
    from_: str
    timestamp: str
    planFilePath: str
    planContent: str
    requestId: str


class PlanApprovalResponseMessage(TypedDict, total=False):
    type: str  # 'plan_approval_response'
    requestId: str
    approved: bool
    feedback: str
    timestamp: str
    permissionMode: str


class TaskAssignmentMessage(TypedDict, total=False):
    type: str  # 'task_assignment'
    taskId: str
    subject: str
    description: str
    assignedBy: str
    timestamp: str


class ModeSetRequestMessage(TypedDict, total=False):
    type: str  # 'mode_set_request'
    mode: str
    from_: str


# ---------------------------------------------------------------------------
# Factory functions — create structured messages
# ---------------------------------------------------------------------------


def create_idle_notification(
    agent_id: str,
    *,
    idle_reason: str | None = None,
    summary: str | None = None,
    completed_task_id: str | None = None,
    completed_status: str | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    """Create an idle notification message."""
    msg: dict[str, Any] = {
        "type": "idle_notification",
        "from": agent_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if idle_reason is not None:
        msg["idleReason"] = idle_reason
    if summary is not None:
        msg["summary"] = summary
    if completed_task_id is not None:
        msg["completedTaskId"] = completed_task_id
    if completed_status is not None:
        msg["completedStatus"] = completed_status
    if failure_reason is not None:
        msg["failureReason"] = failure_reason
    return msg


def create_permission_request_message(
    *,
    request_id: str,
    agent_id: str,
    tool_name: str,
    tool_use_id: str,
    description: str,
    input: dict[str, Any],
    permission_suggestions: list[Any] | None = None,
) -> dict[str, Any]:
    """Create a permission request message."""
    return {
        "type": "permission_request",
        "request_id": request_id,
        "agent_id": agent_id,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "description": description,
        "input": input,
        "permission_suggestions": permission_suggestions or [],
    }


def create_permission_response_message(
    *,
    request_id: str,
    subtype: str,
    error: str | None = None,
    updated_input: dict[str, Any] | None = None,
    permission_updates: list[Any] | None = None,
) -> dict[str, Any]:
    """Create a permission response message."""
    if subtype == "error":
        return {
            "type": "permission_response",
            "request_id": request_id,
            "subtype": "error",
            "error": error or "Permission denied",
        }
    return {
        "type": "permission_response",
        "request_id": request_id,
        "subtype": "success",
        "response": {
            "updated_input": updated_input,
            "permission_updates": permission_updates,
        },
    }


def create_shutdown_request_message(
    *,
    request_id: str,
    from_: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Create a shutdown request message."""
    msg: dict[str, Any] = {
        "type": "shutdown_request",
        "requestId": request_id,
        "from": from_,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if reason is not None:
        msg["reason"] = reason
    return msg


def create_shutdown_approved_message(
    *,
    request_id: str,
    from_: str,
    pane_id: str | None = None,
    backend_type: str | None = None,
) -> dict[str, Any]:
    """Create a shutdown approved message."""
    msg: dict[str, Any] = {
        "type": "shutdown_approved",
        "requestId": request_id,
        "from": from_,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if pane_id is not None:
        msg["paneId"] = pane_id
    if backend_type is not None:
        msg["backendType"] = backend_type
    return msg


def create_shutdown_rejected_message(
    *,
    request_id: str,
    from_: str,
    reason: str,
) -> dict[str, Any]:
    """Create a shutdown rejected message."""
    return {
        "type": "shutdown_rejected",
        "requestId": request_id,
        "from": from_,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def create_mode_set_request_message(
    *,
    mode: str,
    from_: str,
) -> dict[str, Any]:
    """Create a mode set request message."""
    return {
        "type": "mode_set_request",
        "mode": mode,
        "from": from_,
    }


# ---------------------------------------------------------------------------
# Type detection helpers
# ---------------------------------------------------------------------------

_PROTOCOL_TYPES = frozenset(
    {
        "permission_request",
        "permission_response",
        "sandbox_permission_request",
        "sandbox_permission_response",
        "shutdown_request",
        "shutdown_approved",
        "team_permission_update",
        "mode_set_request",
        "plan_approval_request",
        "plan_approval_response",
    }
)


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """Attempt to parse *text* as a JSON dict; return ``None`` on failure."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def is_idle_notification(text: str) -> dict[str, Any] | None:
    """Check if *text* is an idle notification message."""
    parsed = _try_parse_json(text)
    if parsed and parsed.get("type") == "idle_notification":
        return parsed
    return None


def is_permission_request(text: str) -> dict[str, Any] | None:
    """Check if *text* is a permission request message."""
    parsed = _try_parse_json(text)
    if parsed and parsed.get("type") == "permission_request":
        return parsed
    return None


def is_permission_response(text: str) -> dict[str, Any] | None:
    """Check if *text* is a permission response message."""
    parsed = _try_parse_json(text)
    if parsed and parsed.get("type") == "permission_response":
        return parsed
    return None


def is_shutdown_request(text: str) -> dict[str, Any] | None:
    """Check if *text* is a shutdown request message."""
    parsed = _try_parse_json(text)
    if parsed and parsed.get("type") == "shutdown_request":
        return parsed
    return None


def is_shutdown_approved(text: str) -> dict[str, Any] | None:
    """Check if *text* is a shutdown approved message."""
    parsed = _try_parse_json(text)
    if parsed and parsed.get("type") == "shutdown_approved":
        return parsed
    return None


def is_shutdown_rejected(text: str) -> dict[str, Any] | None:
    """Check if *text* is a shutdown rejected message."""
    parsed = _try_parse_json(text)
    if parsed and parsed.get("type") == "shutdown_rejected":
        return parsed
    return None


def is_plan_approval_request(text: str) -> dict[str, Any] | None:
    """Check if *text* is a plan approval request message."""
    parsed = _try_parse_json(text)
    if parsed and parsed.get("type") == "plan_approval_request":
        return parsed
    return None


def is_plan_approval_response(text: str) -> dict[str, Any] | None:
    """Check if *text* is a plan approval response message."""
    parsed = _try_parse_json(text)
    if parsed and parsed.get("type") == "plan_approval_response":
        return parsed
    return None


def is_task_assignment(text: str) -> dict[str, Any] | None:
    """Check if *text* is a task assignment message."""
    parsed = _try_parse_json(text)
    if parsed and parsed.get("type") == "task_assignment":
        return parsed
    return None


def is_mode_set_request(text: str) -> dict[str, Any] | None:
    """Check if *text* is a mode set request message."""
    parsed = _try_parse_json(text)
    if parsed and parsed.get("type") == "mode_set_request":
        return parsed
    return None


def is_structured_protocol_message(text: str) -> bool:
    """Check if *text* is any structured protocol message.

    These message types have specific handlers and should be routed by the
    inbox poller rather than consumed as raw LLM context.
    """
    parsed = _try_parse_json(text)
    if not parsed:
        return False
    return parsed.get("type") in _PROTOCOL_TYPES
