"""Remember skill - review and organize auto-memory entries.

Port of Claude-Code-rev/src/skills/bundled/remember.ts
"""

from __future__ import annotations

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition, is_ant_user

SKILL_PROMPT = """# Memory Review

## Goal
Review the user's memory landscape and produce a clear report of proposed changes, grouped by action type. Do NOT apply changes — present proposals for user approval.

## Steps

### 1. Gather all memory layers
Read CLAUDE.md and CLAUDE.local.md from the project root (if they exist). Your auto-memory content is already in your system prompt — review it there. Note which team memory sections exist, if any.

**Success criteria**: You have the contents of all memory layers and can compare them.

### 2. Classify each auto-memory entry
For each substantive entry in auto-memory, determine the best destination:

| Destination | What belongs there | Examples |
|---|---|---|
| **CLAUDE.md** | Project conventions and instructions for Claude that all contributors should follow | "use bun not npm", "API routes use kebab-case", "test command is bun test", "prefer functional style" |
| **CLAUDE.local.md** | Personal instructions for Claude specific to this user, not applicable to other contributors | "I prefer concise responses", "always explain trade-offs", "don't auto-commit", "run tests before committing" |
| **Team memory** | Org-wide knowledge that applies across repositories (only if team memory is configured) | "deploy PRs go through #deploy-queue", "staging is at staging.internal", "platform team owns infra" |
| **Stay in auto-memory** | Working notes, temporary context, or entries that don't clearly fit elsewhere | Session-specific observations, uncertain patterns |

**Important distinctions:**
- CLAUDE.md and CLAUDE.local.md contain instructions for Claude, not user preferences for external tools (editor theme, IDE keybindings, etc. don't belong in either)
- Workflow practices (PR conventions, merge strategies, branch naming) are ambiguous — ask the user whether they're personal or team-wide
- When unsure, ask rather than guess

**Success criteria**: Each entry has a proposed destination or is flagged as ambiguous.

### 3. Identify cleanup opportunities
Scan across all layers for:
- **Duplicates**: Auto-memory entries already captured in CLAUDE.md or CLAUDE.local.md → propose removing from auto-memory
- **Outdated**: CLAUDE.md or CLAUDE.local.md entries contradicted by newer auto-memory entries → propose updating the older layer
- **Conflicts**: Contradictions between any two layers → propose resolution, noting which is more recent

**Success criteria**: All cross-layer issues identified.

### 4. Present the report
Output a structured report grouped by action type:
1. **Promotions** — entries to move, with destination and rationale
2. **Cleanup** — duplicates, outdated entries, conflicts to resolve
3. **Ambiguous** — entries where you need the user's input on destination
4. **No action needed** — brief note on entries that should stay put

If auto-memory is empty, say so and offer to review CLAUDE.md for cleanup.

**Success criteria**: User can review and approve/reject each proposal individually.

## Rules
- Present ALL proposals before making any changes
- Do NOT modify files without explicit user approval
- Do NOT create new files unless the target doesn't exist yet
- Ask about ambiguous entries — don't guess
"""


async def _get_prompt(args: str, context: object) -> list[dict]:
    prompt = SKILL_PROMPT
    if args:
        prompt += f"\n## Additional context from user\n\n{args}"
    return [{"type": "text", "text": prompt}]


def register_remember_skill() -> None:
    if not is_ant_user():
        return

    register_bundled_skill(
        BundledSkillDefinition(
            name="remember",
            description="Review auto-memory entries and propose promotions to CLAUDE.md, CLAUDE.local.md, or shared memory. Also detects outdated, conflicting, and duplicate entries across memory layers.",
            when_to_use="Use when the user wants to review, organize, or promote their auto-memory entries. Also useful for cleaning up outdated or conflicting entries across CLAUDE.md, CLAUDE.local.md, and auto-memory.",
            user_invocable=True,
            is_enabled=lambda: True,  # isAutoMemoryEnabled equivalent
            get_prompt_for_command=_get_prompt,
        )
    )
