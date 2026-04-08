"""Background memory extraction from conversations.

Ported from Claude-Code-rev/src/services/extractMemories/extractMemories.ts.

Extracts durable memories from the current session transcript and writes
them to the auto-memory directory. Runs once at the end of each complete
query loop (when the model produces a final response with no tool calls).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from open_claude.services.extract_memories.prompts import build_extract_auto_only_prompt
from open_claude.utils.memory.memdir import ENTRYPOINT_NAME
from open_claude.utils.memory.paths import get_memory_dir, is_auto_mem_enabled, is_auto_mem_path
from open_claude.utils.memory.scanner import format_memory_manifest, scan_memory_files

logger = logging.getLogger(__name__)


def _is_model_visible_message(message: dict) -> bool:
    return message.get("role") in ("user", "assistant")


def _count_model_visible_messages_since(messages: list[dict], since_uuid: str | None) -> int:
    if since_uuid is None:
        return sum(1 for m in messages if _is_model_visible_message(m))

    found = False
    count = 0
    for m in messages:
        if not found:
            if m.get("uuid") == since_uuid:
                found = True
            continue
        if _is_model_visible_message(m):
            count += 1

    if not found:
        return sum(1 for m in messages if _is_model_visible_message(m))
    return count


def _has_memory_writes_since(messages: list[dict], since_uuid: str | None) -> bool:
    """Check if any assistant message after the cursor wrote to a memory path."""
    found = since_uuid is None
    for m in messages:
        if not found:
            if m.get("uuid") == since_uuid:
                found = True
            continue
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            fp = _get_written_file_path(block)
            if fp and is_auto_mem_path(fp):
                return True
    return False


def _get_written_file_path(block: dict) -> str | None:
    if block.get("type") != "tool_use":
        return None
    name = block.get("name", "")
    if name not in ("Edit", "Write"):
        return None
    inp = block.get("input")
    if isinstance(inp, dict) and "file_path" in inp:
        fp = inp["file_path"]
        return fp if isinstance(fp, str) else None
    return None


def _extract_written_paths(agent_messages: list[dict]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for m in agent_messages:
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            fp = _get_written_file_path(block)
            if fp and fp not in seen:
                paths.append(fp)
                seen.add(fp)
    return paths


class MemoryExtractor:
    """Stateful memory extractor with closure-scoped mutable state."""

    def __init__(self) -> None:
        self._in_flight: set[asyncio.Task] = set()
        self._last_memory_uuid: str | None = None
        self._in_progress: bool = False
        self._turns_since_last: int = 0
        self._pending_context: dict | None = None
        self._llm_call_fn = None

    def set_llm_call_fn(self, fn) -> None:
        self._llm_call_fn = fn

    async def execute(self, messages: list[dict]) -> None:
        """Run memory extraction at the end of a query loop."""
        if self._llm_call_fn is None:
            return

        if not is_auto_mem_enabled():
            return

        memory_dir = get_memory_dir()
        new_count = _count_model_visible_messages_since(messages, self._last_memory_uuid)

        # Skip if main agent already wrote memories
        if _has_memory_writes_since(messages, self._last_memory_uuid):
            logger.debug("[extractMemories] skipping — conversation already wrote to memory files")
            last = messages[-1] if messages else None
            if last and last.get("uuid"):
                self._last_memory_uuid = last["uuid"]
            return

        self._turns_since_last += 1
        if self._turns_since_last < 1:
            return
        self._turns_since_last = 0

        if self._in_progress:
            logger.debug("[extractMemories] extraction in progress — stashing")
            self._pending_context = {"messages": messages}
            return

        await self._run_extraction(messages, memory_dir, new_count)

    async def _run_extraction(
        self, messages: list[dict], memory_dir: Path, new_count: int,
    ) -> None:
        self._in_progress = True
        start_time = time.time()

        try:
            logger.debug(
                "[extractMemories] starting — %d new messages, dir=%s",
                new_count, memory_dir,
            )

            # Pre-inject memory manifest
            existing = format_memory_manifest(
                await scan_memory_files(memory_dir),
            )

            user_prompt = build_extract_auto_only_prompt(new_count, existing)

            result = await self._llm_call_fn(
                system="You are a memory extraction subagent.",
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Advance cursor
            last = messages[-1] if messages else None
            if last and last.get("uuid"):
                self._last_memory_uuid = last["uuid"]

            logger.debug(
                "[extractMemories] finished in %dms",
                (time.time() - start_time) * 1000,
            )

        except Exception as e:
            logger.debug("[extractMemories] error: %s", e)
        finally:
            self._in_progress = False

            # Run trailing extraction if stashed
            trailing = self._pending_context
            self._pending_context = None
            if trailing:
                await self._run_extraction(
                    trailing["messages"],
                    memory_dir,
                    _count_model_visible_messages_since(
                        trailing["messages"], self._last_memory_uuid,
                    ),
                )

    async def drain(self, timeout_ms: int = 60_000) -> None:
        """Await all in-flight extractions with a soft timeout."""
        if not self._in_flight:
            return
        done, _ = await asyncio.wait(
            self._in_flight,
            timeout=timeout_ms / 1000,
        )
        self._in_flight -= done


# Module-level singleton (set up by init_extract_memories)
_extractor: MemoryExtractor | None = None


def init_extract_memories(llm_call_fn=None) -> None:
    """Initialize the memory extraction system.

    Call once at startup. Creates a fresh extractor with all mutable state.
    """
    global _extractor
    _extractor = MemoryExtractor()
    if llm_call_fn:
        _extractor.set_llm_call_fn(llm_call_fn)


async def execute_extract_memories(messages: list[dict]) -> None:
    """Run memory extraction at the end of a query loop.

    No-op until init_extract_memories() has been called.
    """
    if _extractor:
        await _extractor.execute(messages)


async def drain_pending_extraction(timeout_ms: int = 60_000) -> None:
    """Await all in-flight extractions."""
    if _extractor:
        await _extractor.drain(timeout_ms)
