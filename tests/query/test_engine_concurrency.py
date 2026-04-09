from __future__ import annotations

import asyncio

from open_claude.query.engine import QueryEngine
from open_claude.query.types import ContentBlock, QueryResult, StreamEvent
from open_claude.schemas import ToolExecutionResult
from open_claude.utils.message_queue_manager import QueuedCommand, clear, enqueue, peek


def setup_function() -> None:
    clear()


def teardown_function() -> None:
    clear()


async def test_query_engine_drains_mid_turn_commands(monkeypatch) -> None:
    engine = QueryEngine(client=object())  # type: ignore[arg-type]
    observed_messages: list[list[dict]] = []

    async def fake_query(self, messages, tools=None, abort_event=None):
        observed_messages.append([dict(msg) for msg in messages])
        assistant_count = sum(1 for msg in messages if msg.get("role") == "assistant")
        if assistant_count == 0:
            yield StreamEvent(
                type="tool_use",
                content=ContentBlock(type="tool_use", id="tool-1", name="Read", input={}),
            )
            yield StreamEvent(type="stop", content="tool_use")
            return

        assert any(
            msg.get("role") == "user" and msg.get("content") == "queued prompt"
            for msg in messages
        )
        yield StreamEvent(type="text", content="done")
        yield StreamEvent(type="stop", content="end_turn")

    monkeypatch.setattr(QueryEngine, "query", fake_query)

    enqueue(QueuedCommand(value="queued prompt", mode="prompt", priority="next"))

    events = [
        event
        async for event in engine.query_with_tool_loop(
            messages=[{"role": "user", "content": "first prompt"}],
            tool_executor=lambda _name, _input: asyncio.sleep(
                0,
                result=ToolExecutionResult(output="ok"),
            ),
        )
    ]

    assert len(observed_messages) == 2
    assert peek() is None
    assert any(event.type == "tool_result" for event in events)
    assert isinstance(events[-1].content, QueryResult)
    assert events[-1].content.stop_reason == "end_turn"


async def test_query_engine_stops_after_abort(monkeypatch) -> None:
    engine = QueryEngine(client=object())  # type: ignore[arg-type]
    abort_event = asyncio.Event()
    query_calls = 0

    async def fake_query(self, messages, tools=None, abort_event=None):
        nonlocal query_calls
        query_calls += 1
        yield StreamEvent(
            type="tool_use",
            content=ContentBlock(type="tool_use", id="tool-1", name="Read", input={}),
        )
        yield StreamEvent(type="stop", content="tool_use")

    async def tool_executor(_name: str, _input: dict) -> ToolExecutionResult:
        abort_event.set()
        return ToolExecutionResult(output="ok")

    monkeypatch.setattr(QueryEngine, "query", fake_query)

    events = [
        event
        async for event in engine.query_with_tool_loop(
            messages=[{"role": "user", "content": "first prompt"}],
            tool_executor=tool_executor,
            abort_event=abort_event,
        )
    ]

    assert query_calls == 1
    assert isinstance(events[-1].content, QueryResult)
    assert events[-1].content.stop_reason == "aborted"
