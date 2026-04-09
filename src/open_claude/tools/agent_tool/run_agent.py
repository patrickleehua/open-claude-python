"""Agent execution engine — ported from Claude-Code-rev runAgent.ts.

Provides the ``run_agent()`` async generator that drives a sub-agent's
query loop, plus helpers for system-prompt construction and message filtering.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from open_claude.context.prompt_builder import enhance_system_prompt_with_env_details
from open_claude.tasks.local_agent_task import (
    AgentProgress,
    ProgressTracker,
    create_progress_tracker,
    get_token_count_from_tracker,
    update_progress_from_message,
)
from open_claude.tools.agent_tool.agent_tool_utils import resolve_agent_tools
from open_claude.tools.base import Tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent model resolution
# ---------------------------------------------------------------------------


def get_agent_model(
    agent_model: str | None,
    parent_model: str,
    tool_specified_model: str | None = None,
) -> str:
    """Resolve the effective model for a sub-agent.

    Simplified version of the TS ``getAgentModel``:
    - ``CLAUDE_CODE_SUBAGENT_MODEL`` env takes precedence
    - ``tool_specified_model`` (from the Agent tool call) next
    - ``agent_model`` from the agent definition next
    - ``"inherit"`` → use *parent_model*
    """
    env_model = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL")
    if env_model:
        return env_model

    if tool_specified_model:
        return tool_specified_model

    resolved = agent_model or "inherit"
    if resolved == "inherit":
        return parent_model
    return resolved


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------


def filter_incomplete_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter out assistant messages that have tool_use blocks without results.

    Prevents API errors when messages are reused across context boundaries
    (e.g. fork subagent, compacted transcripts).
    """
    tool_use_ids_with_results: set[str] = set()

    for msg in messages:
        if msg.get("type") == "user" or msg.get("role") == "user":
            content = msg.get("message", msg).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tid = block.get("tool_use_id")
                        if tid:
                            tool_use_ids_with_results.add(tid)

    def _has_incomplete(msg: dict[str, Any]) -> bool:
        if msg.get("type") != "assistant" and msg.get("role") != "assistant":
            return False
        content = msg.get("message", msg).get("content", [])
        if not isinstance(content, list):
            return False
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("id")
                and block["id"] not in tool_use_ids_with_results
            ):
                return True
        return False

    return [m for m in messages if not _has_incomplete(m)]


# ---------------------------------------------------------------------------
# Agent system prompt
# ---------------------------------------------------------------------------


async def get_agent_system_prompt(
    agent_definition: dict[str, Any],
    resolved_agent_model: str,
    additional_working_directories: list[str] | None = None,
    resolved_tools: list[Tool] | None = None,
) -> list[str]:
    """Build the system prompt for an agent.

    Mirrors TS ``getAgentSystemPrompt``:
    1. Use the agent definition's ``system_prompt`` (or ``getSystemPrompt()``)
    2. Enhance with env details via ``enhanceSystemPromptWithEnvDetails``
    """
    enabled_tool_names: set[str] = set()
    if resolved_tools:
        enabled_tool_names = {t.name for t in resolved_tools}

    # Get the base prompt
    get_prompt_fn = agent_definition.get("get_system_prompt")
    if callable(get_prompt_fn):
        try:
            base_prompt = get_prompt_fn()
        except Exception:
            base_prompt = agent_definition.get("system_prompt", "")
    else:
        base_prompt = agent_definition.get("system_prompt", "")

    prompts = [base_prompt] if base_prompt else []

    try:
        return await enhance_system_prompt_with_env_details(
            existing_system_prompt=prompts,
            model=resolved_agent_model,
            additional_working_directories=additional_working_directories,
            enabled_tool_names=enabled_tool_names,
        )
    except Exception:
        # Fallback: use DEFAULT_AGENT_PROMPT
        from open_claude.constants.prompts import DEFAULT_AGENT_PROMPT

        return await enhance_system_prompt_with_env_details(
            existing_system_prompt=[DEFAULT_AGENT_PROMPT],
            model=resolved_agent_model,
            additional_working_directories=additional_working_directories,
            enabled_tool_names=enabled_tool_names,
        )


# ---------------------------------------------------------------------------
# run_agent() — the main async generator
# ---------------------------------------------------------------------------


@dataclass
class RunAgentParams:
    """Parameters for run_agent()."""

    agent_definition: dict[str, Any]
    prompt_messages: list[dict[str, Any]]
    is_async: bool = False
    model: str | None = None
    max_turns: int | None = None
    available_tools: list[Tool] = field(default_factory=list)
    query_source: str = "agent"
    override: dict[str, Any] | None = None
    description: str | None = None
    fork_context_messages: list[dict[str, Any]] | None = None


