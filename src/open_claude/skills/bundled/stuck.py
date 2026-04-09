"""Stuck skill - diagnose frozen/slow Claude Code sessions.

Port of Claude-Code-rev/src/skills/bundled/stuck.ts
"""

from __future__ import annotations

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition, is_ant_user

STUCK_PROMPT = """# /stuck — diagnose frozen/slow Claude Code sessions

The user thinks another Claude Code session on this machine is frozen, stuck, or very slow. Investigate and post a report.

## What to look for

Scan for other Claude Code processes (excluding the current one). Process names are typically `claude` (installed) or `cli` (native dev build).

Signs of a stuck session:
- **High CPU (≥90%) sustained** — likely an infinite loop. Sample twice, 1-2s apart, to confirm it's not a transient spike.
- **Process state `D` (uninterruptible sleep)** — often an I/O hang. The `state` column in `ps` output; first character matters (ignore modifiers like `+`, `s`, `<`).
- **Process state `T` (stopped)** — user probably hit Ctrl+Z by accident.
- **Process state `Z` (zombie)** — parent isn't reaping.
- **Very high RSS (≥4GB)** — possible memory leak making the session sluggish.
- **Stuck child process** — a hung `git`, `node`, or shell subprocess can freeze the parent. Check `pgrep -lP <pid>` for each session.

## Investigation steps

1. **List all Claude Code processes** (macOS/Linux):
   ```
   ps -axo pid=,pcpu=,rss=,etime=,state=,comm=,command= | grep -E '(claude|cli)' | grep -v grep
   ```
   Filter to rows where `comm` is `claude` or (`cli` AND the command path contains "claude").

2. **For anything suspicious**, gather more context:
   - Child processes: `pgrep -lP <pid>`
   - If high CPU: sample again after 1-2s to confirm it's sustained
   - If a child looks hung (e.g., a git command), note its full command line with `ps -p <child_pid> -o command=`
   - Check the session's debug log if you can infer the session ID: `~/.claude/debug/<session-id>.txt`

3. **Consider a stack dump** for a truly frozen process (advanced, optional):
   - macOS: `sample <pid> 3` gives a 3-second native stack sample
   - This is big — only grab it if the process is clearly hung and you want to know *why*

## Report

Only report findings to the user. If every session looks healthy, tell the user that directly.

## Notes
- Don't kill or signal any processes — this is diagnostic only.
- If the user gave an argument (e.g., a specific PID or symptom), focus there first.
"""


async def _get_prompt(args: str, context: object) -> list[dict]:
    prompt = STUCK_PROMPT
    if args:
        prompt += f"\n## User-provided context\n\n{args}\n"
    return [{"type": "text", "text": prompt}]


def register_stuck_skill() -> None:
    if not is_ant_user():
        return

    register_bundled_skill(
        BundledSkillDefinition(
            name="stuck",
            description="[ANT-ONLY] Investigate frozen/stuck/slow Claude Code sessions on this machine and produce a diagnostic report.",
            user_invocable=True,
            get_prompt_for_command=_get_prompt,
        )
    )
