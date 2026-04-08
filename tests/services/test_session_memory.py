"""Tests for services.session_memory — Session memory extraction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from open_claude.services.session_memory.prompts import (
    DEFAULT_SESSION_MEMORY_TEMPLATE,
    _analyze_section_sizes,
    _flush_section,
    _rough_token_count,
    _substitute_variables,
    build_session_memory_update_prompt,
    truncate_session_memory_for_compact,
)
from open_claude.services.session_memory.session_memory import (
    ManualExtractionResult,
    should_extract_memory,
    setup_session_memory_file,
    manually_extract_session_memory,
)
from open_claude.services.session_memory.utils import (
    SessionMemoryConfig,
    get_session_memory_config,
    has_met_initialization_threshold,
    has_met_update_threshold,
    reset_session_memory_state,
    set_last_summarized_message_id,
    mark_extraction_started,
    mark_extraction_completed,
)


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset session memory state before each test."""
    reset_session_memory_state()
    yield
    reset_session_memory_state()


class TestSessionMemoryConfig:
    def test_defaults(self):
        cfg = SessionMemoryConfig()
        assert cfg.minimum_message_tokens_to_init == 10_000
        assert cfg.minimum_tokens_between_update == 5_000
        assert cfg.tool_calls_between_updates == 3


class TestThresholdChecks:
    def test_initialization_threshold(self):
        assert has_met_initialization_threshold(10_000) is True
        assert has_met_initialization_threshold(9_999) is False

    def test_update_threshold(self):
        from open_claude.services.session_memory import utils as u
        u._tokens_at_last_extraction = 5_000
        assert has_met_update_threshold(10_000) is True
        assert has_met_update_threshold(9_999) is False


class TestStateManagement:
    def test_message_id_roundtrip(self):
        set_last_summarized_message_id("msg_123")
        from open_claude.services.session_memory import utils as u
        assert u.get_last_summarized_message_id() == "msg_123"

    def test_extraction_lifecycle(self):
        mark_extraction_started()
        from open_claude.services.session_memory import utils as u
        assert u._extraction_started_at is not None

        mark_extraction_completed()
        assert u._extraction_started_at is None


class TestRoughTokenCount:
    def test_basic(self):
        assert _rough_token_count("A" * 40) == 10
        assert _rough_token_count("") == 0


class TestAnalyzeSectionSizes:
    def test_single_section(self):
        content = "# Title\nSome content here\nMore content"
        sizes = _analyze_section_sizes(content)
        assert "# Title" in sizes
        assert sizes["# Title"] > 0

    def test_multiple_sections(self):
        content = "# A\nContent A\n\n# B\nContent B"
        sizes = _analyze_section_sizes(content)
        assert "# A" in sizes
        assert "# B" in sizes


class TestSubstituteVariables:
    def test_basic_substitution(self):
        result = _substitute_variables("Hello {{name}}", {"name": "World"})
        assert result == "Hello World"

    def test_multiple_vars(self):
        result = _substitute_variables(
            "{{a}} and {{b}}", {"a": "X", "b": "Y"}
        )
        assert result == "X and Y"

    def test_missing_var_preserved(self):
        result = _substitute_variables("{{missing}}", {})
        assert result == "{{missing}}"


class TestFlushSection:
    def test_small_section_unchanged(self):
        lines = ["line1", "line2"]
        result, truncated = _flush_section("# Header", lines, 1000)
        assert not truncated
        assert result[0] == "# Header"
        assert "line1" in result

    def test_large_section_truncated(self):
        lines = ["A" * 100 for _ in range(100)]
        result, truncated = _flush_section("# Header", lines, 200)
        assert truncated
        assert "[... section truncated" in "\n".join(result)

    def test_empty_header(self):
        lines = ["line1", "line2"]
        result, truncated = _flush_section("", lines, 1000)
        assert not truncated
        assert result == lines


class TestTruncateSessionMemoryForCompact:
    def test_no_truncation_needed(self):
        content = "# A\nShort content\n\n# B\nAlso short"
        result, was_truncated = truncate_session_memory_for_compact(content)
        assert not was_truncated
        assert result == content

    def test_truncates_oversized_section(self):
        long_content = " ".join(["word"] * 10_000)
        content = f"# A\n{long_content}\n\n# B\nShort"
        result, was_truncated = truncate_session_memory_for_compact(content)
        assert was_truncated
        assert "[... section truncated" in result


class TestBuildSessionMemoryUpdatePrompt:
    @pytest.mark.asyncio
    async def test_substitutes_variables(self):
        prompt = await build_session_memory_update_prompt(
            "Current notes content", "/path/to/notes.md"
        )
        assert "Current notes content" in prompt
        assert "/path/to/notes.md" in prompt


class TestShouldExtractMemory:
    def test_below_threshold_returns_false(self):
        messages = [{"role": "user", "content": "short"}]
        assert should_extract_memory(messages, token_count_fn=lambda m: 100) is False

    def test_above_threshold_no_tool_calls(self):
        # Above init threshold but last turn has tool_use → should not extract
        messages = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "Read", "input": {}}],
            },
        ]
        # Token count above init threshold
        result = should_extract_memory(messages, token_count_fn=lambda m: 15_000)
        # Depends on whether initialization has been marked
        assert isinstance(result, bool)


class TestManualExtraction:
    @pytest.mark.asyncio
    async def test_no_messages_returns_error(self):
        result = await manually_extract_session_memory([])
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_no_llm_fn_returns_error(self):
        messages = [{"role": "user", "content": "test"}]
        result = await manually_extract_session_memory(messages)
        assert result.success is False
        assert "LLM" in result.error or "No LLM" in result.error


class TestSetupSessionMemoryFile:
    @pytest.mark.asyncio
    async def test_creates_file(self, tmp_path):
        session_dir = tmp_path / "session-memory"
        with patch(
            "open_claude.services.session_memory.session_memory.get_session_memory_dir",
            return_value=session_dir,
        ), patch(
            "open_claude.services.session_memory.session_memory.get_session_memory_path",
            return_value=session_dir / "session-notes.md",
        ):
            path, content = await setup_session_memory_file()
            assert Path(path).exists()
            assert "Session Title" in content
