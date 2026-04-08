"""Tests for utils.memory.scanner — Memory file scanning."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from open_claude.utils.memory.scanner import (
    MemoryHeader,
    format_memory_manifest,
    scan_memory_files,
)


@pytest.fixture
def memory_dir(tmp_path):
    """Create a temporary memory directory with sample files."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()

    # Create MEMORY.md (should be skipped)
    (mem_dir / "MEMORY.md").write_text("# Index\n- [test](test.md)", encoding="utf-8")

    # Create a user memory
    user_mem = mem_dir / "user_role.md"
    user_mem.write_text(
        "---\nname: user_role\ndescription: User is a backend dev\ntype: user\n---\nContent here",
        encoding="utf-8",
    )

    # Create a feedback memory
    fb_mem = mem_dir / "feedback_testing.md"
    fb_mem.write_text(
        "---\nname: testing_feedback\ndescription: Always test stuff\ntype: feedback\n---\nFeedback body",
        encoding="utf-8",
    )

    # Create a file without frontmatter
    plain_mem = mem_dir / "notes.md"
    plain_mem.write_text("Just some plain notes", encoding="utf-8")

    return mem_dir


class TestScanMemoryFiles:
    @pytest.mark.asyncio
    async def test_skips_memory_md(self, memory_dir):
        headers = await scan_memory_files(memory_dir)
        filenames = [h.filename for h in headers]
        assert "MEMORY.md" not in filenames

    @pytest.mark.asyncio
    async def test_finds_md_files(self, memory_dir):
        headers = await scan_memory_files(memory_dir)
        filenames = [h.filename for h in headers]
        assert "user_role.md" in filenames
        assert "feedback_testing.md" in filenames
        assert "notes.md" in filenames

    @pytest.mark.asyncio
    async def test_parses_frontmatter(self, memory_dir):
        headers = await scan_memory_files(memory_dir)
        by_name = {h.filename: h for h in headers}

        user = by_name["user_role.md"]
        assert user.description == "User is a backend dev"
        assert user.type is not None
        assert user.type.value == "user"

        fb = by_name["feedback_testing.md"]
        assert fb.description == "Always test stuff"
        assert fb.type is not None
        assert fb.type.value == "feedback"

    @pytest.mark.asyncio
    async def test_plain_file_has_no_type(self, memory_dir):
        headers = await scan_memory_files(memory_dir)
        by_name = {h.filename: h for h in headers}
        plain = by_name["notes.md"]
        assert plain.type is None
        assert plain.description is None

    @pytest.mark.asyncio
    async def test_has_mtime(self, memory_dir):
        headers = await scan_memory_files(memory_dir)
        for h in headers:
            assert h.mtime_ms > 0

    @pytest.mark.asyncio
    async def test_sorted_newest_first(self, memory_dir):
        # Make all files old, then touch only one to make it newest
        old_time = time.time() - 3600
        for f in memory_dir.iterdir():
            if f.is_file() and f.suffix == ".md" and f.name != "MEMORY.md":
                os.utime(f, (old_time, old_time))

        # Touch feedback_testing.md to be newest
        time.sleep(0.05)  # Ensure mtime difference
        (memory_dir / "feedback_testing.md").touch()

        headers = await scan_memory_files(memory_dir)
        assert headers[0].filename == "feedback_testing.md"

    @pytest.mark.asyncio
    async def test_nonexistent_dir_returns_empty(self, tmp_path):
        headers = await scan_memory_files(tmp_path / "nope")
        assert headers == []

    @pytest.mark.asyncio
    async def test_subdirectory_files(self, memory_dir):
        sub = memory_dir / "subdir"
        sub.mkdir()
        (sub / "deep.md").write_text(
            "---\nname: deep\ndescription: Nested memory\ntype: project\n---\nDeep",
            encoding="utf-8",
        )
        headers = await scan_memory_files(memory_dir)
        filenames = [h.filename for h in headers]
        # Path separators normalized to forward slashes
        assert any("deep.md" in f for f in filenames)


class TestFormatMemoryManifest:
    def test_format(self):
        now_ms = time.time() * 1000
        headers = [
            MemoryHeader(
                filename="test.md",
                file_path="/tmp/test.md",
                mtime_ms=now_ms,
                description="A test memory",
                type="user",
            ),
        ]
        manifest = format_memory_manifest(headers)
        assert "[user] test.md" in manifest
        assert "A test memory" in manifest

    def test_no_description(self):
        now_ms = time.time() * 1000
        headers = [
            MemoryHeader(
                filename="test.md",
                file_path="/tmp/test.md",
                mtime_ms=now_ms,
                description=None,
                type=None,
            ),
        ]
        manifest = format_memory_manifest(headers)
        assert "test.md" in manifest
        # No [type] prefix when type is None
        assert "[" not in manifest
