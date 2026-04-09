"""Core agentic loop: stream API responses, detect tool calls, execute tools, loop."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, AsyncGenerator

from anthropic import AsyncAnthropic

from open_claude.constants import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, SYSTEM_PROMPT_DEFAULT
from open_claude.schemas.permissions import PermissionAskDecision, PermissionDecision, ToolPermissionContext
from open_claude.utils.permissions.pipeline import has_permissions_to_use_tool
from open_claude.query.message_builder import (
    build_assistant_message,
    build_tool_result_message,
    build_user_message,
    normalize_messages,
)
from open_claude.query.streaming import parse_stream
from open_claude.query.types import ContentBlock, QueryResult, StreamEvent, TokenUsage
from open_claude.schemas import ToolExecutionResult, ToolResult
from open_claude.utils.diff import display_data_for_preview, preview_for_tool_input
from open_claude.utils.message_queue_manager import (
    drain_pending_task_notifications,
    get_commands_by_max_priority,
    remove_commands,
)


class QueryEngine:
    """Core agentic loop that streams API responses, detects tool calls, and loops.

    Usage:
        engine = QueryEngine(client)
        async for event in engine.query(messages, tools=tool_defs):
            if event.type == 'text':
                print(event.content)
            elif event.type == 'tool_use':
                # handle tool call
                ...

    For automatic tool execution, use ``query_with_tool_loop`` with a
    ``tool_executor`` callback.
    """

    def __init__(
        self,
        client: AsyncAnthropic,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        system_prompt: str | list[str] = SYSTEM_PROMPT_DEFAULT,
        thinking_budget: int | None = 10000,
        permission_context: ToolPermissionContext | None = None,
        permission_handler: Callable[
            [str, dict[str, Any], ToolPermissionContext, Callable[[ToolPermissionContext], None], str, PermissionAskDecision],
            Awaitable[PermissionDecision],
        ]
        | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.thinking_budget = thinking_budget
        self.permission_context = permission_context or ToolPermissionContext()
        self.permission_handler = permission_handler
        self._total_usage = TokenUsage()

    async def query(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        abort_event: asyncio.Event | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Run a single agentic turn: stream API call and parse the response.

        This method performs ONE API call and yields StreamEvents for each
        completed content block. It does NOT loop on tool_use -- the caller
        is responsible for executing tools and calling query() again with
        tool_result messages appended.

        Yields:
            StreamEvent with types: 'text', 'tool_use', 'thinking',
            'usage', 'error', 'stop'.
        """
        messages = normalize_messages(messages)

        try:
            async with self.client.messages.stream(
                **self._build_stream_kwargs(messages, tools)
            ) as stream:
                async for event in parse_stream(stream):
                    if abort_event is not None and abort_event.is_set():
                        yield StreamEvent(type="stop", content="aborted_streaming")
                        return
                    yield event

                    # Accumulate usage from stop events
                    if event.type == "usage" and isinstance(event.content, TokenUsage):
                        self._total_usage = self._total_usage + event.content
        except Exception as exc:
            yield StreamEvent(type="error", content=str(exc))

    async def query_with_tool_loop(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Callable[[str, dict], Awaitable[ToolExecutionResult]] | None = None,
        max_turns: int = 50,
        abort_event: asyncio.Event | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Full agentic loop with automatic tool execution.

        If tool_executor is provided, tool_use events are automatically handled:
        1. Stream API response, yielding all events
        2. When stop_reason is 'tool_use', collect all tool_use blocks
        3. Execute each via tool_executor(name, input) -> result string
        4. Append tool_result messages to conversation and continue the loop
        5. Repeat until end_turn, max_tokens, or max_turns reached

        Args:
            messages: Conversation history.
            tools: Tool definitions for the API.
            tool_executor: Async callable(tool_name, tool_input) -> result string.
            max_turns: Safety limit on agentic turns.
        """
        # Normalize into a working copy, but sync back to the original list
        # so callers see the updated conversation history.
        working = normalize_messages(messages)
        # Clear the original list and repopulate with normalized entries
        messages.clear()
        messages.extend(working)
        turn_count = 0
        start_time = time.monotonic()
        stop_reason = "end_turn"

        while turn_count < max_turns:
            if abort_event is not None and abort_event.is_set():
                stop_reason = "aborted"
                break

            turn_count += 1
            stop_reason = "end_turn"
            tool_use_blocks: list[ContentBlock] = []
            assistant_blocks: list[dict[str, Any]] = []

            async for event in self.query(messages, tools=tools, abort_event=abort_event):
                yield event

                if event.type == "tool_use" and isinstance(event.content, ContentBlock):
                    tool_use_blocks.append(event.content)
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": event.content.id,
                        "name": event.content.name,
                        "input": event.content.input or {},
                    })
                elif event.type == "text" and event.content:
                    assistant_blocks.append({
                        "type": "text",
                        "text": event.content,
                    })
                elif event.type == "thinking" and isinstance(event.content, str):
                    assistant_blocks.append({
                        "type": "thinking",
                        "thinking": event.content,
                    })
                elif event.type == "stop":
                    stop_reason = event.content

            # Append the assistant message with collected blocks
            if assistant_blocks:
                messages.append(build_assistant_message(assistant_blocks))

            if stop_reason == "aborted_streaming":
                break

            # If no tool calls or no executor, we're done
            if stop_reason != "tool_use" or not tool_use_blocks or tool_executor is None:
                break

            # Execute tools (with permission check)
            tool_results: list[ToolResult] = []
            for block in tool_use_blocks:
                if abort_event is not None and abort_event.is_set():
                    stop_reason = "aborted"
                    break

                tool_name = block.name or ""
                tool_input = block.input or {}

                # Permission check
                decision = await has_permissions_to_use_tool(
                    tool_name=tool_name,
                    input_data=tool_input,
                    context=self.permission_context,
                )
                if decision.behavior == "deny":
                    tool_results.append(
                        ToolResult(
                            tool_call_id=block.id or "",
                            output=decision.message,
                            is_error=True,
                            display_data=display_data_for_preview(
                                preview_for_tool_input(tool_name, tool_input),
                                tool_name=tool_name,
                                status="rejected",
                                dim=True,
                            ),
                        )
                    )
                    yield StreamEvent(
                        type="permission_denied",
                        content=decision.message,
                    )
                    continue
                if decision.behavior == "ask":
                    # Interactive approval needed
                    if self.permission_handler is None:
                        from open_claude.components.permissions import interactive_permission_check

                        final_decision = await interactive_permission_check(
                            tool_name=tool_name,
                            tool_input=tool_input,
                            permission_context=self.permission_context,
                            set_permission_context=lambda ctx: setattr(self, "permission_context", ctx),
                            tool_use_id=block.id or "",
                            decision=decision,
                        )
                    else:
                        final_decision = await self.permission_handler(
                            tool_name,
                            tool_input,
                            self.permission_context,
                            lambda ctx: setattr(self, "permission_context", ctx),
                            block.id or "",
                            decision,
                        )
                    if final_decision.behavior == "deny":
                        tool_results.append(
                            ToolResult(
                                tool_call_id=block.id or "",
                                output=getattr(final_decision, "message", "Permission denied"),
                                is_error=True,
                                display_data=getattr(final_decision, "display_data", None),
                            )
                        )
                        yield StreamEvent(
                            type="permission_denied",
                            content=getattr(final_decision, "message", "Permission denied"),
                        )
                        continue

                    # Approved — use potentially modified input
                    effective_input = getattr(final_decision, "updated_input", None) or tool_input
                else:
                    effective_input = tool_input

                try:
                    execution_result = await tool_executor(
                        tool_name,
                        effective_input,
                    )
                    tool_results.append(
                        ToolResult(
                            tool_call_id=block.id or "",
                            output=execution_result.output,
                            is_error=False,
                            display_data=execution_result.display_data,
                            new_messages=execution_result.new_messages,
                        )
                    )
                except Exception as exc:
                    tool_results.append(
                        ToolResult(
                            tool_call_id=block.id or "",
                            output=str(exc),
                            is_error=True,
                        )
                    )
                    yield StreamEvent(type="error", content=f"Tool {block.name} failed: {exc}")

            # Yield tool_result events and append to conversation
            for tr in tool_results:
                yield StreamEvent(type="tool_result", content=tr)

            if tool_results:
                messages.append(build_tool_result_message(tool_results))

                # Inject new_messages from tool results as additional user messages
                # (mirrors TS ToolResult.newMessages injection)
                for tr in tool_results:
                    if tr.new_messages:
                        messages.extend(tr.new_messages)

            if stop_reason == "aborted":
                break

            self._drain_mid_turn_commands(messages)

        # Yield final result summary
        duration_ms = (time.monotonic() - start_time) * 1000
        yield StreamEvent(
            type="result",
            content=QueryResult(
                stop_reason=stop_reason,
                usage=self._total_usage,
                duration_ms=duration_ms,
                total_turns=turn_count,
            ),
        )

    def _build_stream_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Build kwargs for the streaming API call."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self._format_system_prompt(),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        # Enable extended thinking when budget is set
        if self.thinking_budget and self.thinking_budget > 0:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget,
            }
            # max_tokens must cover thinking_budget + response tokens
            if kwargs["max_tokens"] <= self.thinking_budget:
                kwargs["max_tokens"] = self.thinking_budget + self.max_tokens
        return kwargs

    def _format_system_prompt(self) -> str | list[dict[str, str]]:
        """Format system prompt for the API.

        If system_prompt is a list of strings, convert to text block array.
        If it's a single string, pass as-is.
        """
        if isinstance(self.system_prompt, list):
            return [{"type": "text", "text": section} for section in self.system_prompt]
        return self.system_prompt

    def get_total_usage(self) -> TokenUsage:
        """Return accumulated token usage across all query calls."""
        return self._total_usage

    def _drain_mid_turn_commands(self, messages: list[dict[str, Any]]) -> None:
        """Inject task notifications before the next API turn.

        User prompts stay queued until the current turn fully completes so the UI
        can render them as independent turns with their own assistant blocks.
        """
        drain_pending_task_notifications()
        queued = get_commands_by_max_priority(
            "later",
            filter_fn=lambda cmd: cmd.agent_id is None,
        )
        consumed = [
            cmd for cmd in queued if cmd.mode == "task-notification"
        ]
        if not consumed:
            return
        for cmd in consumed:
            messages.append(build_user_message(cmd.value))
        remove_commands(consumed)
