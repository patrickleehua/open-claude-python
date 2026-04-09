"""Central skill registry for all skills (bundled + disk-based + dynamic).

Port of TypeScript bundledSkills.ts registry pattern.
"""

from __future__ import annotations

import logging

from open_claude.skills.types import SkillCommand

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Central registry for all skills (bundled + disk-based + dynamic)."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillCommand] = {}
        self._alias_map: dict[str, str] = {}
        self._dynamic_skills: dict[str, SkillCommand] = {}
        self._conditional_skills: dict[str, SkillCommand] = {}
        self._activated_conditional: set[str] = set()

    def register(self, skill: SkillCommand) -> None:
        """Register a skill command."""
        self._skills[skill.name] = skill
        for alias in skill.aliases:
            self._alias_map[alias] = skill.name

    def find(self, name: str) -> SkillCommand | None:
        """Find a skill by name or alias. Checks dynamic skills first."""
        # Check dynamic skills first (highest priority)
        if name in self._dynamic_skills:
            return self._dynamic_skills[name]
        # Check registered skills
        if name in self._skills:
            return self._skills[name]
        # Check aliases
        if name in self._alias_map:
            return self._skills.get(self._alias_map[name])
        # Check dynamic skill aliases
        for skill in self._dynamic_skills.values():
            if name in skill.aliases:
                return skill
        return None

    def get_all(self) -> list[SkillCommand]:
        """Return all registered skills (bundled + dynamic)."""
        result = list(self._skills.values())
        for name, skill in self._dynamic_skills.items():
            if name not in self._skills:
                result.append(skill)
        return result

    def get_visible(self) -> list[SkillCommand]:
        """Return all non-hidden, enabled skills."""
        return [s for s in self.get_all() if not s.is_hidden and s.is_enabled()]

    def get_user_invocable(self) -> list[SkillCommand]:
        """Return all user-invocable skills."""
        return [
            s for s in self.get_all() if s.user_invocable and s.is_enabled()
        ]

    def get_skill_commands_for_prompt(self) -> list[dict]:
        """Return skill metadata for inclusion in system prompt.

        Format matches the skill_tool_commands structure expected by
        prompt_builder.build_system_prompt().
        """
        result = []
        for skill in self.get_user_invocable():
            entry: dict[str, Any] = {
                "name": skill.name,
                "description": skill.description,
                "userInvocable": skill.user_invocable,
            }
            if skill.when_to_use:
                entry["whenToUse"] = skill.when_to_use
            if skill.argument_hint:
                entry["argumentHint"] = skill.argument_hint
            if skill.aliases:
                entry["aliases"] = skill.aliases
            result.append(entry)
        return result

    def add_dynamic_skill(self, skill: SkillCommand) -> None:
        """Add a dynamically discovered skill."""
        self._dynamic_skills[skill.name] = skill

    def activate_conditional_skills(
        self, file_paths: list[str], cwd: str
    ) -> list[str]:
        """Activate conditional skills whose paths match given file paths.

        Returns list of newly activated skill names.
        """
        if not self._conditional_skills:
            return []

        activated: list[str] = []

        for name, skill in list(self._conditional_skills.items()):
            # For now, simple activation without full gitignore matching
            # Full path matching can be added when the `ignore` library is available
            if name not in self._activated_conditional:
                self._dynamic_skills[name] = skill
                del self._conditional_skills[name]
                self._activated_conditional.add(name)
                activated.append(name)

        return activated

    def clear(self) -> None:
        """Clear all registered skills."""
        self._skills.clear()
        self._alias_map.clear()
        self._dynamic_skills.clear()
        self._conditional_skills.clear()
        self._activated_conditional.clear()
