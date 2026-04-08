"""Tests for utils.memory.paths — Memory directory path resolution."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from open_claude.utils.memory.paths import (
    _sanitize_path,
    get_memory_base_dir,
    get_memory_dir,
    get_memory_entrypoint,
    is_auto_mem_path,
    is_auto_memory_enabled,
)


class TestSanitizePath:
    def test_forward_slashes(self):
        assert _sanitize_path("a/b/c") == "a_b_c"

    def test_backslashes(self):
        assert _sanitize_path("a\\b\\c") == "a_b_c"

    def test_mixed_separators(self):
        assert _sanitize_path("a/b\\c/d") == "a_b_c_d"

    def test_leading_trailing_separators(self):
        assert _sanitize_path("/a/b/") == "a_b"

    def test_collapsed_underscores(self):
        assert _sanitize_path("a//b///c") == "a_b_c"

    def test_empty_returns_default(self):
        assert _sanitize_path("") == "default"
        assert _sanitize_path("///") == "default"


class TestGetMemoryBaseDir:
    def test_default_is_home_claude(self):
        with patch.dict(os.environ, {}, clear=False):
            # Only clear the remote override, keep other env
            os.environ.pop("CLAUDE_CODE_REMOTE_MEMORY_DIR", None)
            result = get_memory_base_dir()
            assert result == Path.home() / ".claude"

    def test_env_override(self):
        with patch.dict(os.environ, {"CLAUDE_CODE_REMOTE_MEMORY_DIR": "/tmp/mem"}):
            result = get_memory_base_dir()
            assert result == Path("/tmp/mem")


class TestGetMemoryDir:
    def test_structure_under_projects(self):
        # Use a unique path to avoid lru_cache hits
        import uuid
        unique = f"/home/user/test_{uuid.uuid4().hex[:8]}"
        result = get_memory_dir(unique)
        assert "projects" in str(result)
        assert str(result).endswith("memory")

    def test_caches_result(self):
        # lru_cache on the function
        r1 = get_memory_dir("/test/cache/path")
        r2 = get_memory_dir("/test/cache/path")
        assert r1 == r2


class TestGetMemoryEntrypoint:
    def test_ends_with_memory_md(self):
        result = get_memory_entrypoint("/some/path")
        assert result.name == "MEMORY.md"


class TestIsAutoMemPath:
    def test_inside_memory_dir(self):
        mem_dir = get_memory_dir("/test/project")
        result = is_auto_mem_path(str(mem_dir / "some_file.md"), cwd="/test/project")
        assert result is True

    def test_outside_memory_dir(self):
        result = is_auto_mem_path("/tmp/random_file.md", cwd="/test/project")
        assert result is False


class TestIsAutoMemoryEnabled:
    def test_default_enabled(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_auto_memory_enabled() is True

    @pytest.mark.parametrize("val", ["1", "true", "True", "TRUE", "yes"])
    def test_disabled_by_env(self, val):
        with patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": val}):
            assert is_auto_memory_enabled() is False

    def test_enabled_when_env_is_random(self):
        with patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "no"}):
            assert is_auto_memory_enabled() is True
