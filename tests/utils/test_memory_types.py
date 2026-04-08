"""Tests for utils.memory.types — MemoryType enum and parsing."""

from __future__ import annotations

import pytest

from open_claude.utils.memory.types import (
    TYPES_SECTION,
    WHAT_NOT_TO_SAVE_SECTION,
    WHEN_TO_ACCESS_SECTION,
    TRUSTING_RECALL_SECTION,
    MEMORY_FRONTMATTER_EXAMPLE,
    MemoryType,
    parse_memory_type,
)


class TestMemoryType:
    def test_values(self):
        assert MemoryType.USER == "user"
        assert MemoryType.FEEDBACK == "feedback"
        assert MemoryType.PROJECT == "project"
        assert MemoryType.REFERENCE == "reference"

    def test_is_str_enum(self):
        for mt in MemoryType:
            assert isinstance(mt, str)

    def test_iteration(self):
        assert set(MemoryType) == {"user", "feedback", "project", "reference"}


class TestParseMemoryType:
    @pytest.mark.parametrize("raw", ["user", "feedback", "project", "reference"])
    def test_valid_types(self, raw):
        assert parse_memory_type(raw) == MemoryType(raw)

    def test_none_returns_none(self):
        assert parse_memory_type(None) is None

    def test_invalid_returns_none(self):
        assert parse_memory_type("unknown") is None

    def test_empty_string_returns_none(self):
        assert parse_memory_type("") is None


class TestPromptConstants:
    def test_types_section_is_list(self):
        assert isinstance(TYPES_SECTION, list)
        assert len(TYPES_SECTION) > 10
        assert TYPES_SECTION[0] == "## Types of memory"

    def test_what_not_to_save_section(self):
        assert isinstance(WHAT_NOT_TO_SAVE_SECTION, list)
        assert WHAT_NOT_TO_SAVE_SECTION[0] == "## What NOT to save in memory"

    def test_when_to_access_section(self):
        assert isinstance(WHEN_TO_ACCESS_SECTION, list)
        assert WHEN_TO_ACCESS_SECTION[0] == "## When to access memories"

    def test_trusting_recall_section(self):
        assert isinstance(TRUSTING_RECALL_SECTION, list)
        assert len(TRUSTING_RECALL_SECTION) > 3

    def test_frontmatter_example_has_yaml_delimiters(self):
        assert "---" in MEMORY_FRONTMATTER_EXAMPLE
