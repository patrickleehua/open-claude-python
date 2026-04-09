"""In-process teammate spawning -- ported from Claude-Code-rev spawnInProcess.ts.

Manages the creation and teardown of teammate agents that run as asyncio
tasks within the same process (as opposed to separate tmux panes).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from open_claude.tasks.local_agent_task import (
    LocalAgentTaskState,
    register_async_agent,
    kill_async_agent,
    _get_task,
    _remove_task,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration & output types
# ---------------------------------------------------------------------------


@dataclass
class InProcessSpawnConfig:
    """Configuration for spawning an in-process teammate."""

    name: str
    team_name: str
    prompt: str
    color: str | None = None
    plan_mode_required: bool = False
    model: str | None = None


@dataclass
class InProcessSpawnOutput:
    """Result of an in-process teammate spawn attempt."""

    success: bool
    agent_id: str | None = None
    task_id: str | None = None
    abort_event: asyncio.Event | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Spawning
# ---------------------------------------------------------------------------


async def spawn_in_process_teammate(
    config: InProcessSpawnConfig,
) -> InProcessSpawnOutput:
    """Create an agent context and register a background task for a teammate.

    The actual agent loop is launched by ``start_in_process_teammate`` in
    ``in_process_runner.py``, which consumes the registered task.
    """
    try:
        agent_id = str(uuid.uuid4())
        task_id = agent_id  # 1:1 mapping in the in-process path

        # Build a minimal agent definition dict so the task store has enough
        # metadata for progress display and tool selection.
        agent_definition: dict = {
            "agent_type": "general-purpose",
            "name": config.name,
            "color": config.color,
            "plan_mode_required": config.plan_mode_required,
            "model": config.model,
        }

        task = await register_async_agent(
            agent_id=agent_id,
            description=config.name,
            prompt=config.prompt,
            selected_agent=agent_definition,
        )
        task.task_id = task_id

        # Stash team name on the task for downstream consumers.
        task.result = {"team_name": config.team_name}

        logger.info(
            "spawn_in_process_teammate: registered %s (task_id=%s)",
            config.name,
            task_id,
        )

        return InProcessSpawnOutput(
            success=True,
            agent_id=agent_id,
            task_id=task_id,
            abort_event=task.abort_event,
        )
    except Exception as exc:
        logger.exception("spawn_in_process_teammate failed for %s", config.name)
        return InProcessSpawnOutput(
            success=False,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------


async def kill_in_process_teammate(task_id: str) -> bool:
    """Abort an in-process teammate and clean up its task entry.

    Returns ``True`` if the task was found and killed, ``False`` otherwise.
    """
    task = _get_task(task_id)
    if task is None:
        return False

    if task.status == "running":
        await kill_async_agent(task_id)

    # Remove from the store so it does not linger in the task list.
    await _remove_task(task_id)
    logger.info("kill_in_process_teammate: cleaned up %s", task_id)
    return True
