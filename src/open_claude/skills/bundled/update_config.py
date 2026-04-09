"""Update Config skill - configure Claude Code via settings.json.

Port of Claude-Code-rev/src/skills/bundled/updateConfig.ts
"""

from __future__ import annotations

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition

SETTINGS_EXAMPLES_DOCS = """## Settings File Locations

Choose the appropriate file based on scope:

| File | Scope | Git | Use For |
|------|-------|-----|---------|
| `~/.claude/settings.json` | Global | N/A | Personal preferences for all projects |
| `.claude/settings.json` | Project | Commit | Team-wide hooks, permissions, plugins |
| `.claude/settings.local.json` | Project | Gitignore | Personal overrides for this project |

Settings load in order: user → project → local (later overrides earlier).

## Settings Schema Reference

### Permissions
```json
{
  "permissions": {
    "allow": ["Bash(npm:*)", "Edit(.claude)", "Read"],
    "deny": ["Bash(rm -rf:*)"],
    "ask": ["Write(/etc/*)"],
    "defaultMode": "default" | "plan" | "acceptEdits" | "dontAsk",
    "additionalDirectories": ["/extra/dir"]
  }
}
```

**Permission Rule Syntax:**
- Exact match: `"Bash(npm run test)"`
- Prefix wildcard: `"Bash(git:*)"` - matches `git status`, `git commit`, etc.
- Tool only: `"Read"` - allows all Read operations

### Environment Variables
```json
{
  "env": {
    "DEBUG": "true",
    "MY_API_KEY": "value"
  }
}
```

### Model & Agent
```json
{
  "model": "sonnet",
  "agent": "agent-name",
  "alwaysThinkingEnabled": true
}
```

### Attribution (Commits & PRs)
```json
{
  "attribution": {
    "commit": "Custom commit trailer text",
    "pr": "Custom PR description text"
  }
}
```
Set `commit` or `pr` to empty string `""` to hide that attribution.

### MCP Server Management
```json
{
  "enableAllProjectMcpServers": true,
  "enabledMcpjsonServers": ["server1", "server2"],
  "disabledMcpjsonServers": ["blocked-server"]
}
```

### Other Settings
- `language`: Preferred response language
- `cleanupPeriodDays`: Days to keep transcripts (default: 30; 0 disables persistence entirely)
- `respectGitignore`: Whether to respect .gitignore (default: true)
"""

HOOKS_DOCS = """## Hooks Configuration

Hooks run commands at specific points in Claude Code's lifecycle.

### Hook Structure
```json
{
  "hooks": {
    "EVENT_NAME": [
      {
        "matcher": "ToolName|OtherTool",
        "hooks": [
          {
            "type": "command",
            "command": "your-command-here",
            "timeout": 60,
            "statusMessage": "Running..."
          }
        ]
      }
    ]
  }
}
```

### Hook Events

| Event | Matcher | Purpose |
|-------|---------|---------|
| PermissionRequest | Tool name | Run before permission prompt |
| PreToolUse | Tool name | Run before tool, can block |
| PostToolUse | Tool name | Run after successful tool |
| PostToolUseFailure | Tool name | Run after tool fails |
| Notification | Notification type | Run on notifications |
| Stop | - | Run when Claude stops |
| PreCompact | "manual"/"auto" | Before compaction |
| PostCompact | "manual"/"auto" | After compaction |
| UserPromptSubmit | - | When user submits |
| SessionStart | - | When session starts |

**Common tool matchers:** `Bash`, `Write`, `Edit`, `Read`, `Glob`, `Grep`

### Hook Types

**1. Command Hook** - Runs a shell command:
```json
{ "type": "command", "command": "prettier --write $FILE", "timeout": 30 }
```

**2. Prompt Hook** - Evaluates a condition with LLM:
```json
{ "type": "prompt", "prompt": "Is this safe? $ARGUMENTS" }
```

**3. Agent Hook** - Runs an agent with tools:
```json
{ "type": "agent", "prompt": "Verify tests pass: $ARGUMENTS" }
```

### Hook Input (stdin JSON)
```json
{
  "session_id": "abc123",
  "tool_name": "Write",
  "tool_input": { "file_path": "/path/to/file.txt", "content": "..." },
  "tool_response": { "success": true }
}
```

### Hook JSON Output
```json
{
  "systemMessage": "Warning shown to user in UI",
  "continue": false,
  "stopReason": "Message shown when blocking",
  "suppressOutput": false,
  "decision": "block",
  "reason": "Explanation for decision"
}
```

### Common Patterns

**Auto-format after writes:**
```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Write|Edit",
      "hooks": [{
        "type": "command",
        "command": "jq -r '.tool_response.filePath // .tool_input.file_path' | { read -r f; prettier --write \\"$f\\"; } 2>/dev/null || true"
      }]
    }]
  }
}
```

**Log all bash commands:**
```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{
        "type": "command",
        "command": "jq -r '.tool_input.command' >> ~/.claude/bash-log.txt"
      }]
    }]
  }
}
```
"""

