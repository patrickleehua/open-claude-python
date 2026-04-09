"""Team file management — ported from Claude-Code-rev teamHelpers.ts.

Manages team configuration files for multi-agent coordination:
team member tracking, permission modes, worktree cleanup.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TeamMember:
    """A member of a team."""

    agent_id: str
    name: str
    agent_type: str | None = None
    model: str | None = None
    prompt: str | None = None
    color: str | None = None
    plan_mode_required: bool | None = None
    joined_at: float = field(default_factory=lambda: time.time() * 1000)
    cwd: str = ""
    worktree_path: str | None = None
    session_id: str | None = None
    subscriptions: list[str] = field(default_factory=list)
    backend_type: str | None = None
    is_active: bool | None = None
    mode: str | None = None


@dataclass
class TeamAllowedPath:
    """A path that all teammates can edit without asking."""

    path: str
    tool_name: str
    added_by: str
    added_at: float = field(default_factory=lambda: time.time() * 1000)


@dataclass
class TeamFile:
    """Team configuration persisted to disk."""

    name: str
    description: str | None = None
    created_at: float = field(default_factory=lambda: time.time() * 1000)
    lead_agent_id: str = ""
    lead_session_id: str | None = None
    hidden_pane_ids: list[str] = field(default_factory=list)
    team_allowed_paths: list[TeamAllowedPath] = field(default_factory=list)
    members: list[TeamMember] = field(default_factory=list)


@dataclass
class SpawnTeamOutput:
    """Result of spawning a team."""

    team_name: str
    team_file_path: str
    lead_agent_id: str


# ---------------------------------------------------------------------------
# Name sanitization
# ---------------------------------------------------------------------------


def sanitize_name(name: str) -> str:
    """Lowercase, replace non-alphanumeric with hyphens."""
    return re.sub(r"[^a-zA-Z0-9]", "-", name).lower()


def sanitize_agent_name(name: str) -> str:
    """Replace '@' with '-' to prevent ambiguity."""
    return name.replace("@", "-")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _get_teams_base_dir() -> Path:
    """Return ``~/.claude/teams/``."""
    return Path.home() / ".claude" / "teams"


def get_team_dir(team_name: str) -> Path:
    """Return the directory for a team."""
    return _get_teams_base_dir() / sanitize_name(team_name)


def get_team_file_path(team_name: str) -> Path:
    """Return the config.json path for a team."""
    return get_team_dir(team_name) / "config.json"


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _team_member_to_dict(m: TeamMember) -> dict[str, Any]:
    return {
        "agentId": m.agent_id,
        "name": m.name,
        "agentType": m.agent_type,
        "model": m.model,
        "prompt": m.prompt,
        "color": m.color,
        "planModeRequired": m.plan_mode_required,
        "joinedAt": m.joined_at,
        "cwd": m.cwd,
        "worktreePath": m.worktree_path,
        "sessionId": m.session_id,
        "subscriptions": m.subscriptions,
        "backendType": m.backend_type,
        "isActive": m.is_active,
        "mode": m.mode,
    }


def _dict_to_team_member(d: dict[str, Any]) -> TeamMember:
    return TeamMember(
        agent_id=d.get("agentId", ""),
        name=d.get("name", ""),
        agent_type=d.get("agentType"),
        model=d.get("model"),
        prompt=d.get("prompt"),
        color=d.get("color"),
        plan_mode_required=d.get("planModeRequired"),
        joined_at=d.get("joinedAt", time.time() * 1000),
        cwd=d.get("cwd", ""),
        worktree_path=d.get("worktreePath"),
        session_id=d.get("sessionId"),
        subscriptions=d.get("subscriptions", []),
        backend_type=d.get("backendType"),
        is_active=d.get("isActive"),
        mode=d.get("mode"),
    )


def _team_file_to_dict(tf: TeamFile) -> dict[str, Any]:
    return {
        "name": tf.name,
        "description": tf.description,
        "createdAt": tf.created_at,
        "leadAgentId": tf.lead_agent_id,
        "leadSessionId": tf.lead_session_id,
        "hiddenPaneIds": tf.hidden_pane_ids,
        "teamAllowedPaths": [
            {
                "path": p.path,
                "toolName": p.tool_name,
                "addedBy": p.added_by,
                "addedAt": p.added_at,
            }
            for p in tf.team_allowed_paths
        ],
        "members": [_team_member_to_dict(m) for m in tf.members],
    }


def _dict_to_team_file(d: dict[str, Any]) -> TeamFile:
    allowed_paths = [
        TeamAllowedPath(
            path=p.get("path", ""),
            tool_name=p.get("toolName", ""),
            added_by=p.get("addedBy", ""),
            added_at=p.get("addedAt", 0),
        )
        for p in d.get("teamAllowedPaths", [])
    ]
    return TeamFile(
        name=d.get("name", ""),
        description=d.get("description"),
        created_at=d.get("createdAt", 0),
        lead_agent_id=d.get("leadAgentId", ""),
        lead_session_id=d.get("leadSessionId"),
        hidden_pane_ids=d.get("hiddenPaneIds", []),
        team_allowed_paths=allowed_paths,
        members=[_dict_to_team_member(m) for m in d.get("members", [])],
    )


# ---------------------------------------------------------------------------
# Read / Write
# ---------------------------------------------------------------------------


def read_team_file(team_name: str) -> TeamFile | None:
    """Read a team file synchronously."""
    path = get_team_file_path(team_name)
    try:
        content = path.read_text(encoding="utf-8")
        return _dict_to_team_file(json.loads(content))
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Failed to read team file for %s: %s", team_name, exc)
        return None


async def read_team_file_async(team_name: str) -> TeamFile | None:
    """Read a team file asynchronously."""
    import asyncio

    path = get_team_file_path(team_name)
    try:
        content = await asyncio.to_thread(path.read_text, "utf-8")
        return _dict_to_team_file(json.loads(content))
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Failed to read team file for %s: %s", team_name, exc)
        return None


async def write_team_file_async(team_name: str, team_file: TeamFile) -> None:
    """Write a team file asynchronously, ensuring the directory exists."""
    import asyncio

    team_dir = get_team_dir(team_name)
    await asyncio.to_thread(team_dir.mkdir, True, True)
    path = get_team_file_path(team_name)
    data = json.dumps(_team_file_to_dict(team_file), indent=2)
    await asyncio.to_thread(path.write_text, data, "utf-8")


def _write_team_file_sync(team_name: str, team_file: TeamFile) -> None:
    """Write a team file synchronously."""
    team_dir = get_team_dir(team_name)
    team_dir.mkdir(parents=True, exist_ok=True)
    path = get_team_file_path(team_name)
    data = json.dumps(_team_file_to_dict(team_file), indent=2)
    path.write_text(data, encoding="utf-8")


# ---------------------------------------------------------------------------
# Member operations
# ---------------------------------------------------------------------------


def add_teammate(team_name: str, member: TeamMember) -> None:
    """Add a member to the team file."""
    team_file = read_team_file(team_name)
    if team_file is None:
        logger.warning("Cannot add teammate: team %s not found", team_name)
        return
    team_file.members.append(member)
    _write_team_file_sync(team_name, team_file)


def remove_teammate_from_team_file(
    team_name: str,
    identifier: dict[str, str | None],
) -> bool:
    """Remove a teammate by agent_id or name."""
    identifier_str = identifier.get("agent_id") or identifier.get("name")
    if not identifier_str:
        return False

    team_file = read_team_file(team_name)
    if team_file is None:
        return False

    original_len = len(team_file.members)
    team_file.members = [
        m
        for m in team_file.members
        if not (
            (identifier.get("agent_id") and m.agent_id == identifier["agent_id"])
            or (identifier.get("name") and m.name == identifier["name"])
        )
    ]

    if len(team_file.members) == original_len:
        return False

    _write_team_file_sync(team_name, team_file)
    return True


def remove_member_from_team(team_name: str, agent_id: str) -> bool:
    """Remove a member from the team by agent_id."""
    team_file = read_team_file(team_name)
    if team_file is None:
        return False

    idx = next((i for i, m in enumerate(team_file.members) if m.agent_id == agent_id), None)
    if idx is None:
        return False

    team_file.members.pop(idx)
    _write_team_file_sync(team_name, team_file)
    return True


def set_member_mode(team_name: str, member_name: str, mode: str) -> bool:
    """Set a team member's permission mode."""
    team_file = read_team_file(team_name)
    if team_file is None:
        return False

    member = next((m for m in team_file.members if m.name == member_name), None)
    if member is None:
        return False

    if member.mode == mode:
        return True

    member.mode = mode
    _write_team_file_sync(team_name, team_file)
    return True


async def set_member_active(team_name: str, member_name: str, is_active: bool) -> None:
    """Set a team member's active status."""
    team_file = await read_team_file_async(team_name)
    if team_file is None:
        return

    member = next((m for m in team_file.members if m.name == member_name), None)
    if member is None:
        return

    if member.is_active == is_active:
        return

    member.is_active = is_active
    await write_team_file_async(team_name, team_file)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def cleanup_team_directories(team_name: str) -> None:
    """Remove worktrees and delete team directory.

    Best-effort: logs errors but does not raise.
    """
    import asyncio
    import shutil

    # Read team file to get worktree paths BEFORE deleting
    team_file = read_team_file(team_name)
    if team_file:
        for member in team_file.members:
            if member.worktree_path:
                wt = Path(member.worktree_path)
                try:
                    await asyncio.to_thread(shutil.rmtree, wt, True)
                except Exception as exc:
                    logger.warning("Failed to remove worktree %s: %s", wt, exc)

    # Remove team directory
    team_dir = get_team_dir(team_name)
    try:
        await asyncio.to_thread(shutil.rmtree, team_dir, True)
    except Exception as exc:
        logger.warning("Failed to remove team dir %s: %s", team_dir, exc)
