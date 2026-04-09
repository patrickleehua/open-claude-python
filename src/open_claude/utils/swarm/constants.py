"""Swarm / teammate constants — ported from Claude-Code-rev swarm/constants.ts."""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Session & command constants
# ---------------------------------------------------------------------------

TEAM_LEAD_NAME: str = "team-lead"
"""Default name for the team lead agent."""

SWARM_SESSION_NAME: str = "claude-swarm"
"""Tmux session name for the swarm."""

SWARM_VIEW_WINDOW_NAME: str = "swarm-view"
"""Window name for the swarm view."""

TMUX_COMMAND: str = "tmux"
"""Path to the tmux binary."""

HIDDEN_SESSION_NAME: str = "claude-hidden"
"""Hidden tmux session for background operations."""


def get_swarm_socket_name() -> str:
    """Return the socket name for external swarm sessions.

    Includes PID to ensure multiple Claude instances don't conflict.
    """
    return f"claude-swarm-{os.getpid()}"


# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

TEAMMATE_COMMAND_ENV_VAR: str = "CLAUDE_CODE_TEAMMATE_COMMAND"
"""Override the command used to spawn teammate instances."""

TEAMMATE_COLOR_ENV_VAR: str = "CLAUDE_CODE_AGENT_COLOR"
"""Set on spawned teammates to indicate their assigned color."""

PLAN_MODE_REQUIRED_ENV_VAR: str = "CLAUDE_CODE_PLAN_MODE_REQUIRED"
"""When set to 'true', teammates must enter plan mode before writing code."""

SWARM_MODE_ENV_VAR: str = "CLAUDE_CODE_SWARM_MODE"
"""When set to 'true', swarm / teammate mode is active."""


def is_swarm_mode() -> bool:
    """Return whether the current session is running in swarm mode."""
    return os.environ.get(SWARM_MODE_ENV_VAR, "").lower() == "true"
