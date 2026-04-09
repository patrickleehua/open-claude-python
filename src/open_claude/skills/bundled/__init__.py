"""Bundled skills initialization.

Port of Claude-Code-rev/src/skills/bundled/index.ts

Registers all bundled skills at startup. Feature-flagged skills
are gated via CLAUDE_CODE_FEATURE_* environment variables.

To add a new bundled skill:
1. Create a new file in skills/bundled/ (e.g., myskill.py)
2. Export a register function that calls register_bundled_skill()
3. Import and call that function in _init_bundled_skills()
"""

from __future__ import annotations

import logging

from open_claude.skills.types import is_feature_enabled

logger = logging.getLogger(__name__)


def _init_bundled_skills() -> None:
    """Initialize all bundled skills.

    Called at startup to register skills that ship with the CLI.
    """
    # Always-registered skills
    from open_claude.skills.bundled.update_config import register_update_config_skill
    from open_claude.skills.bundled.keybindings import register_keybindings_skill
    from open_claude.skills.bundled.verify import register_verify_skill
    from open_claude.skills.bundled.debug import register_debug_skill
    from open_claude.skills.bundled.lorem_ipsum import register_lorem_ipsum_skill
    from open_claude.skills.bundled.skillify import register_skillify_skill
    from open_claude.skills.bundled.remember import register_remember_skill
    from open_claude.skills.bundled.simplify import register_simplify_skill
    from open_claude.skills.bundled.batch import register_batch_skill
    from open_claude.skills.bundled.stuck import register_stuck_skill

    register_update_config_skill()
    register_keybindings_skill()
    register_verify_skill()
    register_debug_skill()
    register_lorem_ipsum_skill()
    register_skillify_skill()
    register_remember_skill()
    register_simplify_skill()
    register_batch_skill()
    register_stuck_skill()

    # Feature-flagged skills
    if is_feature_enabled("KAIROS") or is_feature_enabled("KAIROS_DREAM"):
        from open_claude.skills.bundled.dream import register_dream_skill
        register_dream_skill()

    if is_feature_enabled("REVIEW_ARTIFACT"):
        from open_claude.skills.bundled.hunter import register_hunter_skill
        register_hunter_skill()

    if is_feature_enabled("AGENT_TRIGGERS"):
        from open_claude.skills.bundled.loop import register_loop_skill
        register_loop_skill()

    if is_feature_enabled("AGENT_TRIGGERS_REMOTE"):
        from open_claude.skills.bundled.schedule_remote_agents import (
            register_schedule_remote_agents_skill,
        )
        register_schedule_remote_agents_skill()

    if is_feature_enabled("BUILDING_CLAUDE_APPS"):
        from open_claude.skills.bundled.claude_api import register_claude_api_skill
        register_claude_api_skill()

    # claude-in-chrome: enabled when MCP browser tools are detected
    # For now, check env var
    if is_feature_enabled("CLAUDE_IN_CHROME"):
        from open_claude.skills.bundled.claude_in_chrome import (
            register_claude_in_chrome_skill,
        )
        register_claude_in_chrome_skill()

    if is_feature_enabled("RUN_SKILL_GENERATOR"):
        from open_claude.skills.bundled.run_skill_generator import (
            register_run_skill_generator_skill,
        )
        register_run_skill_generator_skill()

    logger.debug("Bundled skills initialized")
