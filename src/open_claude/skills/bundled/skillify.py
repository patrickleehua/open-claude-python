"""Skillify skill - capture session's repeatable process into a reusable skill.

Port of Claude-Code-rev/src/skills/bundled/skillify.ts
"""

from __future__ import annotations

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition, is_ant_user

SKILLIFY_PROMPT = """# Skillify {{userDescriptionBlock}}

You are capturing this session's repeatable process as a reusable skill.

## Your Task

### Step 1: Analyze the Session

Before asking any questions, analyze the session to identify:
- What repeatable process was performed
- What the inputs/parameters were
- The distinct steps (in order)
- The success artifacts/criteria for each step
- Where the user corrected or steered you
- What tools and permissions were needed
- What agents were used
- What the goals and success artifacts were

### Step 2: Interview the User

You will use the AskUserQuestion to understand what the user wants to automate. Important notes:
- Use AskUserQuestion for ALL questions! Never ask questions via plain text.
- For each round, iterate as much as needed until the user is happy.
- The user always has a freeform "Other" option to type edits or feedback.

**Round 1: High level confirmation**
- Suggest a name and description for the skill based on your analysis. Ask the user to confirm or rename.
- Suggest high-level goal(s) and specific success criteria for the skill.

**Round 2: More details**
- Present the high-level steps you identified as a numbered list. Tell the user you will dig into the detail in the next round.
- If you think the skill will require arguments, suggest arguments based on what you observed.
- If it's not clear, ask if this skill should run inline (in the current conversation) or forked (as a sub-agent with its own context).
- Ask where the skill should be saved. Options:
  - **This repo** (`.claude/skills/<name>/SKILL.md`)
  - **Personal** (`~/.claude/skills/<name>/SKILL.md`)

**Round 3: Breaking down each step**
For each major step, if it's not glaringly obvious, ask:
- What does this step produce that later steps need?
- What proves that this step succeeded?
- Should the user be asked to confirm before proceeding?
- Are any steps independent and could run in parallel?
- How should the skill be executed?
- What are the hard constraints or hard preferences?

You may do multiple rounds of AskUserQuestion here, one round per step.

IMPORTANT: Pay special attention to places where the user corrected you during the session.

**Round 4: Final questions**
- Confirm when this skill should be invoked, and suggest trigger phrases.
- Ask for any other gotchas or things to watch out for.

Stop interviewing once you have enough information. IMPORTANT: Don't over-ask for simple processes!

### Step 3: Write the SKILL.md

Create the skill directory and file at the location the user chose in Round 2.

Use this format:

```markdown
---
name: {{skill-name}}
description: {{one-line description}}
allowed-tools:
  {{list of tool permission patterns}}
when_to_use: {{detailed description of when to invoke}}
argument-hint: "{{hint showing argument placeholders}}"
arguments:
  {{list of argument names}}
context: {{inline or fork -- omit for inline}}
---

# {{Skill Title}}
Description of skill

## Inputs
- `$arg_name`: Description of this input

## Goal
Clearly stated goal for this workflow.

## Steps

### 1. Step Name
What to do in this step.

**Success criteria**: ALWAYS include this!

...
```

**Per-step annotations**:
- **Success criteria** is REQUIRED on every step.
- **Execution**: `Direct` (default), `Task agent`, `Teammate`, or `[human]`.
- **Artifacts**: Data this step produces that later steps need.
- **Human checkpoint**: When to pause and ask the user before proceeding.
- **Rules**: Hard rules for the workflow.

### Step 4: Confirm and Save

Before writing the file, output the complete SKILL.md content as a yaml code block for review. Then ask for confirmation.

After writing, tell the user:
- Where the skill was saved
- How to invoke it: `/{{skill-name}} [arguments]`
- That they can edit the SKILL.md directly to refine it
"""


async def _get_prompt(args: str, context: object) -> list[dict]:
    user_description_block = (
        f"The user described this process as: \"{args}\"" if args else ""
    )

    prompt = SKILLIFY_PROMPT.replace("{{userDescriptionBlock}}", user_description_block)

    return [{"type": "text", "text": prompt}]


def register_skillify_skill() -> None:
    if not is_ant_user():
        return

    register_bundled_skill(
        BundledSkillDefinition(
            name="skillify",
            description="Capture this session's repeatable process into a skill. Call at end of the process you want to capture with an optional description.",
            allowed_tools=[
                "Read",
                "Write",
                "Edit",
                "Glob",
                "Grep",
                "AskUserQuestion",
                "Bash(mkdir:*)",
            ],
            user_invocable=True,
            disable_model_invocation=True,
            argument_hint="[description of the process you want to capture]",
            get_prompt_for_command=_get_prompt,
        )
    )
