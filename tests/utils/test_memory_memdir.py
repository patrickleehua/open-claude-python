"""Tests for utils.memory.memdir — Core memory prompt building."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from open_claude.utils.memory.memdir import (
    DIR_EXISTS_GUIDANCE,
    ENTRYPOINT_NAME,
    MAX_ENTRYPOINT_BYTES,
    MAX_ENTRYPOINT_LINES,
    EntrypointTruncation,
    build_memory_lines,
    build_memory_prompt,
    ensure_memory_dir_exists,
    load_memory_prompt,
    truncate_entrypoint_content,
)


class TestTruncateEntrypointContent:
    def test_small_content_unchanged(self):
        result = truncate_entrypoint_content("Hello\nWorld")
        assert result.was_line_truncated is False
        assert result.was_byte_truncated is False
        assert result.content == "Hello\nWorld"
        assert result.line_count == 2

    def test_line_truncation(self):
        lines = [f"Line {i}" for i in range(MAX_ENTRYPOINT_LINES + 50)]
        text = "\n".join(lines)
        result = truncate_entrypoint_content(text)
        assert result.was_line_truncated is True
        assert "WARNING" in result.content
        assert str(MAX_ENTRYPOINT_LINES) in result.content

    def test_byte_truncation(self):
        # Create content that exceeds byte limit but stays within line limit
        long_line = "A" * (MAX_ENTRYPOINT_BYTES + 1000)
        result = truncate_entrypoint_content(long_line)
        assert result.was_byte_truncated is True
        assert "WARNING" in result.content

    def test_both_truncated(self):
        lines = ["A" * 200 for _ in range(MAX_ENTRYPOINT_LINES + 10)]
        text = "\n".join(lines)
        result = truncate_entrypoint_content(text)
        assert result.was_line_truncated is True
        # May or may not be byte-truncated depending on exact sizes
        assert "WARNING" in result.content

    def test_empty_string(self):
        result = truncate_entrypoint_content("")
        assert result.line_count == 1  # empty string splits to [""]
        assert result.was_line_truncated is False


class TestEnsureMemoryDirExists:
    @pytest.mark.asyncio
    async def test_creates_dir(self, tmp_path):
        target = tmp_path / "new" / "memory"
        assert not target.exists()
        await ensure_memory_dir_exists(target)
        assert target.is_dir()

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_path):
        target = tmp_path / "mem"
        target.mkdir()
        await ensure_memory_dir_exists(target)  # should not raise
        assert target.is_dir()


class TestBuildMemoryLines:
    def test_includes_type_section(self):
        lines = build_memory_lines("auto memory", "/tmp/mem")
        text = "\n".join(lines)
        assert "## Types of memory" in text

    def test_includes_what_not_to_save(self):
        lines = build_memory_lines("auto memory", "/tmp/mem")
        text = "\n".join(lines)
        assert "## What NOT to save in memory" in text

    def test_includes_when_to_access(self):
        lines = build_memory_lines("auto memory", "/tmp/mem")
        text = "\n".join(lines)
        assert "## When to access memories" in text

    def test_skip_index_mode(self):
        lines = build_memory_lines("auto memory", "/tmp/mem", skip_index=True)
        text = "\n".join(lines)
        assert "Step 1" not in text
        assert "Step 2" not in text

    def test_with_index_mode(self):
        lines = build_memory_lines("auto memory", "/tmp/mem", skip_index=False)
        text = "\n".join(lines)
        assert "Step 1" in text
        assert "Step 2" in text

    def test_extra_guidelines(self):
        lines = build_memory_lines(
            "auto memory", "/tmp/mem", extra_guidelines=["Custom guideline here"]
        )
        text = "\n".join(lines)
        assert "Custom guideline here" in text

    def test_display_name_in_header(self):
        lines = build_memory_lines("auto memory", "/tmp/mem")
        assert lines[0] == "# auto memory"


class TestBuildMemoryPrompt:
    def test_with_existing_memory_md(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "MEMORY.md").write_text("- [Test](test.md) — test entry", encoding="utf-8")

        prompt = build_memory_prompt("auto memory", str(mem_dir))
        assert "## MEMORY.md" in prompt
        assert "test entry" in prompt

    def test_with_empty_memory_md(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()

        prompt = build_memory_prompt("auto memory", str(mem_dir))
        assert "## MEMORY.md" in prompt
        assert "currently empty" in prompt


class TestLoadMemoryPrompt:
    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self):
        with patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "true"}):
            result = await load_memory_prompt(cwd="/test")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_prompt_when_enabled(self, tmp_path):
        with patch.dict(os.environ, {}, clear=False):
            result = await load_memory_prompt(cwd=str(tmp_path))
            assert result is not None
            assert "# auto memory" in result

    @pytest.mark.asyncio
    async def test_creates_memory_dir(self, tmp_path):
        with patch.dict(os.environ, {}, clear=False):
            await load_memory_prompt(cwd=str(tmp_path))
            # Memory dir should have been created
            from open_claude.utils.memory.paths import get_memory_dir
            mem_dir = get_memory_dir(str(tmp_path))
            assert mem_dir.exists()