async def run_agent(
    params: RunAgentParams,
    *,
    client: Any | None = None,
    tool_executor: Any | None = None,
    parent_model: str = "claude-sonnet-4-20250514",
) -> AsyncGenerator[dict[str, Any], None]:
    """Execute a sub-agent and yield messages.

    This is the core agent execution loop, ported from TS ``runAgent()``:

    1. Resolve agent model
    2. Build system prompt
    3. Filter tools via ``resolve_agent_tools()``
    4. Create a sub-QueryEngine
    5. Run the query loop, yielding messages
    6. Handle abort / error / cleanup
    """
    from open_claude.query.engine import QueryEngine
    from open_claude.services.api.client import get_client

    agent_def = params.agent_definition
    override = params.override or {}

    # 1. Resolve model
    resolved_model = get_agent_model(
        agent_model=agent_def.get("model"),
        parent_model=parent_model,
        tool_specified_model=params.model,
    )

    # 2. Agent ID
    agent_id = override.get("agent_id") or str(uuid.uuid4())

    # 3. Filter tools
    resolved_tools_result = resolve_agent_tools(
        agent_definition=agent_def,
        available_tools=params.available_tools,
        is_async=params.is_async,
    )
    resolved_tools = resolved_tools_result.resolved_tools

    # 4. Build system prompt
    system_prompt_override = override.get("system_prompt")
    if system_prompt_override:
        agent_system_prompt = system_prompt_override
        if isinstance(agent_system_prompt, list):
            agent_system_prompt = "\n\n".join(agent_system_prompt)
    else:
        prompt_sections = await get_agent_system_prompt(
            agent_definition=agent_def,
            resolved_agent_model=resolved_model,
            resolved_tools=resolved_tools,
        )
        agent_system_prompt = "\n\n".join(prompt_sections)

    # 5. Build initial messages
    context_messages: list[dict[str, Any]] = []
    if params.fork_context_messages:
        context_messages = filter_incomplete_tool_calls(params.fork_context_messages)

    initial_messages = [*context_messages, *params.prompt_messages]

    # 6. Abort event
    abort_event: asyncio.Event | None = override.get("abort_event")
    if abort_event is None and params.is_async:
        import asyncio
        abort_event = asyncio.Event()

    # 7. Create sub-QueryEngine
    api_client = client or get_client()
    engine = QueryEngine(
        client=api_client,
        model=resolved_model,
        system_prompt=agent_system_prompt,
    )

    # Build tool definitions for the API
    tool_defs = [t.get_api_definition() for t in resolved_tools] if resolved_tools else None

    # Build a tool executor that dispatches to the resolved tools.
    # Must return ToolExecutionResult — query_with_tool_loop accesses .output.
    from open_claude.schemas import ToolExecutionResult

    async def _tool_executor(tool_name: str, tool_input: dict) -> ToolExecutionResult:
        if tool_executor:
            result = await tool_executor(tool_name, tool_input)
            if isinstance(result, ToolExecutionResult):
                return result
            return ToolExecutionResult(output=str(result))

        # Find the tool
        for t in resolved_tools:
            if t.name == tool_name:
                # Create input model instance
                input_cls = t.input_schema
                if isinstance(tool_input, dict):
                    try:
                        input_instance = input_cls(**tool_input)
                    except Exception:
                        input_instance = tool_input
                else:
                    input_instance = tool_input
                result = await t.call(input_instance)
                if isinstance(result, ToolExecutionResult):
                    return result
                return ToolExecutionResult(output=str(result))

        return ToolExecutionResult(output=f"Error: Tool '{tool_name}' not found", is_error=True)

    # 8. Run the query loop
    messages_copy = list(initial_messages)
    effective_max_turns = params.max_turns or agent_def.get("max_turns") or 50

    try:
        async for event in engine.query_with_tool_loop(
            messages=messages_copy,
            tools=tool_defs,
            tool_executor=_tool_executor,
            max_turns=effective_max_turns,
        ):
            # Check abort
            if abort_event and abort_event.is_set():
                break

            # Yield assistant messages, tool results, progress
            if event.type in ("text", "tool_use", "tool_result", "thinking"):
                yield {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": _event_to_content(event),
                    },
                    "agent_id": agent_id,
                    "event_type": event.type,
                }
            elif event.type == "error":
                yield {
                    "type": "error",
                    "message": str(event.content),
                    "agent_id": agent_id,
                }
            elif event.type == "result":
                yield {
                    "type": "result",
                    "result": {
                        "agent_id": agent_id,
                        "agent_type": agent_def.get("agent_type", "general-purpose"),
                        "total_turns": getattr(event.content, "total_turns", 0),
                        "duration_ms": getattr(event.content, "duration_ms", 0),
                        "usage": {},
                    },
                    "agent_id": agent_id,
                }
    except Exception as exc:
        logger.exception("run_agent error for %s", agent_id)
        yield {
            "type": "error",
            "message": str(exc),
            "agent_id": agent_id,
        }
    finally:
        # Cleanup: clear messages to release memory
        initial_messages.clear()


def _event_to_content(event: Any) -> list[dict[str, Any]]:
    """Convert a StreamEvent to content blocks."""
    blocks: list[dict[str, Any]] = []
    if event.type == "text" and event.content:
        blocks.append({"type": "text", "text": event.content})
    elif event.type == "tool_use" and hasattr(event, "content"):
        block = event.content
        blocks.append({
            "type": "tool_use",
            "id": getattr(block, "id", ""),
            "name": getattr(block, "name", ""),
            "input": getattr(block, "input", {}),
        })
    elif event.type == "tool_result" and hasattr(event, "content"):
        tr = event.content
        blocks.append({
            "type": "tool_result",
            "tool_use_id": getattr(tr, "tool_call_id", ""),
            "content": getattr(tr, "output", ""),
            "is_error": getattr(tr, "is_error", False),
        })
    elif event.type == "thinking" and event.content:
        blocks.append({"type": "thinking", "thinking": event.content})
    return blocks if blocks else [{"type": "text", "text": ""}]


# Need asyncio import for abort_event creation
import asyncio  # noqa: E402
