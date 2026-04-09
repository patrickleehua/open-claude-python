"""Claude API skill - build apps with the Claude API or Anthropic SDK.

Port of Claude-Code-rev/src/skills/bundled/claudeApi.ts
"""

from __future__ import annotations

import os
import re

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition
from open_claude.skills.bundled.claude_api_content import (
    SKILL_FILES,
    SKILL_MODEL_VARS,
    SKILL_PROMPT,
)

DetectedLanguage = str  # python | typescript | java | go | ruby | csharp | php | curl

LANGUAGE_INDICATORS: dict[str, list[str]] = {
    "python": [".py", "requirements.txt", "pyproject.toml", "setup.py", "Pipfile"],
    "typescript": [".ts", ".tsx", "tsconfig.json", "package.json"],
    "java": [".java", "pom.xml", "build.gradle"],
    "go": [".go", "go.mod"],
    "ruby": [".rb", "Gemfile"],
    "csharp": [".cs", ".csproj"],
    "php": [".php", "composer.json"],
    "curl": [],
}


def _detect_language() -> DetectedLanguage | None:
    """Detect the project language by scanning CWD for indicator files."""
    try:
        entries = os.listdir(os.getcwd())
    except OSError:
        return None

    for lang, indicators in LANGUAGE_INDICATORS.items():
        if not indicators:
            continue
        for indicator in indicators:
            if indicator.startswith("."):
                if any(e.endswith(indicator) for e in entries):
                    return lang
            else:
                if indicator in entries:
                    return lang
    return None


def _get_files_for_language(lang: DetectedLanguage) -> list[str]:
    """Get relevant doc file paths for a detected language."""
    return [
        path
        for path in SKILL_FILES
        if path.startswith(f"{lang}/") or path.startswith("shared/")
    ]


def _process_content(md: str) -> str:
    """Strip HTML comments and substitute {{VAR}} placeholders."""
    # Strip HTML comments
    out = re.sub(r"<!--[\s\S]*?-->\n?", "", md)
    # Substitute model vars
    out = re.sub(
        r"\{\{(\w+)\}\}",
        lambda m: SKILL_MODEL_VARS.get(m.group(1), m.group(0)),
        out,
    )
    return out


def _build_inline_reference(file_paths: list[str]) -> str:
    """Build <doc> XML blocks from file contents."""
    sections = []
    for file_path in sorted(file_paths):
        md = SKILL_FILES.get(file_path)
        if not md:
            continue
        sections.append(
            f'<doc path="{file_path}">\n{_process_content(md).strip()}\n</doc>'
        )
    return "\n\n".join(sections)


def _build_prompt(lang: DetectedLanguage | None, args: str) -> str:
    """Build the full claude-api skill prompt."""
    clean_prompt = _process_content(SKILL_PROMPT)
    reading_guide_idx = clean_prompt.find("## Reading Guide")
    base_prompt = (
        clean_prompt[:reading_guide_idx].rstrip()
        if reading_guide_idx != -1
        else clean_prompt
    )

    parts: list[str] = [base_prompt]

    if lang:
        file_paths = _get_files_for_language(lang)
        parts.append(f"Detected language: **{lang}**")
        parts.append("---\n\n## Included Documentation\n\n" + _build_inline_reference(file_paths))
    else:
        parts.append("No project language was auto-detected. Ask the user which language they are using.")
        parts.append(
            "---\n\n## Included Documentation\n\n"
            + _build_inline_reference(list(SKILL_FILES.keys()))
        )

    if args:
        parts.append(f"## User Request\n\n{args}")

    return "\n\n".join(parts)


async def _get_prompt(args: str, context: object) -> list[dict]:
    lang = _detect_language()
    prompt = _build_prompt(lang, args)
    return [{"type": "text", "text": prompt}]


def register_claude_api_skill() -> None:
    register_bundled_skill(
        BundledSkillDefinition(
            name="claude-api",
            description=(
                "Build apps with the Claude API or Anthropic SDK.\n"
                "TRIGGER when: code imports `anthropic`/`@anthropic-ai/sdk`/`claude_agent_sdk`, "
                "or user asks to use Claude API, Anthropic SDKs, or Agent SDK.\n"
                "DO NOT TRIGGER when: code imports `openai`/other AI SDK, general programming, "
                "or ML/data-science tasks."
            ),
            allowed_tools=["Read", "Grep", "Glob", "WebFetch"],
            user_invocable=True,
            get_prompt_for_command=_get_prompt,
        )
    )
