"""/commit command — generate a git commit via the model.

This is a **PromptCommand**: it expands into a structured prompt that instructs
the model to analyse staged changes and create a commit.

Mirrors ``Claude-Code-rev/src/commands/commit.ts``.
"""

from __future__ import annotations

from open_claude.commands.base import CommandResult, CommandResultType, PromptCommand

_COMMIT_PROMPT = """\
## Context

- Current git status: !`git status`
- Current git diff (staged and unstaged changes): !`git diff HEAD`
- Current branch: !`git branch --show-current`
- Recent commits: !`git log --oneline -10`

## Git Safety Protocol

- NEVER update the git config
- NEVER skip hooks (--no-verify, --no-gpg-sign, etc) unless the user explicitly requests it
- CRITICAL: ALWAYS create NEW commits. NEVER use git commit --amend, unless the user explicitly requests it
- Do not commit files that likely contain secrets (.env, credentials.json, etc). Warn the user if they specifically request to commit those files
- If there are no changes to commit (i.e., no untracked files and no modifications), do not create an empty commit
- Never use git commands with the -i flag (like git rebase -i or git add -i) since they require interactive input which is not supported

## Your task

Based on the above changes, create a single git commit:

1. Analyze all staged changes and draft a commit message:
   - Look at the recent commits above to follow this repository's commit message style
   - Summarize the nature of the changes (new feature, enhancement, bug fix, refactoring, test, docs, etc.)
   - Ensure the message accurately reflects the changes and their purpose
   - Draft a concise (1-2 sentences) commit message that focuses on the "why" rather than the "what"

2. Stage relevant files and create the commit using HEREDOC syntax:
```bash
git add -A && git commit -m "$(cat <<'EOF'
Commit message here.

Co-Authored-By: open-claude-python <noreply@open-claude.dev>
EOF
)"
```

Stage and create the commit using a single message. Do not use any other tools or do anything else.
"""

ALLOWED_TOOLS = [
    "Bash(git add:*)",
    "Bash(git status:*)",
    "Bash(git commit:*)",
]


class CommitCommand(PromptCommand):
    name = "commit"
    description = "Create a git commit"
    argument_hint = ""

    async def execute(self, args: str, context) -> CommandResult:  # type: ignore[override]
        return CommandResult(
            type=CommandResultType.TEXT,
            value=_COMMIT_PROMPT,
            should_query=True,
            prompt_content=_COMMIT_PROMPT,
            allowed_tools=ALLOWED_TOOLS,
        )
