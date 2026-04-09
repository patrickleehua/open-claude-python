"""Persistent in-process agent loop -- ported from Claude-Code-rev inProcessRunner.ts.

Runs a teammate agent in a long-lived asyncio task that:
  1. Executes the initial prompt.
  2. Sends an idle notification when done.
  3. Polls the mailbox for new prompts or shutdown requests.
  4. Repeats until aborted or shutdown is approved.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from open_claude.tasks.local_agent_task import (
    LocalAgentTaskState,
    get_all_tasks,
    queue_pending_message,
    drain_pending_messages,
    fail_agent_task,
    complete_agent_task,
    _get_task,
)
from open_claude.utils.swarm.mailbox import (
    TeammateMessage,
    read_unread_messages,
    write_to_mailbox,
    mark_messages_as_read_by_predicate,
    create_idle_notification,
    is_shutdown_request,
    is_idle_notification,
)
from open_claude.utils.swarm.prompts import TEAMMATE_SYSTEM_PROMPT_ADDENDUM

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Polling constants
# ---------------------------------------------------------------------------

_MAILBOX_POLL_INTERVAL: float = 2.0
"""Seconds between mailbox polls."""

_IDLE_REASON_AVAILABLE = "available"
_IDLE_REASON_FAILED = "failed"

# ---------------------------------------------------------------------------
# Configuration & result types
# ---------------------------------------------------------------------------


@dataclass
class InProcessRunnerConfig:
    """Full configuration for the in-process runner loop."""

    identity: str
    task_id: str
    prompt: str
    agent_definition: dict[str, Any] | None = None
    abort_event: asyncio.Event | None = None
    model: str | None = None
    system_prompt: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    allow_permission_prompts: bool = False
    description: str = ""


@dataclass
class InProcessRunnerResult:
    """Outcome of the in-process runner loop."""

    success: bool
    error: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Message formatting helpers
# ---------------------------------------------------------------------------


def format_as_teammate_message(
    from_: str,
    content: str,
    color: str | None = None,
    summary: str | None = None,
) -> str:
    """Wrap *content* in an XML tag used for inter-agent messages."""
    color_attr = f' color="{color}"' if color else ""
    summary_attr = f' summary="{summary}"' if summary else ""
    return (
        f'<teammate-message teammate_id="{from_}"'
        f"{color_attr}{summary_attr}>\n"
        f"{content}\n"
        f"</teammate-message>"
    )


# ---------------------------------------------------------------------------
# Mailbox polling
# ---------------------------------------------------------------------------


async def wait_for_next_prompt_or_shutdown(
    identity: str,
    abort_event: asyncio.Event,
    task_id: str,
) -> dict[str, Any]:
    """Poll the mailbox for a new prompt or shutdown request.

    Returns a dict with ``type`` set to one of:
    - ``"shutdown_request"`` -- a shutdown was received.
    - ``"new_message"`` -- a new user prompt is available (under ``prompt``).
    - ``"aborted"`` -- the abort event was set externally.
    """
    while True:
        # Check abort first.
        if abort_event.is_set():
            return {"type": "aborted"}

        # Poll mailbox.
        try:
            unread = await read_unread_messages(identity)
            for msg in unread:
                parsed = is_shutdown_request(msg.text)
                if parsed is not None:
                    await _mark_read(identity, msg)
                    return {"type": "shutdown_request", "data": parsed}

                # Not a protocol message -- treat as a new prompt.
                if msg.text and not _is_structured(msg.text):
                    await _mark_read(identity, msg)
                    return {
                        "type": "new_message",
                        "prompt": msg.text,
                        "from_": msg.from_,
                    }
            # Also check pending messages queued by the task system.
            pending = drain_pending_messages(task_id)
            if pending:
                return {
                    "type": "new_message",
                    "prompt": "\n".join(pending),
                    "from_": "task-system",
                }
        except Exception:
            logger.exception("wait_for_next_prompt_or_shutdown: mailbox error")

        await asyncio.sleep(_MAILBOX_POLL_INTERVAL)


async def _mark_read(identity: str, msg: TeammateMessage) -> None:
    """Mark a single message as read by identity match."""
    await mark_messages_as_read_by_predicate(
        identity,
        predicate=lambda m: m.timestamp == msg.timestamp and m.from_ == msg.from_,
    )


def _is_structured(text: str) -> bool:
    """Heuristic: if the text parses as JSON with a ``type`` key it is a
    protocol message, not a user prompt."""
    try:
        import json

        obj = json.loads(text)
        return isinstance(obj, dict) and "type" in obj
    except (json.JSONDecodeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Idle notification helper
# ---------------------------------------------------------------------------


async def _send_idle_notification(
    identity: str,
    *,
    idle_reason: str = _IDLE_REASON_AVAILABLE,
    summary: str | None = None,
    completed_task_id: str | None = None,
    completed_status: str | None = None,
    failure_reason: str | None = None,
) -> None:
    """Write an idle notification to the team lead's mailbox."""
    notification = create_idle_notification(
        identity,
        idle_reason=idle_reason,
        summary=summary,
        completed_task_id=completed_task_id,
        completed_status=completed_status,
        failure_reason=failure_reason,
    )
    import json

    team_name = os.environ.get("CLAUDE_CODE_TEAM_NAME", "default")
    lead_name = "team-lead"
    msg = TeammateMessage(
        from_=identity,
        text=json.dumps(notification),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    await write_to_mailbox(lead_name, msg, team_name)


# ---------------------------------------------------------------------------
# Main runner loop
# ---------------------------------------------------------------------------


async def run_in_process_teammate(
    config: InProcessRunnerConfig,
) -> InProcessRunnerResult:
    """Execute the persistent agent loop for an in-process teammate.

    1. Build system prompt (base + teammate addendum).
    2. Run the agent with the initial prompt.
    3. Send idle notification.
    4. Poll for next prompt or shutdown, repeat.
    """
    import json

    from open_claude.tools.agent_tool.built_in.agents import (
        GENERAL_PURPOSE_AGENT,
    )

    abort_event = config.abort_event or asyncio.Event()
    collected_messages: list[dict[str, Any]] = []
    agent_def = config.agent_definition or {}

    # Compose system prompt.
    base_prompt = config.system_prompt or GENERAL_PURPOSE_AGENT.system_prompt
    system_prompt = base_prompt + "\n" + TEAMMATE_SYSTEM_PROMPT_ADDENDUM

    # Identity addendum.
    identity_line = f"\nYour teammate name is: {config.identity}\n"
    system_prompt += identity_line

    current_prompt = config.prompt
    turn = 0

    while True:
        turn += 1
        logger.info(
            "run_in_process_teammate [%s] turn=%d", config.identity, turn
        )

        # ----- Run the agent -----
        try:
            result = await _run_agent_turn(
                prompt=current_prompt,
                system_prompt=system_prompt,
                identity=config.identity,
                task_id=config.task_id,
                model=config.model,
                allowed_tools=config.allowed_tools,
                agent_definition=agent_def,
            )
        except Exception as exc:
            logger.exception(
                "run_in_process_teammate [%s] agent error on turn %d",
                config.identity,
                turn,
            )
            await fail_agent_task(config.task_id, str(exc))
            await _send_idle_notification(
                config.identity,
                idle_reason=_IDLE_REASON_FAILED,
                completed_task_id=config.task_id,
                failure_reason=str(exc),
            )
            return InProcessRunnerResult(
                success=False,
                error=str(exc),
                messages=collected_messages,
            )

        if result:
            collected_messages.append(result)

        # Check abort.
        if abort_event.is_set():
            logger.info(
                "run_in_process_teammate [%s] aborted after turn %d",
                config.identity,
                turn,
            )
            break

        # ----- Send idle notification -----
        summary = _extract_summary(result) if result else None
        await _send_idle_notification(
            config.identity,
            idle_reason=_IDLE_REASON_AVAILABLE,
            summary=summary,
            completed_task_id=config.task_id,
        )

        # ----- Wait for next prompt or shutdown -----
        next_action = await wait_for_next_prompt_or_shutdown(
            config.identity, abort_event, config.task_id
        )

        if next_action["type"] == "aborted":
            logger.info(
                "run_in_process_teammate [%s] abort during wait", config.identity
            )
            break

        if next_action["type"] == "shutdown_request":
            logger.info(
                "run_in_process_teammate [%s] shutdown requested",
                config.identity,
            )
            break

        if next_action["type"] == "new_message":
            current_prompt = next_action["prompt"]
            continue

        # Should not reach here, but break defensively.
        break

    # Mark task completed.
    task = _get_task(config.task_id)
    if task and task.status == "running":
        await complete_agent_task(
            {"agent_id": config.task_id, "status": "completed"}
        )

    return InProcessRunnerResult(
        success=True,
        messages=collected_messages,
    )


# ---------------------------------------------------------------------------
# Agent turn execution
# ---------------------------------------------------------------------------


async def _run_agent_turn(
    *,
    prompt: str,
    system_prompt: str,
    identity: str,
    task_id: str,
    model: str | None,
    allowed_tools: list[str],
    agent_definition: dict[str, Any],
) -> dict[str, Any] | None:
    """Execute a single agent turn via :func:`run_agent`."""
    try:
        from open_claude.tools import get_all_tools
        from open_claude.tools.agent_tool.run_agent import RunAgentParams, run_agent

        # Build effective agent definition with tool constraints
        effective_def: dict[str, Any] = {**agent_definition, "system_prompt": system_prompt}
        if allowed_tools:
            effective_def["tools"] = allowed_tools

        # Load all available tools; resolve_agent_tools() handles filtering
        all_tools = get_all_tools()

        params = RunAgentParams(
            agent_definition=effective_def,
            prompt_messages=[{"role": "user", "content": prompt}],
            model=model,
            available_tools=all_tools,
            query_source=f"swarm:{identity}",
            description=f"Teammate turn for {identity}",
        )

        # run_agent() is an async generator — must iterate, not await
        collected: list[dict[str, Any]] = []
        async for msg in run_agent(
            params, parent_model=model or "claude-sonnet-4-20250514"
        ):
            collected.append(msg)
        return {"turn_prompt": prompt, "messages": collected}
    except ImportError:
        logger.debug(
            "run_agent module not available; using stub for %s", identity
        )
        return {"turn_prompt": prompt, "messages": []}


# ---------------------------------------------------------------------------
# Summary extraction
# ---------------------------------------------------------------------------


def _extract_summary(result: dict[str, Any]) -> str | None:
    """Try to extract a short summary from an agent turn result."""
    messages = result.get("messages", [])
    if not messages:
        return None
    # Take the last assistant text block, truncated.
    for msg in reversed(messages):
        content = msg.get("message", {}).get("content", [])
        for block in reversed(content):
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if len(text) > 300:
                    return text[:300] + "..."
                return text or None
    return None


# ---------------------------------------------------------------------------
# Fire-and-forget wrapper
# ---------------------------------------------------------------------------


def start_in_process_teammate(config: InProcessRunnerConfig) -> None:
    """Fire-and-forget: schedule the runner loop as an asyncio task."""
    asyncio.create_task(_run_and_cleanup(config))


async def _run_and_cleanup(config: InProcessRunnerConfig) -> None:
    """Run the teammate loop and ensure the task is cleaned up."""
    try:
        await run_in_process_teammate(config)
    except Exception:
        logger.exception(
            "start_in_process_teammate [%s] unhandled error", config.identity
        )
        await fail_agent_task(config.task_id, "Unhandled error in runner loop")
