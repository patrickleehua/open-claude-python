"""Verify skill content bundle.

Port of Claude-Code-rev/src/skills/bundled/verifyContent.ts
"""

from __future__ import annotations

SKILL_MD = """# Verify Skill

Verify a code change does what it should by running the app.

## Steps

1. **Understand the change** - Read the git diff or the files the user mentions
2. **Identify verification strategy** - Determine how to verify the change works
3. **Run verification** - Execute tests, build, or manual verification
4. **Report results** - Summarize what was verified and any issues found
"""

SKILL_FILES: dict[str, str] = {
    "examples/cli.md": "# CLI Verification\n\nVerify CLI changes by running commands.\n\nRestored placeholder content.",
    "examples/server.md": "# Server Verification\n\nVerify server changes by making requests.\n\nRestored placeholder content.",
}
