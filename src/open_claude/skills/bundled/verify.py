"""Verify skill - verify a code change does what it should.

Port of Claude-Code-rev/src/skills/bundled/verify.ts
"""

from __future__ import annotations

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition, is_ant_user
from open_claude.skills.bundled.verify_content import SKILL_FILES, SKILL_MD

DESCRIPTION = "Verify a code change does what it should by running the app."


async def _get_prompt(args: str, context: object) -> list[dict]:
    parts: list[str] = [SKILL_MD.strip()]
    if args:
        parts.append(f"## User Request\n\n{args}")
    return [{"type": "text", "text": "\n\n".join(parts)}]


def register_verify_skill() -> None:
    if not is_ant_user():
        return

    register_bundled_skill(
        BundledSkillDefinition(
            name="verify",
            description=DESCRIPTION,
            user_invocable=True,
            files=SKILL_FILES,
            get_prompt_for_command=_get_prompt,
        )
    )
