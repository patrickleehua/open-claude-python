"""YAML frontmatter parser for memory .md files.

Ported from Claude-Code-rev/src/utils/frontmatterParser.ts.
"""

from __future__ import annotations

import re

import yaml

FRONTMATTER_RE = re.compile(r"^---\s*\n([\s\S]*?)---\s*\n?")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_content).
    If no frontmatter is found, returns ({}, original_text).
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    frontmatter_text = match.group(1) or ""
    body = text[match.end():]

    try:
        parsed = yaml.safe_load(frontmatter_text)
        if isinstance(parsed, dict):
            return parsed, body
    except yaml.YAMLError:
        pass

    return {}, text
