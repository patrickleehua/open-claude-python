"""Schedule Remote Agents skill - create and manage scheduled remote agents.

Port of Claude-Code-rev/src/skills/bundled/scheduleRemoteAgents.ts

Deferred: registered but disabled until remote agent infrastructure is implemented.
"""

from __future__ import annotations

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition

REMOTE_TRIGGER_TOOL_NAME = "RemoteTrigger"
ASK_USER_QUESTION_TOOL_NAME = "AskUserQuestion"


async def _get_prompt(args: str, context: object) -> list[dict]:
    prompt = """# /schedule — manage scheduled remote agents

Create, update, list, or run scheduled remote agents (triggers).

## Capabilities

- Create new triggers with cron schedules
- List existing triggers
- Update trigger configurations
- Delete triggers
- Run triggers on demand

## Cron Expression Handling

Standard 5-field cron: minute hour day-of-month month day-of-week.
Supports timezone conversion.

Note: This skill requires remote agent infrastructure to be available.
"""
    if args:
        prompt += f"\n## User Request\n\n{args}"
    return [{"type": "text", "text": prompt}]


def register_schedule_remote_agents_skill() -> None:
    register_bundled_skill(
        BundledSkillDefinition(
            name="schedule",
            description="Create, update, list, or run scheduled remote agents (triggers).",
            when_to_use=(
                "When the user wants to schedule recurring Claude Code sessions, "
                "manage remote agent triggers, or set up cron-based automation."
            ),
            argument_hint="[action] [options]",
            user_invocable=True,
            allowed_tools=[REMOTE_TRIGGER_TOOL_NAME, ASK_USER_QUESTION_TOOL_NAME],
            is_enabled=lambda: False,  # Disabled until remote infra is available
            get_prompt_for_command=_get_prompt,
        )
    )
