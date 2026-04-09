"""Claude in Chrome skill - Chrome browser automation.

Port of Claude-Code-rev/src/skills/bundled/claudeInChrome.ts

Deferred: registered but disabled until MCP browser tools are available.
"""

from __future__ import annotations

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition

SKILL_ACTIVATION_MESSAGE = """
Now that this skill is invoked, you have access to Chrome browser automation tools.

IMPORTANT: Start by getting information about the user's current browser tabs.
"""


async def _get_prompt(args: str, context: object) -> list[dict]:
    prompt = f"# Claude in Chrome\n\n{SKILL_ACTIVATION_MESSAGE}"
    if args:
        prompt += f"\n## Task\n\n{args}"
    return [{"type": "text", "text": prompt}]


def register_claude_in_chrome_skill() -> None:
    register_bundled_skill(
        BundledSkillDefinition(
            name="claude-in-chrome",
            description=(
                "Automates your Chrome browser to interact with web pages - clicking elements, "
                "filling forms, capturing screenshots, reading console logs, and navigating sites."
            ),
            when_to_use=(
                "When the user wants to interact with web pages, automate browser tasks, "
                "capture screenshots, read console logs, or perform any browser-based actions."
            ),
            allowed_tools=["mcp__claude-in-chrome__*"],
            user_invocable=True,
            is_enabled=lambda: False,  # Disabled until MCP browser tools are available
            get_prompt_for_command=_get_prompt,
        )
    )
