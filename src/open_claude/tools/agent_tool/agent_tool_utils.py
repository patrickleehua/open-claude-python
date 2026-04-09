"""Agent tool utility functions — ported from Claude-Code-rev agentToolUtils.ts.

Provides tool filtering, resolution, finalization, and the async agent lifecycle
driver used by AgentTool and resumeAgentBackground.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Sequence

from pydantic import BaseModel

from open_claude.constants.prompts import AGENT_TOOL_NAME
from open_claude.schemas.permissions import PermissionMode
from open_claude.tasks.local_agent_task import (
    ProgressTracker,
    complete_agent_task,
    create_progress_tracker,
    enqueue_agent_notification,
    fail_agent_task,
    get_progress_update,
    get_token_count_from_tracker,
    is_local_agent_task,
    kill_async_agent,
    update_agent_progress,
    update_progress_from_message,
)
from open_claude.tools.base import Tool
from open_claude.utils.permissions.rule_parser import permission_rule_value_from_string

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEGACY_AGENT_TOOL_NAME = "Task"
EXIT_PLAN_MODE_V2_TOOL_NAME = "ExitPlanMode"

ALL_AGENT_DISALLOWED_TOOLS: set[str] = {"Agent"}
CUSTOM_AGENT_DISALLOWED_TOOLS: set[str] = {"Agent"}

ASYNC_AGENT_ALLOWED_TOOLS: set[str] = {
    "Bash",
    "Glob",
    "Grep",
    "Read",
    "WebFetch",
    "WebSearch",
    "Skill",
    "TodoWrite",
    "AskUserQuestion",
    "Edit",
    "Write",
    "NotebookEdit",
}

IN_PROCESS_TEAMMATE_ALLOWED_TOOLS: set[str] = {
    "TodoWrite",
    "Agent",
}

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# Shorthand — the Python port uses ``list[Tool]`` everywhere the TS code uses
# the ``Tools`` type alias.
Tools = list[Tool]

# Messages are represented as plain dicts (same shape as the API wire format).
Message = dict[str, Any]


@dataclass
class ResolvedAgentTools:
    """Result of resolving an agent definition's tool list against available tools."""

    has_wildcard: bool
    valid_tools: list[str]
    invalid_tools: list[str]
    resolved_tools: Tools
    allowed_agent_types: list[str] | None = None


@dataclass
class AgentToolResult:
    """Finalised result produced by an agent invocation."""

    agent_id: str
    agent_type: str | None = None
    content: list[dict[str, str]] = field(default_factory=list)
    total_tool_use_count: int = 0
    total_duration_ms: float = 0.0
    total_tokens: int = 0
    usage: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pydantic model for serialisation / deserialization (replaces Zod schema)
# ---------------------------------------------------------------------------


class _UsageServerToolUse(BaseModel):
    web_search_requests: int = 0
    web_fetch_requests: int = 0


class _UsageCacheCreation(BaseModel):
    ephemeral_1h_input_tokens: int = 0
    ephemeral_5m_input_tokens: int = 0


class AgentToolResultUsage(BaseModel):
    """Usage sub-schema for :class:`AgentToolResultSchema`."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    server_tool_use: _UsageServerToolUse | None = None
    service_tier: str | None = None  # 'standard' | 'priority' | 'batch'
    cache_creation: _UsageCacheCreation | None = None


class AgentToolResultContent(BaseModel):
    type: str = "text"
    text: str = ""


class AgentToolResultSchema(BaseModel):
    """Pydantic schema equivalent to the Zod ``agentToolResultSchema``."""

    agent_id: str
    agent_type: str | None = None
    content: list[AgentToolResultContent] = field(default_factory=list)
    total_tool_use_count: int = 0
    total_duration_ms: float = 0.0
    total_tokens: int = 0
    usage: AgentToolResultUsage = field(default_factory=AgentToolResultUsage)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _tool_matches_name(tool: Tool, name: str) -> bool:
    """Check whether *tool* matches *name* via primary name or alias."""
    return tool.name == name or name in getattr(tool, "aliases", [])


def _extract_text_content(
    blocks: Sequence[dict[str, Any]],
    separator: str = "",
) -> str:
    """Extract and concatenate ``text`` fields from text-typed content blocks."""
    return separator.join(
        b.get("text", "") for b in blocks if b.get("type") == "text"
    )


def _get_last_assistant_message(
    messages: list[Message],
) -> Message | None:
    """Return the last assistant message, scanning from the end."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("type") == "assistant":
            return messages[i]
    return None


