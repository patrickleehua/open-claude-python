"""AgentTool - launches specialized agents for complex tasks (name: 'Agent').

Ported from Claude-Code-rev AgentTool.tsx.  The ``call()`` method resolves
an agent definition, builds its prompt / tools, then either runs it
synchronously (foreground) or dispatches to the async lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from open_claude.tasks.local_agent_task import (
    LocalAgentTaskState,
    complete_agent_task,
    create_progress_tracker,
    enqueue_agent_notification,
    fail_agent_task,
    get_token_count_from_tracker,
    kill_async_agent,
    register_agent_foreground,
    register_async_agent,
    update_agent_progress,
    update_progress_from_message,
)
from open_claude.tools.agent_tool.agent_tool_utils import (
    count_tool_uses,
    extract_partial_result,
    finalize_agent_tool,
    resolve_agent_tools,
    run_async_agent_lifecycle,
)
from open_claude.tools.agent_tool.built_in.agents import (
    GENERAL_PURPOSE_AGENT,
    BuiltInAgentDefinition,
)
from open_claude.tools.agent_tool.run_agent import RunAgentParams, run_agent
from open_claude.tools.base import Tool, ToolError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class AgentToolInput(BaseModel):
    """Input schema for AgentTool."""

    prompt: str = Field(
        description="The task description to send to the agent"
    )
    description: str = Field(
        description="A short description (3-5 words) of what the agent will do"
    )
    subagent_type: str | None = Field(
        default=None,
        description="The type of agent to use. If omitted, the general-purpose agent is used.",
    )
    model: str | None = Field(
        default=None,
        description="Optional model override (sonnet, opus, haiku).",
    )
    run_in_background: bool = Field(
        default=False,
        description="Run the agent in the background",
    )
    name: str | None = Field(
        default=None,
        description="A short name for the agent (1-2 words, lowercase)",
    )
    team_name: str | None = Field(
        default=None,
        description="Team name for spawning in swarm mode.",
    )
    mode: str | None = Field(
        default=None,
        description="Permission mode for spawned teammate.",
    )
    isolation: str | None = Field(
        default=None,
        description="Isolation mode: 'worktree' creates a temp git worktree.",
    )
    cwd: str | None = Field(
        default=None,
        description="Absolute path to run the agent in.",
    )


# ---------------------------------------------------------------------------
# Builtin agent registry
# ---------------------------------------------------------------------------


def _get_builtin_agents() -> dict[str, BuiltInAgentDefinition]:
    """Return built-in agent definitions keyed by agent_type."""
    from open_claude.tools.agent_tool.built_in.agents import (
        EXPLORE_AGENT,
        PLAN_AGENT,
        VERIFICATION_AGENT,
    )

    return {
        a.agent_type: a
        for a in [GENERAL_PURPOSE_AGENT, EXPLORE_AGENT, PLAN_AGENT, VERIFICATION_AGENT]
    }


def _agent_def_to_dict(agent: BuiltInAgentDefinition) -> dict[str, Any]:
    """Convert a BuiltInAgentDefinition to a plain dict for run_agent."""
    return {
        "agent_type": agent.agent_type,
        "system_prompt": agent.system_prompt,
        "disallowed_tools": agent.disallowed_tools,
        "model": agent.model,
        "background": agent.background,
        "color": agent.color,
        "source": "built-in",
        "when_to_use": agent.when_to_use,
    }


# ---------------------------------------------------------------------------
# AgentTool
# ---------------------------------------------------------------------------


class AgentTool(Tool):
    """Launches specialized agents for complex, multi-step tasks."""

    @property
    def name(self) -> str:
        return "Agent"

    @property
    def input_schema(self) -> type[BaseModel]:
        return AgentToolInput

    @property
    def description(self) -> str:
        return (
            "Launch a new agent to handle complex, multi-step tasks autonomously.\n"
            "\n"
            "The Agent tool launches specialized agents (subprocesses) that autonomously handle "
            "complex tasks. Each agent type has specific capabilities and tools available to it.\n"
            "\n"
            "When using the Agent tool, specify a subagent_type parameter to select which agent "
            "type to use. If omitted, the general-purpose agent is used.\n"
            "\n"
            "When NOT to use the Agent tool:\n"
            "- If you want to read a specific file path, use the Read tool or the Glob tool instead "
            "of the Agent tool, to find the match more quickly\n"
            '- If you are searching for a specific class definition like "class Foo", use the Glob '
            "tool instead, to find the match more quickly\n"
            "- If you are searching for code within a specific file or set of 2-3 files, use the "
            "Read tool instead of the Agent tool, to find the match more quickly\n"
            "- Other tasks that are not related to the agent descriptions above\n"
            "\n"
            "Usage notes:\n"
            "- Always include a short description (3-5 words) summarizing what the agent will do\n"
            "- Launch multiple agents concurrently whenever possible, to maximize performance; to "
            "do that, use a single message with multiple tool uses\n"
            "- When the agent is done, it will return a single message back to you. The result "
            "returned by the agent is not visible to the user. To show the user the result, you "
            "should send a text message back to the user with a concise summary of the result.\n"
            "- You can optionally run agents in the background using the run_in_background parameter. "
            "When an agent runs in the background, you will be automatically notified when it "
            "completes — do NOT sleep, poll, or proactively check on its progress. Continue with "
            "other work or respond to the user instead.\n"
            "- **Foreground vs background**: Use foreground (default) when you need the agent's "
            "results before you can proceed — e.g., research agents whose findings inform your "
            "next steps. Use background when you have genuinely independent work to do in parallel.\n"
            "- The agent's outputs should generally be trusted\n"
            "- Clearly tell the agent whether you expect it to write code or just to do research "
            "(search, file reads, web fetches, etc.)\n"
            "- If the user specifies that they want you to run agents \"in parallel\", you MUST send "
            "a single message with multiple Agent tool use content blocks. For example, if you need "
            "to launch both a build-validator agent and a test-runner agent in parallel, send a "
            "single message with both tool calls.\n"
            "\n"
            "## Writing the prompt\n"
            "\n"
            "Brief the agent like a smart colleague who just walked into the room — it hasn't seen "
            "this conversation, doesn't know what you've tried, doesn't understand why this task matters.\n"
            "- Explain what you're trying to accomplish and why.\n"
            "- Describe what you've already learned or ruled out.\n"
            "- Give enough context about the surrounding problem that the agent can make judgment "
            "calls rather than just following a narrow instruction.\n"
            '- If you need a short response, say so ("report in under 200 words").\n'
            "- Lookups: hand over the exact command. Investigations: hand over the question — "
            "prescribed steps become dead weight when the premise is wrong.\n"
            "\n"
            "Terse command-style prompts produce shallow, generic work.\n"
            "\n"
            '**Never delegate understanding.** Don\'t write "based on your findings, fix the bug" or '
            '"based on the research, implement it." Those phrases push synthesis onto the agent instead '
            "of doing it yourself. Write prompts that prove you understood: include file paths, line "
            "numbers, what specifically to change."
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return True

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    # ------------------------------------------------------------------
    # call()
    # ------------------------------------------------------------------

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: AgentToolInput
        start_time = time.time() * 1000

        # 1. Resolve agent type → definition
        agent_type = data.subagent_type or GENERAL_PURPOSE_AGENT.agent_type
        agent_def = self._resolve_agent(agent_type)
        if agent_def is None:
            builtins = list(_get_builtin_agents().keys())
            raise ToolError(
                f"Agent type '{agent_type}' not found. "
                f"Available agents: {', '.join(builtins)}"
            )

        agent_dict = _agent_def_to_dict(agent_def)
        is_async = data.run_in_background or agent_def.background

        # 2. Gather available tools
        available_tools = self._get_available_tools()

        # 3. Build prompt messages
        prompt_messages = [
            {"role": "user", "content": data.prompt}
        ]

        # 4. Determine parent model
        parent_model = os.environ.get("CLAUDE_CODE_MODEL", "claude-sonnet-4-20250514")

        # --- SYNC PATH ---
        if not is_async:
            return await self._run_sync(
                agent_dict=agent_dict,
                prompt_messages=prompt_messages,
                available_tools=available_tools,
                parent_model=parent_model,
                data=data,
                start_time=start_time,
            )

        # --- ASYNC PATH ---
        return await self._run_async(
            agent_dict=agent_dict,
            prompt_messages=prompt_messages,
            available_tools=available_tools,
            parent_model=parent_model,
            data=data,
            start_time=start_time,
        )

    # ------------------------------------------------------------------
    # Sync execution
    # ------------------------------------------------------------------

    async def _run_sync(
        self,
        *,
        agent_dict: dict[str, Any],
        prompt_messages: list[dict[str, Any]],
        available_tools: list[Any],
        parent_model: str,
        data: AgentToolInput,
        start_time: float,
    ) -> str:
        """Run agent synchronously (foreground) and return the result."""
        params = RunAgentParams(
            agent_definition=agent_dict,
            prompt_messages=prompt_messages,
            is_async=False,
            model=data.model,
            available_tools=available_tools,
            query_source=f"agent:{agent_dict.get('agent_type', 'general-purpose')}",
            description=data.description,
        )

        agent_messages: list[dict[str, Any]] = []
        tracker = create_progress_tracker()

        async for msg in run_agent(params, parent_model=parent_model):
            agent_messages.append(msg)
            if msg.get("type") == "assistant":
                update_progress_from_message(tracker, msg)

        # Extract final result
        duration_ms = time.time() * 1000 - start_time
        result = finalize_agent_tool(
            agent_messages=agent_messages,
            agent_id=str(uuid.uuid4()),
            metadata={
                "prompt": data.prompt,
                "resolved_agent_model": parent_model,
                "is_built_in_agent": True,
                "start_time": start_time,
                "agent_type": agent_dict.get("agent_type", "general-purpose"),
                "is_async": False,
            },
        )

        # Format result for the caller
        text_parts = []
        for block in result.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))

        final_text = "\n".join(t for t in text_parts if t)
        if not final_text:
            final_text = f"Agent completed in {duration_ms:.0f}ms with {result.get('total_tool_use_count', 0)} tool uses."

        return final_text

    # ------------------------------------------------------------------
    # Async execution
    # ------------------------------------------------------------------

    async def _run_async(
        self,
        *,
        agent_dict: dict[str, Any],
        prompt_messages: list[dict[str, Any]],
        available_tools: list[Any],
        parent_model: str,
        data: AgentToolInput,
        start_time: float,
    ) -> str:
        """Run agent asynchronously (background) and return immediately."""
        agent_id = str(uuid.uuid4())

        # Register the background task
        task = await register_async_agent(
            agent_id=agent_id,
            description=data.description,
            prompt=data.prompt,
            selected_agent=agent_dict,
        )
        abort_event = task.abort_event or asyncio.Event()

        metadata = {
            "prompt": data.prompt,
            "resolved_agent_model": parent_model,
            "is_built_in_agent": True,
            "start_time": start_time,
            "agent_type": agent_dict.get("agent_type", "general-purpose"),
            "is_async": True,
        }

        # Stream factory that creates a new run_agent() generator per lifecycle
        def make_stream(
            _on_cache_safe_params: Any = None,
        ):
            return run_agent(
                RunAgentParams(
                    agent_definition=agent_dict,
                    prompt_messages=prompt_messages,
                    is_async=True,
                    model=data.model,
                    available_tools=available_tools,
                    query_source=f"agent:{agent_dict.get('agent_type', 'general-purpose')}",
                    description=data.description,
                ),
                parent_model=parent_model,
            )

        # Minimal tool_use_context expected by run_async_agent_lifecycle
        class _ToolUseContext:
            def __init__(self, tools: list[Any]) -> None:
                self.options = type("Options", (), {"tools": tools})()
                self.tool_use_id: str | None = None

        tool_use_context = _ToolUseContext(available_tools)

        # root_set_app_state: no-op stub (full implementation would update TUI)
        def root_set_app_state(mutator: Any) -> None:
            pass

        # Schedule the async lifecycle in the background
        async def _lifecycle() -> None:
            await run_async_agent_lifecycle(
                task_id=agent_id,
                abort_event=abort_event,
                make_stream=make_stream,
                metadata=metadata,
                description=data.description,
                tool_use_context=tool_use_context,
                root_set_app_state=root_set_app_state,
                agent_id_for_cleanup=agent_id,
            )

        asyncio.create_task(_lifecycle())

        output_path = f".claude/tasks/{agent_id}"
        return (
            f"Agent launched in background.\n\n"
            f"Agent ID: {agent_id}\n"
            f"Description: {data.description}\n"
            f"Output file: {output_path}\n\n"
            f"You will be notified when the agent completes. "
            f"Do NOT sleep, poll, or proactively check on its progress."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_agent(self, agent_type: str) -> BuiltInAgentDefinition | None:
        """Find the agent definition for the given type."""
        builtins = _get_builtin_agents()

        # Try exact match first
        if agent_type in builtins:
            return builtins[agent_type]

        # Try case-insensitive match
        lower = agent_type.lower()
        for key, agent in builtins.items():
            if key.lower() == lower:
                return agent

        return None

    def _get_available_tools(self) -> list[Any]:
        """Get all currently available tools for the agent."""
        try:
            from open_claude.tools import get_all_tools
            return get_all_tools()
        except Exception:
            logger.exception("Failed to load tools for sub-agent")
            return []