HOOK_VERIFICATION_FLOW = """## Constructing a Hook (with verification)

1. **Dedup check.** Read the target file. If a hook already exists on the same event+matcher, show the existing command and ask: keep it, replace it, or add alongside.

2. **Construct the command for THIS project.** The hook receives JSON on stdin. Build a command that extracts payload safely.

3. **Pipe-test the raw command.** Synthesize the stdin payload and pipe it directly to verify it works.

4. **Write the JSON.** Merge into the target file.

5. **Validate syntax + schema in one shot:**
   `jq -e '.hooks.<event>[] | select(.matcher == "<matcher>") | .hooks[] | select(.type == "command") | .command' <target-file>`

6. **Prove the hook fires** — trigger the matching tool and verify the hook executed.

7. **Handoff.** Tell the user the hook is live.
"""

UPDATE_CONFIG_PROMPT = f"""# Update Config Skill

Modify Claude Code configuration by updating settings.json files.

## When Hooks Are Required (Not Memory)

If the user wants something to happen automatically in response to an EVENT, they need a **hook** configured in settings.json. Memory/preferences cannot trigger automated actions.

## CRITICAL: Read Before Write

**Always read the existing settings file before making changes.** Merge new settings with existing ones - never replace the entire file.

## CRITICAL: Use AskUserQuestion for Ambiguity

When the user's request is ambiguous, use AskUserQuestion to clarify:
- Which settings file to modify (user/project/local)
- Whether to add to existing arrays or replace them
- Specific values when multiple options exist

## Decision: Config Tool vs Direct Edit

**Use the Config tool** for these simple settings:
- `theme`, `editorMode`, `verbose`, `model`
- `language`, `alwaysThinkingEnabled`
- `permissions.defaultMode`

**Edit settings.json directly** for:
- Hooks (PreToolUse, PostToolUse, etc.)
- Complex permission rules (allow/deny arrays)
- Environment variables
- MCP server configuration
- Plugin configuration

## Workflow

1. **Clarify intent** - Ask if the request is ambiguous
2. **Read existing file** - Use Read tool on the target settings file
3. **Merge carefully** - Preserve existing settings, especially arrays
4. **Edit file** - Use Edit tool (if file doesn't exist, ask user to create it first)
5. **Confirm** - Tell user what was changed

## Merging Arrays (Important!)

When adding to permission arrays or hook arrays, **merge with existing**, don't replace.

{SETTINGS_EXAMPLES_DOCS}

{HOOKS_DOCS}

{HOOK_VERIFICATION_FLOW}

## Common Mistakes to Avoid

1. **Replacing instead of merging** - Always preserve existing settings
2. **Wrong file** - Ask user if scope is unclear
3. **Invalid JSON** - Validate syntax after changes
4. **Forgetting to read first** - Always read before write

## Troubleshooting Hooks

If a hook isn't running:
1. Check the settings file
2. Verify JSON syntax
3. Check the matcher
4. Check hook type
5. Test the command manually
6. Use --debug to see hook execution logs
"""


async def _get_prompt(args: str, context: object) -> list[dict]:
    if args.startswith("[hooks-only]"):
        req = args[len("[hooks-only]"):].strip()
        prompt = HOOKS_DOCS + "\n\n" + HOOK_VERIFICATION_FLOW
        if req:
            prompt += f"\n\n## Task\n\n{req}"
        return [{"type": "text", "text": prompt}]

    prompt = UPDATE_CONFIG_PROMPT

    if args:
        prompt += f"\n\n## User Request\n\n{args}"

    return [{"type": "text", "text": prompt}]


def register_update_config_skill() -> None:
    register_bundled_skill(
        BundledSkillDefinition(
            name="update-config",
            description=(
                "Use this skill to configure the Claude Code harness via settings.json. "
                'Automated behaviors ("from now on when X", "each time X", "whenever X", '
                '"before/after X") require hooks configured in settings.json. '
                "Also use for: permissions, env vars, hook troubleshooting, "
                "or any changes to settings.json files."
            ),
            allowed_tools=["Read"],
            user_invocable=True,
            get_prompt_for_command=_get_prompt,
        )
    )