def _get_token_count_from_usage(usage: dict[str, Any]) -> int:
    """Compute total token count from a usage dict."""
    return (
        usage.get("input_tokens", 0)
        + (usage.get("cache_creation_input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0)
        + usage.get("output_tokens", 0)
    )


# ---------------------------------------------------------------------------
# filterToolsForAgent
# ---------------------------------------------------------------------------


def filter_tools_for_agent(
    tools: Tools,
    is_built_in: bool,
    is_async: bool = False,
    permission_mode: PermissionMode | str | None = None,
) -> Tools:
    """Filter *tools* for consumption by a sub-agent.

    Parameters
    ----------
    tools:
        The full tool pool to filter.
    is_built_in:
        Whether the requesting agent is a built-in agent.
    is_async:
        Whether the agent runs asynchronously (background).
    permission_mode:
        Current permission mode (used to decide ExitPlanMode availability).
    """
    # Normalise permission_mode to a plain string for comparison
    pm = permission_mode.value if isinstance(permission_mode, PermissionMode) else permission_mode

    return [
        tool
        for tool in tools
        if _tool_allowed(tool, is_built_in, is_async, pm)
    ]


def _tool_allowed(
    tool: Tool,
    is_built_in: bool,
    is_async: bool,
    permission_mode: str | None,
) -> bool:
    """Decide whether a single *tool* is allowed for a sub-agent."""
    # MCP tools are always allowed
    if tool.name.startswith("mcp__"):
        return True

    # ExitPlanMode for agents in plan mode
    if _tool_matches_name(tool, EXIT_PLAN_MODE_V2_TOOL_NAME) and permission_mode == "plan":
        return True

    # Disallow lists
    if tool.name in ALL_AGENT_DISALLOWED_TOOLS:
        return False
    if not is_built_in and tool.name in CUSTOM_AGENT_DISALLOWED_TOOLS:
        return False

    # Async allow-list
    if is_async and tool.name not in ASYNC_AGENT_ALLOWED_TOOLS:
        # In-process teammate escape hatch
        if _tool_matches_name(tool, AGENT_TOOL_NAME):
            return True
        if tool.name in IN_PROCESS_TEAMMATE_ALLOWED_TOOLS:
            return True
        return False

    return True


# ---------------------------------------------------------------------------
# resolveAgentTools
# ---------------------------------------------------------------------------


def resolve_agent_tools(
    agent_definition: Any,
    available_tools: Tools,
    is_async: bool = False,
    is_main_thread: bool = False,
) -> ResolvedAgentTools:
    """Resolve and validate agent tools against the available pool.

    Handles wildcard expansion (``["*"]``) and validation in one place.
    """
    # Support both dict and object (dataclass) agent definitions
    if isinstance(agent_definition, dict):
        agent_tools = agent_definition.get("tools")
        disallowed_tools = agent_definition.get("disallowed_tools") or []
        source = agent_definition.get("source", "built-in")
        perm_mode = agent_definition.get("permission_mode")
    else:
        agent_tools = getattr(agent_definition, "tools", None)
        disallowed_tools = getattr(agent_definition, "disallowed_tools", None) or []
        source = getattr(agent_definition, "source", "built-in")
        perm_mode = getattr(agent_definition, "permission_mode", None)

    # When is_main_thread is true, skip filterToolsForAgent entirely — the
    # main thread's tool pool is already properly assembled.
    filtered_available: Tools = (
        available_tools
        if is_main_thread
        else filter_tools_for_agent(
            available_tools,
            is_built_in=(source == "built-in"),
            is_async=is_async,
            permission_mode=perm_mode,
        )
    )

    # Build disallowed set
    disallowed_set: set[str] = set()
    for tool_spec in disallowed_tools:
        parsed = permission_rule_value_from_string(tool_spec)
        disallowed_set.add(parsed.tool_name)

    # Remove disallowed from the filtered pool
    allowed_available = [t for t in filtered_available if t.name not in disallowed_set]

    # Wildcard: allow everything (after filtering disallowed)
    has_wildcard = agent_tools is None or (
        len(agent_tools) == 1 and agent_tools[0] == "*"
    )
    if has_wildcard:
        return ResolvedAgentTools(
            has_wildcard=True,
            valid_tools=[],
            invalid_tools=[],
            resolved_tools=allowed_available,
        )

    # Build name -> Tool map
    available_map: dict[str, Tool] = {t.name: t for t in allowed_available}

    valid_tools: list[str] = []
    invalid_tools: list[str] = []
    resolved: list[Tool] = []
    resolved_set: set[int] = set()  # id-based dedup
    allowed_agent_types: list[str] | None = None

    for tool_spec in agent_tools:
        parsed = permission_rule_value_from_string(tool_spec)
        tool_name = parsed.tool_name
        rule_content = parsed.rule_content

        # Agent tool carries allowedAgentTypes metadata
        if tool_name == AGENT_TOOL_NAME:
            if rule_content:
                allowed_agent_types = [s.strip() for s in rule_content.split(",")]
            if not is_main_thread:
                valid_tools.append(tool_spec)
                continue

        tool = available_map.get(tool_name)
        if tool is not None:
            valid_tools.append(tool_spec)
            if id(tool) not in resolved_set:
                resolved.append(tool)
                resolved_set.add(id(tool))
        else:
            invalid_tools.append(tool_spec)

    return ResolvedAgentTools(
        has_wildcard=False,
        valid_tools=valid_tools,
        invalid_tools=invalid_tools,
        resolved_tools=resolved,
        allowed_agent_types=allowed_agent_types,
    )


# ---------------------------------------------------------------------------
# countToolUses
# ---------------------------------------------------------------------------


def count_tool_uses(messages: list[Message]) -> int:
    """Count total ``tool_use`` blocks across all assistant messages."""
    count = 0
    for m in messages:
        if m.get("type") != "assistant":
            continue
        for block in m.get("message", m).get("content", []):
            if block.get("type") == "tool_use":
                count += 1
    return count


# ---------------------------------------------------------------------------
# finalizeAgentTool
# ---------------------------------------------------------------------------


def finalize_agent_tool(
    agent_messages: list[Message],
    agent_id: str,
    metadata: dict[str, Any],
) -> AgentToolResult:
    """Produce a final :class:`AgentToolResult` from the agent conversation.

    Parameters
    ----------
    agent_messages:
        Accumulated message list from the agent run.
    agent_id:
        Unique identifier for this agent invocation.
    metadata:
        Dict with keys: ``prompt``, ``resolved_agent_model``,
        ``is_built_in_agent``, ``start_time``, ``agent_type``, ``is_async``.
    """
    prompt: str = metadata["prompt"]
    resolved_agent_model: str = metadata["resolved_agent_model"]
    is_built_in_agent: bool = metadata["is_built_in_agent"]
    start_time: float = metadata["start_time"]
    agent_type: str = metadata["agent_type"]
    is_async: bool = metadata["is_async"]

    last_assistant = _get_last_assistant_message(agent_messages)
    if last_assistant is None:
        raise RuntimeError("No assistant messages found")

    inner = last_assistant.get("message", last_assistant)

    # Extract text content; fall back to the most recent assistant message
    # that has text content when the final message is pure tool_use.
    content = [b for b in inner.get("content", []) if b.get("type") == "text"]
    if not content:
        for i in range(len(agent_messages) - 1, -1, -1):
            m = agent_messages[i]
            if m.get("type") != "assistant":
                continue
            inner_m = m.get("message", m)
            text_blocks = [b for b in inner_m.get("content", []) if b.get("type") == "text"]
            if text_blocks:
                content = text_blocks
                break

    usage = inner.get("usage", {})
    total_tokens = _get_token_count_from_usage(usage)
    total_tool_use_count = count_tool_uses(agent_messages)
    total_duration_ms = time.time() * 1000 - start_time

    logger.info(
        "agent_tool_completed  agent_type=%s  model=%s  tool_uses=%d  "
        "duration_ms=%.0f  tokens=%d  built_in=%s  async=%s",
        agent_type,
        resolved_agent_model,
        total_tool_use_count,
        total_duration_ms,
        total_tokens,
        is_built_in_agent,
        is_async,
    )

    return AgentToolResult(
        agent_id=agent_id,
        agent_type=agent_type,
        content=content,
        total_duration_ms=total_duration_ms,
        total_tokens=total_tokens,
        total_tool_use_count=total_tool_use_count,
        usage=usage,
    )


# ---------------------------------------------------------------------------
# getLastToolUseName
# ---------------------------------------------------------------------------


def get_last_tool_use_name(message: Message) -> str | None:
    """Return the name of the last ``tool_use`` block in an assistant message."""
    if message.get("type") != "assistant":
        return None
    inner = message.get("message", message)
    blocks = inner.get("content", [])
    for i in range(len(blocks) - 1, -1, -1):
        if blocks[i].get("type") == "tool_use":
            return blocks[i].get("name")
    return None


# ---------------------------------------------------------------------------
# emitTaskProgress  (stub — full implementation requires SDK progress bus)
# ---------------------------------------------------------------------------


def emit_task_progress(
    tracker: ProgressTracker,
    task_id: str,
    tool_use_id: str | None,
    description: str,
    start_time: float,
    last_tool_name: str,
) -> None:
    """Emit a task-progress event to the SDK progress bus (stub)."""
    progress = get_progress_update(tracker)
    # In the full implementation this would call:
    #   emit_task_progress_event({...})
    logger.debug(
        "task_progress  task_id=%s  tool=%s  tokens=%d  tool_uses=%d",
        task_id,
        last_tool_name,
        progress.token_count,
        progress.tool_use_count,
    )


# ---------------------------------------------------------------------------
# classifyHandoffIfNeeded  (stub — feature-gated)
# ---------------------------------------------------------------------------


async def classify_handoff_if_needed(
    *,
    agent_messages: list[Message],
    tools: Tools,
    tool_permission_context: Any,
    abort_signal: asyncio.Event,
    subagent_type: str,
    total_tool_use_count: int,
) -> str | None:
    """Classify sub-agent handoff for security (stub — feature-gated).

    Returns a warning string if the classifier flags the output, or ``None``.
    """
    # TRANSCRIPT_CLASSIFIER is not yet implemented in the Python port.
    return None


# ---------------------------------------------------------------------------
# extractPartialResult
# ---------------------------------------------------------------------------


def extract_partial_result(messages: list[Message]) -> str | None:
    """Extract a partial result string from accumulated agent messages.

    Used when an async agent is killed to preserve what it accomplished.
    Returns ``None`` if no text content is found.
    """
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("type") != "assistant":
            continue
        inner = m.get("message", m)
        text = _extract_text_content(inner.get("content", []), "\n")
        if text:
            return text
    return None


# ---------------------------------------------------------------------------
# runAsyncAgentLifecycle
# ---------------------------------------------------------------------------


async def run_async_agent_lifecycle(
    *,
    task_id: str,
    abort_event: asyncio.Event,
    make_stream: Callable[
        [Callable[[Any], None] | None],
        AsyncGenerator[Message, None],
    ],
    metadata: dict[str, Any],
    description: str,
    tool_use_context: Any,
    root_set_app_state: Callable[[Callable[[Any], Any]], None],
    agent_id_for_cleanup: str,
    enable_summarization: bool = False,
    get_worktree_result: Callable[[], Any] | None = None,
) -> None:
    """Drive a background agent from spawn to terminal notification.

    Shared between AgentTool's async-from-start path and resumeAgentBackground.

    Parameters
    ----------
    task_id:
        Identifier for the task in the module-level task store.
    abort_event:
        ``asyncio.Event`` that is set when the agent should be killed.
    make_stream:
        Factory returning an ``AsyncGenerator`` that yields agent messages.
    metadata:
        Dict with the same keys accepted by :func:`finalize_agent_tool`.
    description:
        Short human-readable description of the agent task.
    tool_use_context:
        Opaque context object carrying ``options.tools`` and ``tool_use_id``.
    root_set_app_state:
        Mutator for the root app state (replaces TS ``rootSetAppState``).
    agent_id_for_cleanup:
        Agent ID used for cleanup bookkeeping (skills, dump state).
    enable_summarization:
        Whether to start background summarization (stub).
    get_worktree_result:
        Optional async callable returning ``{worktree_path?, worktree_branch?}``.
    """
    stop_summarization: Callable[[], None] | None = None
    agent_messages: list[Message] = []

    try:
        tracker = create_progress_tracker()

        on_cache_safe_params: Callable[[Any], None] | None = None
        if enable_summarization:
            # Summarization is not yet wired in the Python port.
            pass

        stream = make_stream(on_cache_safe_params)
        async for message in stream:
            agent_messages.append(message)

            # Append immediately when UI holds the task (retain).
            root_set_app_state(
                lambda prev, _msg=message: _append_retain_message(prev, task_id, _msg)
            )

            # Update progress tracker
            tools = getattr(
                getattr(tool_use_context, "options", None), "tools", []
            )
            update_progress_from_message(tracker, message)

            update_agent_progress(task_id, get_progress_update(tracker))

            last_tool_name = get_last_tool_use_name(message)
            if last_tool_name:
                emit_task_progress(
                    tracker,
                    task_id,
                    getattr(tool_use_context, "tool_use_id", None),
                    description,
                    metadata["start_time"],
                    last_tool_name,
                )

        # Stream finished — stop summarization if active
        if stop_summarization is not None:
            stop_summarization()

        # Finalize result
        agent_result = finalize_agent_tool(agent_messages, task_id, metadata)

        # Mark task completed FIRST so TaskOutput(block=true) unblocks
        await complete_agent_task(
            {
                "agent_id": agent_result.agent_id,
                "agent_type": agent_result.agent_type,
                "content": agent_result.content,
                "total_tool_use_count": agent_result.total_tool_use_count,
                "total_duration_ms": agent_result.total_duration_ms,
                "total_tokens": agent_result.total_tokens,
                "usage": agent_result.usage,
            }
        )

        final_message = _extract_text_content(agent_result.content, "\n")

        # Handoff classifier (stub — always passes through)
        handoff_warning = await classify_handoff_if_needed(
            agent_messages=agent_messages,
            tools=getattr(
                getattr(tool_use_context, "options", None), "tools", []
            ),
            tool_permission_context=None,
            abort_signal=abort_event,
            subagent_type=metadata["agent_type"],
            total_tool_use_count=agent_result.total_tool_use_count,
        )
        if handoff_warning:
            final_message = f"{handoff_warning}\n\n{final_message}"

        # Worktree result
        worktree_result: dict[str, Any] = {}
        if get_worktree_result is not None:
            worktree_result = await get_worktree_result()

        enqueue_agent_notification(
            task_id=task_id,
            description=description,
            status="completed",
            final_message=final_message,
            usage={
                "total_tokens": get_token_count_from_tracker(tracker),
                "tool_uses": agent_result.total_tool_use_count,
                "duration_ms": agent_result.total_duration_ms,
            },
            tool_use_id=getattr(tool_use_context, "tool_use_id", None),
            **worktree_result,
        )

    except asyncio.CancelledError:
        # Abort / kill path
        if stop_summarization is not None:
            stop_summarization()

        await kill_async_agent(task_id)

        logger.info(
            "agent_tool_terminated  agent_type=%s  model=%s  "
            "duration_ms=%.0f  async=True  built_in=%s  reason=user_kill_async",
            metadata.get("agent_type"),
            metadata.get("resolved_agent_model"),
            time.time() * 1000 - metadata.get("start_time", 0),
            metadata.get("is_built_in_agent"),
        )

        worktree_result: dict[str, Any] = {}  # type: ignore[no-redef]
        if get_worktree_result is not None:
            worktree_result = await get_worktree_result()

        partial_result = extract_partial_result(agent_messages)
        enqueue_agent_notification(
            task_id=task_id,
            description=description,
            status="killed",
            tool_use_id=getattr(tool_use_context, "tool_use_id", None),
            final_message=partial_result,
            **worktree_result,
        )

    except Exception as exc:
        if stop_summarization is not None:
            stop_summarization()

        msg = str(exc)
        await fail_agent_task(task_id, msg)

        worktree_result: dict[str, Any] = {}  # type: ignore[no-redef]
        if get_worktree_result is not None:
            worktree_result = await get_worktree_result()

        enqueue_agent_notification(
            task_id=task_id,
            description=description,
            status="failed",
            error=msg,
            tool_use_id=getattr(tool_use_context, "tool_use_id", None),
            **worktree_result,
        )


# ---------------------------------------------------------------------------
# Internal helpers for run_async_agent_lifecycle
# ---------------------------------------------------------------------------


def _append_retain_message(
    prev: Any,
    task_id: str,
    message: Message,
) -> Any:
    """Append a message to a retained task's message list in app state.

    Mirrors the TS pattern: ``rootSetAppState(prev => { ... })``.
    ``prev`` is expected to carry a ``tasks`` dict keyed by task_id.
    """
    tasks = getattr(prev, "tasks", None) or {}
    t = tasks.get(task_id)
    if t is None or not is_local_agent_task(t) or not getattr(t, "retain", False):
        return prev
    base = getattr(t, "messages", None) or []
    # Return a shallow-updated state (dataclass or dict)
    if isinstance(prev, dict):
        new_task = {**t, "messages": [*base, message]} if isinstance(t, dict) else t
        return {**prev, "tasks": {**tasks, task_id: new_task}}
    # dataclass-style: mutate in place (simplest for Python)
    t.messages = [*base, message]
    return prev
