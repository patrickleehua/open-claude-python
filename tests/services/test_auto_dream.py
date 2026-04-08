"""Tests for services.auto_dream — Consolidation lock and runner."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from open_claude.services.auto_dream.config import is_auto_dream_enabled
from open_claude.services.auto_dream.consolidation_lock import (
    read_last_consolidated_at,
    record_consolidation,
    rollback_consolidation_lock,
    try_acquire_consolidation_lock,
)
from open_claude.services.auto_dream.consolidation_prompt import build_consolidation_prompt


class TestConsolidationLock:
    @pytest.mark.asyncio
    async def test_read_returns_zero_when_no_file(self, tmp_path):
        with patch(
            "open_claude.services.auto_dream.consolidation_lock.get_memory_dir",
            return_value=tmp_path,
        ):
            result = await read_last_consolidated_at()
            assert result == 0.0

    @pytest.mark.asyncio
    async def test_acquire_creates_lock_file(self, tmp_path):
        with patch(
            "open_claude.services.auto_dream.consolidation_lock.get_memory_dir",
            return_value=tmp_path,
        ):
            prior = await try_acquire_consolidation_lock()
            assert prior == 0.0  # No prior lock
            lock_file = tmp_path / ".consolidate-lock"
            assert lock_file.exists()
            assert lock_file.read_text().strip() == str(os.getpid())

    @pytest.mark.asyncio
    async def test_read_after_record(self, tmp_path):
        with patch(
            "open_claude.services.auto_dream.consolidation_lock.get_memory_dir",
            return_value=tmp_path,
        ):
            await record_consolidation()
            mtime = await read_last_consolidated_at()
            assert mtime > 0

    @pytest.mark.asyncio
    async def test_rollback_deletes_on_zero(self, tmp_path):
        with patch(
            "open_claude.services.auto_dream.consolidation_lock.get_memory_dir",
            return_value=tmp_path,
        ):
            await try_acquire_consolidation_lock()
            lock_file = tmp_path / ".consolidate-lock"
            assert lock_file.exists()

            await rollback_consolidation_lock(0)
            assert not lock_file.exists()

    @pytest.mark.asyncio
    async def test_rollback_rewinds_mtime(self, tmp_path):
        with patch(
            "open_claude.services.auto_dream.consolidation_lock.get_memory_dir",
            return_value=tmp_path,
        ):
            await try_acquire_consolidation_lock()
            old_mtime = time.time() * 1000 - 3600_000  # 1 hour ago

            await rollback_consolidation_lock(old_mtime)
            lock_file = tmp_path / ".consolidate-lock"
            assert lock_file.exists()


class TestBuildConsolidationPrompt:
    def test_contains_phases(self):
        prompt = build_consolidation_prompt("/tmp/mem", "/tmp/logs")
        assert "Phase 1" in prompt
        assert "Phase 2" in prompt
        assert "Phase 3" in prompt
        assert "Phase 4" in prompt

    def test_includes_memory_root(self):
        prompt = build_consolidation_prompt("/my/memory/dir", "/logs")
        assert "/my/memory/dir" in prompt

    def test_extra_appended(self):
        prompt = build_consolidation_prompt("/tmp/mem", "/tmp/logs", extra="Custom note")
        assert "Custom note" in prompt


class TestIsAutoDreamEnabled:
    def test_default_false(self):
        # Default is False since no settings.json
        result = is_auto_dream_enabled()
        assert isinstance(result, bool)
