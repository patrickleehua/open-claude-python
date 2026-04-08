"""Tests for utils.memory.frontmatter — YAML frontmatter parsing."""

from __future__ import annotations

import pytest

from open_claude.utils.memory.frontmatter import parse_frontmatter


class TestParseFrontmatter:
    def test_basic_frontmatter(self):
        text = "---\nname: test\n---\nBody content here"
        fm, body = parse_frontmatter(text)
        assert fm == {"name": "test"}
        assert body.strip() == "Body content here"

    def test_multiple_fields(self):
        text = "---\nname: test\ndescription: a test memory\ntype: user\n---\nContent"
        fm, body = parse_frontmatter(text)
        assert fm["name"] == "test"
        assert fm["description"] == "a test memory"
        assert fm["type"] == "user"
        assert body.strip() == "Content"

    def test_no_frontmatter(self):
        text = "Just some plain text\nNo frontmatter here"
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_empty_frontmatter(self):
        text = "---\n---\nBody"
        fm, body = parse_frontmatter(text)
        # Empty YAML frontmatter may parse as None or {}
        assert fm == {} or fm is None or fm == ""
        assert "Body" in body

    def test_invalid_yaml_returns_empty(self):
        text = "---\n: invalid: yaml: [broken\n---\nBody"
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == text  # Falls back to original text on parse error

    def test_frontmatter_with_multiline_body(self):
        body_text = "Line 1\nLine 2\nLine 3"
        text = f"---\nname: my_memory\n---\n{body_text}"
        fm, body = parse_frontmatter(text)
        assert fm["name"] == "my_memory"
        assert body == body_text

    def test_whitespace_after_delimiters(self):
        text = "---  \nname: test\n---  \nBody"
        fm, body = parse_frontmatter(text)
        assert fm == {"name": "test"}
        assert body.strip() == "Body"
