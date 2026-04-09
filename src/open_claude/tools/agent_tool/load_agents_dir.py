"""Load agent definitions from markdown/JSON files and merge with built-in agents.

Ported from Claude-Code-rev/src/tools/AgentTool/loadAgentsDir.ts.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Union

import yaml

from open_claude.schemas.permissions import PermissionMode
from open_claude.tools.agent_tool.built_in.agents import (
    EXPLORE_AGENT,
    GENERAL_PURPOSE_AGENT,
    PLAN_AGENT,
    VERIFICATION_AGENT,
)
from open_claude.utils.memory.frontmatter import parse_frontmatter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EFFORT_LEVELS = ("low", "medium", "high")
PERMISSION_MODES = tuple(m.value for m in PermissionMode)
AGENT_COLORS = (
    "blue", "green", "yellow", "red", "magenta", "cyan",
    "orange", "pink", "purple", "teal",
)

SettingSource = Literal[
    "built-in",
    "userSettings",
    "projectSettings",
    "policySettings",
    "flagSettings",
    "plugin",
]

AgentMemoryScope = Literal["user", "project", "local"]

# MCP server spec: either a name reference string or an inline {name: config} dict.
AgentMcpServerSpec = Union[str, dict[str, dict]]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BaseAgentDefinition:
    """Common fields shared by all agent definition types."""

    agent_type: str
    when_to_use: str
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    skills: list[str] | None = None
    mcp_servers: list[AgentMcpServerSpec] | None = None
    hooks: dict | None = None
    color: str | None = None
    model: str | None = None
    effort: str | int | None = None
    permission_mode: str | None = None
    max_turns: int | None = None
    filename: str | None = None
    base_dir: str | None = None
    critical_system_reminder: str | None = None
    required_mcp_servers: list[str] | None = None
    background: bool | None = None
    initial_prompt: str | None = None
    memory: AgentMemoryScope | None = None
    isolation: Literal["worktree", "remote"] | None = None
    pending_snapshot_update: dict | None = None
    omit_claude_md: bool | None = None


@dataclass
class WrappedBuiltInAgent(BaseAgentDefinition):
    """Built-in agent wrapped for the agent-definitions registry.

    This wraps the raw :class:`built_in.agents.BuiltInAgentDefinition` with
    a ``get_system_prompt`` callable so it conforms to the
    :class:`BaseAgentDefinition` interface used by the loader.
    """

    source: str = field(default="built-in", init=False)
    base_dir: str = field(default="built-in", init=False)
    get_system_prompt: Callable[..., str] = field(default=lambda: "")

    def __post_init__(self) -> None:
        self.source = "built-in"
        self.base_dir = "built-in"


@dataclass
class CustomAgentDefinition(BaseAgentDefinition):
    """Agent loaded from user/project/policy markdown or JSON."""

    get_system_prompt: Callable[..., str] = field(default=lambda: "")
    source: SettingSource = "userSettings"


# Union type for all agent variants.
AgentDefinition = Union[WrappedBuiltInAgent, CustomAgentDefinition]


@dataclass
class AgentDefinitionsResult:
    """Return value for *get_agent_definitions_with_overrides*."""

    active_agents: list[AgentDefinition]
    all_agents: list[AgentDefinition]
    failed_files: list[dict[str, str]] | None = None
    allowed_agent_types: list[str] | None = None


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_agent_definitions_cache: dict[str, AgentDefinitionsResult] = {}


# ---------------------------------------------------------------------------
# Type guards
# ---------------------------------------------------------------------------


def is_built_in_agent(agent: AgentDefinition) -> bool:
    """Return True for built-in agents."""
    return getattr(agent, "source", None) == "built-in"


def is_custom_agent(agent: AgentDefinition) -> bool:
    """Return True for user/project/policy-sourced agents (not built-in or plugin)."""
    source = getattr(agent, "source", None)
    return source != "built-in" and source != "plugin"


# ---------------------------------------------------------------------------
# Built-in agent helpers
# ---------------------------------------------------------------------------


def _get_built_in_agents() -> list[WrappedBuiltInAgent]:
    """Wrap the four canonical built-in agents as *WrappedBuiltInAgent*."""

    def _wrap(agent) -> WrappedBuiltInAgent:
        prompt = getattr(agent, "system_prompt", "")
        return WrappedBuiltInAgent(
            agent_type=agent.agent_type,
            when_to_use=agent.when_to_use,
            disallowed_tools=list(agent.disallowed_tools) if agent.disallowed_tools else None,
            color=agent.color,
            background=agent.background,
            model=agent.model,
            critical_system_reminder=agent.critical_system_reminder,
            get_system_prompt=lambda _p=prompt: _p,
        )

    return [_wrap(a) for a in (GENERAL_PURPOSE_AGENT, EXPLORE_AGENT, PLAN_AGENT, VERIFICATION_AGENT)]


# ---------------------------------------------------------------------------
# Frontmatter parsing utilities
# ---------------------------------------------------------------------------


def _parse_agent_tools(value) -> list[str] | None:
    """Normalise a tools field (comma-separated string or list) into a list."""
    if value is None:
        return None
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return None


def _parse_skills(value) -> list[str] | None:
    """Parse skills from comma-separated string or list."""
    return _parse_agent_tools(value)


def _parse_effort_value(raw) -> str | int | None:
    """Validate an effort value.  Returns the value or None."""
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        if raw in EFFORT_LEVELS:
            return raw
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def _parse_positive_int(value) -> int | None:
    """Parse a positive integer from frontmatter value."""
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        try:
            iv = int(value)
            if iv > 0:
                return iv
        except ValueError:
            pass
    return None


def _get_parse_error(frontmatter: dict) -> str:
    """Return a human-friendly reason why frontmatter failed to parse."""
    name = frontmatter.get("name")
    description = frontmatter.get("description")

    if not name or not isinstance(name, str):
        return 'Missing required "name" field in frontmatter'
    if not description or not isinstance(description, str):
        return 'Missing required "description" field in frontmatter'
    return "Unknown parsing error"


# ---------------------------------------------------------------------------
# parseAgentFromMarkdown
# ---------------------------------------------------------------------------


def parse_agent_from_markdown(
    file_path: str,
    base_dir: str,
    frontmatter: dict,
    content: str,
    source: SettingSource,
) -> CustomAgentDefinition | None:
    """Parse a markdown file into a *CustomAgentDefinition*.

    Returns ``None`` when the file does not look like a valid agent definition
    (e.g. reference docs co-located in the agents directory).
    """
    try:
        agent_type = frontmatter.get("name")
        when_to_use = frontmatter.get("description")

        if not agent_type or not isinstance(agent_type, str):
            return None
        if not when_to_use or not isinstance(when_to_use, str):
            logger.debug(
                "Agent file %s is missing required 'description' in frontmatter",
                file_path,
            )
            return None

        # Unescape literal ``\\n`` produced by some YAML writers.
        when_to_use = when_to_use.replace("\\n", "\n")

        # --- colour ---
        color: str | None = frontmatter.get("color")
        if not isinstance(color, str) or color not in AGENT_COLORS:
            color = None

        # --- model ---
        model_raw = frontmatter.get("model")
        model: str | None = None
        if isinstance(model_raw, str) and model_raw.strip():
            trimmed = model_raw.strip()
            model = "inherit" if trimmed.lower() == "inherit" else trimmed

        # --- background ---
        bg_raw = frontmatter.get("background")
        if bg_raw not in (None, "true", "false", True, False):
            logger.debug(
                "Agent file %s has invalid background value %r. Must be 'true', 'false', or omitted.",
                file_path,
                bg_raw,
            )
        background = bg_raw in ("true", True) or None

        # --- memory ---
        valid_memory: tuple[str, ...] = ("user", "project", "local")
        memory_raw = frontmatter.get("memory")
        memory: AgentMemoryScope | None = None
        if memory_raw is not None:
            if isinstance(memory_raw, str) and memory_raw in valid_memory:
                memory = memory_raw  # type: ignore[assignment]
            else:
                logger.debug(
                    "Agent file %s has invalid memory value %r. Valid options: %s",
                    file_path,
                    memory_raw,
                    ", ".join(valid_memory),
                )

        # --- isolation ---
        valid_isolation: tuple[str, ...] = ("worktree",)
        isolation_raw = frontmatter.get("isolation")
        isolation: Literal["worktree", "remote"] | None = None
        if isolation_raw is not None:
            if isinstance(isolation_raw, str) and isolation_raw in valid_isolation:
                isolation = isolation_raw  # type: ignore[assignment]
            else:
                logger.debug(
                    "Agent file %s has invalid isolation value %r. Valid options: %s",
                    file_path,
                    isolation_raw,
                    ", ".join(valid_isolation),
                )

        # --- effort ---
        effort_raw = frontmatter.get("effort")
        parsed_effort = _parse_effort_value(effort_raw) if effort_raw is not None else None
        if effort_raw is not None and parsed_effort is None:
            logger.debug(
                "Agent file %s has invalid effort %r. Valid options: %s or an integer",
                file_path,
                effort_raw,
                ", ".join(EFFORT_LEVELS),
            )

        # --- permissionMode ---
        pm_raw = frontmatter.get("permissionMode")
        permission_mode: str | None = None
        if pm_raw and isinstance(pm_raw, str) and pm_raw in PERMISSION_MODES:
            permission_mode = pm_raw

        if pm_raw and not permission_mode:
            logger.debug(
                "Agent file %s has invalid permissionMode %r. Valid options: %s",
                file_path,
                pm_raw,
                ", ".join(PERMISSION_MODES),
            )

        # --- maxTurns ---
        max_turns_raw = frontmatter.get("maxTurns")
        max_turns = _parse_positive_int(max_turns_raw) if max_turns_raw is not None else None
        if max_turns_raw is not None and max_turns is None:
            logger.debug(
                "Agent file %s has invalid maxTurns %r. Must be a positive integer.",
                file_path,
                max_turns_raw,
            )

        # --- filename ---
        filename = Path(file_path).stem

        # --- tools / disallowedTools ---
        tools = _parse_agent_tools(frontmatter.get("tools"))
        disallowed_tools = _parse_agent_tools(frontmatter.get("disallowedTools"))

        # --- skills ---
        skills = _parse_skills(frontmatter.get("skills"))

        # --- initialPrompt ---
        ip_raw = frontmatter.get("initialPrompt")
        initial_prompt = ip_raw if isinstance(ip_raw, str) and ip_raw.strip() else None

        # --- mcpServers ---
        mcp_raw = frontmatter.get("mcpServers")
        mcp_servers: list[AgentMcpServerSpec] | None = None
        if isinstance(mcp_raw, list):
            valid: list[AgentMcpServerSpec] = []
            for item in mcp_raw:
                if isinstance(item, str):
                    valid.append(item)
                elif isinstance(item, dict):
                    valid.append(item)
            if valid:
                mcp_servers = valid

        # --- hooks ---
        hooks = frontmatter.get("hooks") if isinstance(frontmatter.get("hooks"), dict) else None

        system_prompt = content.strip()

        return CustomAgentDefinition(
            base_dir=base_dir,
            agent_type=agent_type,
            when_to_use=when_to_use,
            tools=tools,
            disallowed_tools=disallowed_tools,
            skills=skills,
            initial_prompt=initial_prompt,
            mcp_servers=mcp_servers,
            hooks=hooks,
            get_system_prompt=lambda _p=system_prompt: _p,
            source=source,
            filename=filename,
            color=color,
            model=model,
            effort=parsed_effort,
            permission_mode=permission_mode,
            max_turns=max_turns,
            background=background,
            memory=memory,
            isolation=isolation,
        )
    except Exception as exc:
        logger.debug("Error parsing agent from %s: %s", file_path, exc)
        return None


# ---------------------------------------------------------------------------
# parseAgentFromJson
# ---------------------------------------------------------------------------


def parse_agent_from_json(
    name: str,
    definition: dict,
    source: SettingSource = "flagSettings",
) -> CustomAgentDefinition | None:
    """Validate a JSON agent definition and return a *CustomAgentDefinition*."""
    try:
        if not isinstance(definition, dict):
            return None

        description = definition.get("description")
        prompt = definition.get("prompt")
        if not description or not isinstance(description, str):
            logger.debug("Agent %r from JSON is missing 'description'", name)
            return None
        if not prompt or not isinstance(prompt, str):
            logger.debug("Agent %r from JSON is missing 'prompt'", name)
            return None

        tools = _parse_agent_tools(definition.get("tools"))
        disallowed_tools = _parse_agent_tools(definition.get("disallowedTools"))
        skills = _parse_skills(definition.get("skills"))

        model_raw = definition.get("model")
        model: str | None = None
        if isinstance(model_raw, str) and model_raw.strip():
            trimmed = model_raw.strip()
            model = "inherit" if trimmed.lower() == "inherit" else trimmed

        effort_raw = definition.get("effort")
        effort = _parse_effort_value(effort_raw) if effort_raw is not None else None

        pm_raw = definition.get("permissionMode")
        permission_mode: str | None = None
        if pm_raw and isinstance(pm_raw, str) and pm_raw in PERMISSION_MODES:
            permission_mode = pm_raw

        max_turns = _parse_positive_int(definition.get("maxTurns"))

        mcp_raw = definition.get("mcpServers")
        mcp_servers: list[AgentMcpServerSpec] | None = None
        if isinstance(mcp_raw, list) and mcp_raw:
            mcp_servers = mcp_raw

        hooks = definition.get("hooks") if isinstance(definition.get("hooks"), dict) else None

        initial_prompt = definition.get("initialPrompt")
        if not isinstance(initial_prompt, str) or not initial_prompt.strip():
            initial_prompt = None

        background = definition.get("background")
        if background not in (True, False):
            background = None

        memory_raw = definition.get("memory")
        memory: AgentMemoryScope | None = None
        if isinstance(memory_raw, str) and memory_raw in ("user", "project", "local"):
            memory = memory_raw  # type: ignore[assignment]

        isolation_raw = definition.get("isolation")
        isolation: Literal["worktree", "remote"] | None = None
        if isinstance(isolation_raw, str) and isolation_raw in ("worktree",):
            isolation = isolation_raw  # type: ignore[assignment]

        system_prompt = prompt

        return CustomAgentDefinition(
            agent_type=name,
            when_to_use=description,
            tools=tools,
            disallowed_tools=disallowed_tools,
            skills=skills,
            get_system_prompt=lambda _p=system_prompt: _p,
            source=source,
            model=model,
            effort=effort,
            permission_mode=permission_mode,
            max_turns=max_turns,
            mcp_servers=mcp_servers,
            hooks=hooks,
            initial_prompt=initial_prompt if isinstance(initial_prompt, str) else None,
            background=background,
            memory=memory,
            isolation=isolation,
        )
    except Exception as exc:
        logger.debug("Error parsing agent %r from JSON: %s", name, exc)
        return None


# ---------------------------------------------------------------------------
# parseAgentsFromJson
# ---------------------------------------------------------------------------


def parse_agents_from_json(
    agents_json: dict,
    source: SettingSource = "flagSettings",
) -> list[AgentDefinition]:
    """Parse multiple agents from a ``{name: def, ...}`` mapping."""
    if not isinstance(agents_json, dict):
        return []
    result: list[AgentDefinition] = []
    for name, defn in agents_json.items():
        agent = parse_agent_from_json(name, defn, source)
        if agent is not None:
            result.append(agent)
    return result


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------


def _scan_agents_dir(cwd: str) -> list[dict]:
    """Scan ``.claude/agents/`` for ``*.md`` files and return parsed entries.

    Each entry is ``{file_path, base_dir, frontmatter, content, source}``.
    """
    agents_dir = Path(cwd) / ".claude" / "agents"
    if not agents_dir.is_dir():
        return []

    results: list[dict] = []
    for md_file in sorted(agents_dir.rglob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, body = parse_frontmatter(text)
        if not isinstance(fm, dict):
            fm = {}
        results.append(
            {
                "file_path": str(md_file),
                "base_dir": str(md_file.parent),
                "frontmatter": fm,
                "content": body,
                "source": "projectSettings",
            }
        )
    return results


# ---------------------------------------------------------------------------
# getActiveAgentsFromList
# ---------------------------------------------------------------------------


def get_active_agents_from_list(all_agents: list[AgentDefinition]) -> list[AgentDefinition]:
    """Deduplicate agents by ``agent_type``.

    Priority order (first match wins): built-in, plugin, user, project, flag, managed.
    """
    source_order = [
        "built-in",
        "plugin",
        "userSettings",
        "projectSettings",
        "flagSettings",
        "policySettings",
    ]
    buckets: dict[str, list[AgentDefinition]] = {s: [] for s in source_order}
    for agent in all_agents:
        src = getattr(agent, "source", "projectSettings")
        if src not in buckets:
            src = "projectSettings"
        buckets[src].append(agent)

    agent_map: dict[str, AgentDefinition] = {}
    for src in source_order:
        for agent in buckets.get(src, []):
            agent_map.setdefault(agent.agent_type, agent)
    return list(agent_map.values())


# ---------------------------------------------------------------------------
# MCP requirement helpers
# ---------------------------------------------------------------------------


def has_required_mcp_servers(agent: AgentDefinition, available_servers: list[str]) -> bool:
    """Return True if all required MCP servers for *agent* are present."""
    required = getattr(agent, "required_mcp_servers", None)
    if not required:
        return True
    lower_available = [s.lower() for s in available_servers]
    return all(
        any(pat.lower() in srv for srv in lower_available)
        for pat in required
    )


def filter_agents_by_mcp_requirements(
    agents: list[AgentDefinition],
    available_servers: list[str],
) -> list[AgentDefinition]:
    """Filter agents whose required MCP servers are all available."""
    return [a for a in agents if has_required_mcp_servers(a, available_servers)]


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------


def get_agent_definitions_with_overrides(cwd: str) -> AgentDefinitionsResult:
    """Load built-in agents then scan ``.claude/agents/`` for overrides.

    Results are cached per *cwd*; call :func:`clear_agent_definitions_cache`
    to invalidate.
    """
    if cwd in _agent_definitions_cache:
        return _agent_definitions_cache[cwd]

    # Simple mode: only built-in agents.
    if os.environ.get("CLAUDE_CODE_SIMPLE", "").lower() in ("1", "true"):
        built_in = _get_built_in_agents()
        result = AgentDefinitionsResult(active_agents=built_in, all_agents=built_in)
        _agent_definitions_cache[cwd] = result
        return result

    try:
        failed_files: list[dict[str, str]] = []
        md_entries = _scan_agents_dir(cwd)

        custom_agents: list[AgentDefinition] = []
        for entry in md_entries:
            agent = parse_agent_from_markdown(
                entry["file_path"],
                entry["base_dir"],
                entry["frontmatter"],
                entry["content"],
                entry["source"],
            )
            if agent is None:
                fm = entry["frontmatter"]
                if fm.get("name"):
                    error_msg = _get_parse_error(fm)
                    failed_files.append({"path": entry["file_path"], "error": error_msg})
                    logger.debug(
                        "Failed to parse agent from %s: %s",
                        entry["file_path"],
                        error_msg,
                    )
                continue
            custom_agents.append(agent)

        built_in = _get_built_in_agents()
        all_agents_list: list[AgentDefinition] = [*built_in, *custom_agents]
        active_agents = get_active_agents_from_list(all_agents_list)

        result = AgentDefinitionsResult(
            active_agents=active_agents,
            all_agents=all_agents_list,
            failed_files=failed_files if failed_files else None,
        )
    except Exception as exc:
        logger.debug("Error loading agent definitions: %s", exc)
        built_in = _get_built_in_agents()
        result = AgentDefinitionsResult(
            active_agents=built_in,
            all_agents=built_in,
            failed_files=[{"path": "unknown", "error": str(exc)}],
        )

    _agent_definitions_cache[cwd] = result
    return result


def clear_agent_definitions_cache() -> None:
    """Invalidate the module-level agent definitions cache."""
    _agent_definitions_cache.clear()
