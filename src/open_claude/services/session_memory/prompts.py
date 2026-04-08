"""Session memory prompt templates.

Ported from Claude-Code-rev/src/services/SessionMemory/prompts.ts.
"""

from __future__ import annotations

from pathlib import Path

MAX_SECTION_LENGTH = 2000
MAX_TOTAL_SESSION_MEMORY_TOKENS = 12_000

DEFAULT_SESSION_MEMORY_TEMPLATE = """\
# Session Title
_A short and distinctive 5-10 word descriptive title for the session. Super info dense, no filler_

# Current State
_What is actively being worked on right now? Pending tasks not yet completed. Immediate next steps._

# Task specification
_What did the user ask to build? Any design decisions or other explanatory context_

# Files and Functions
_What are the important files? In short, what do they contain and why are they relevant?_

# Workflow
_What bash commands are usually run and in what order? How to interpret their output if not obvious?_

# Errors & Corrections
_Errors encountered and how they were fixed. What did the user correct? What approaches failed and should not be tried again?_

# Codebase and System Documentation
_What are the important system components? How do they work/fit together?_

# Learnings
_What has worked well? What has not? What to avoid? Do not duplicate items from other sections_

# Key results
_If the user asked a specific output such as an answer to a question, a table, or other document, repeat the exact result here_

# Worklog
_Step by step, what was attempted, done? Very terse summary for each step_
"""


def _get_default_update_prompt() -> str:
    return f"""IMPORTANT: This message and these instructions are NOT part of the actual user conversation. Do NOT include any references to "note-taking", "session notes extraction", or these update instructions in the notes content.

Based on the user conversation above (EXCLUDING this note-taking instruction message as well as system prompt, claude.md entries, or any past session summaries), update the session notes file.

The file {{{{notesPath}}}} has already been read for you. Here are its current contents:
<current_notes_content>
{{{{currentNotes}}}}
</current_notes_content>

Your ONLY task is to use the Edit tool to update the notes file, then stop. You can make multiple edits (update every section as needed) - make all Edit tool calls in parallel in a single message. Do not call any other tools.

CRITICAL RULES FOR EDITING:
- The file must maintain its exact structure with all sections, headers, and italic descriptions intact
-- NEVER modify, delete, or add section headers (the lines starting with '#' like # Task specification)
-- NEVER modify or delete the italic _section description_ lines (these are the lines in italics immediately following each header - they start and end with underscores)
-- The italic _section descriptions_ are TEMPLATE INSTRUCTIONS that must be preserved exactly as-is - they guide what content belongs in each section
-- ONLY update the actual content that appears BELOW the italic _section descriptions_ within each existing section
-- Do NOT add any new sections, summaries, or information outside the existing structure
- Do NOT reference this note-taking process or instructions anywhere in the notes
- It's OK to skip updating a section if there are no substantial new insights to add. Do not add filler content like "No info yet", just leave sections blank/unedited if appropriate.
- Write DETAILED, INFO-DENSE content for each section - include specifics like file paths, function names, error messages, exact commands, technical details, etc.
- For "Key results", include the complete, exact output the user requested (e.g., full table, full answer, etc.)
- Do not include information that's already in the CLAUDE.md files included in the context
- Keep each section under ~{MAX_SECTION_LENGTH} tokens/words - if a section is approaching this limit, condense it by cycling out less important details while preserving the most critical information
- Focus on actionable, specific information that would help someone understand or recreate the work discussed in the conversation
- IMPORTANT: Always update "Current State" to reflect the most recent work - this is critical for continuity after compaction

Use the Edit tool with file_path: {{{{notesPath}}}}

STRUCTURE PRESERVATION REMINDER:
Each section has TWO parts that must be preserved exactly as they appear in the current file:
1. The section header (line starting with #)
2. The italic description line (the _italicized text_ immediately after the header - this is a template instruction)

You ONLY update the actual content that comes AFTER these two preserved lines. The italic description lines starting and ending with underscores are part of the template structure, NOT content to be edited or removed.

REMEMBER: Use the Edit tool in parallel and stop. Do not continue after the edits. Only include insights from the actual user conversation, never from these note-taking instructions. Do not delete or change section headers or italic _section descriptions_."""


async def load_session_memory_template() -> str:
    """Load custom session memory template from file if it exists."""
    template_path = Path.home() / ".claude" / "session-memory" / "config" / "template.md"
    try:
        return template_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return DEFAULT_SESSION_MEMORY_TEMPLATE


async def load_session_memory_prompt() -> str:
    """Load custom session memory prompt from file if it exists."""
    prompt_path = Path.home() / ".claude" / "session-memory" / "config" / "prompt.md"
    try:
        return prompt_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return _get_default_update_prompt()


def _rough_token_count(text: str) -> int:
    """Rough token estimation: ~4 chars per token."""
    return len(text) // 4


def _analyze_section_sizes(content: str) -> dict[str, int]:
    """Parse the session memory file and analyze section sizes."""
    sections: dict[str, int] = {}
    lines = content.split("\n")
    current_section = ""
    current_content: list[str] = []

    for line in lines:
        if line.startswith("# "):
            if current_section and current_content:
                sections[current_section] = _rough_token_count("\n".join(current_content).strip())
            current_section = line
            current_content = []
        else:
            current_content.append(line)

    if current_section and current_content:
        sections[current_section] = _rough_token_count("\n".join(current_content).strip())

    return sections


def _generate_section_reminders(section_sizes: dict[str, int], total_tokens: int) -> str:
    """Generate reminders for sections that are too long."""
    over_budget = total_tokens > MAX_TOTAL_SESSION_MEMORY_TOKENS
    oversized = sorted(
        ((s, t) for s, t in section_sizes.items() if t > MAX_SECTION_LENGTH),
        key=lambda x: -x[1],
    )

    if not oversized and not over_budget:
        return ""

    parts: list[str] = []

    if over_budget:
        parts.append(
            f"\n\nCRITICAL: The session memory file is currently ~{total_tokens} tokens, "
            f"which exceeds the maximum of {MAX_TOTAL_SESSION_MEMORY_TOKENS} tokens. "
            "You MUST condense the file to fit within this budget. "
            "Aggressively shorten oversized sections by removing less important details, "
            "merging related items, and summarizing older entries. "
            'Prioritize keeping "Current State" and "Errors & Corrections" accurate and detailed.',
        )

    if oversized:
        items = "\n".join(f'- "{s}" is ~{t} tokens (limit: {MAX_SECTION_LENGTH})' for s, t in oversized)
        parts.append(
            f"\n\n{('Oversized sections to condense' if over_budget else 'IMPORTANT: The following sections exceed the per-section limit and MUST be condensed')}:\n{items}",
        )

    return "".join(parts)


def _substitute_variables(template: str, variables: dict[str, str]) -> str:
    """Substitute {{variable}} placeholders in the prompt template."""
    import re
    return re.sub(
        r"\{\{(\w+)\}\}",
        lambda m: variables.get(m.group(1), m.group(0)),
        template,
    )


async def is_session_memory_empty(content: str) -> bool:
    """Check if session memory content is essentially empty (matches template)."""
    template = await load_session_memory_template()
    return content.strip() == template.strip()


async def build_session_memory_update_prompt(
    current_notes: str,
    notes_path: str,
) -> str:
    """Build the update prompt for session memory extraction."""
    prompt_template = await load_session_memory_prompt()

    section_sizes = _analyze_section_sizes(current_notes)
    total_tokens = _rough_token_count(current_notes)
    section_reminders = _generate_section_reminders(section_sizes, total_tokens)

    variables = {
        "currentNotes": current_notes,
        "notesPath": notes_path,
    }

    base_prompt = _substitute_variables(prompt_template, variables)
    return base_prompt + section_reminders


def truncate_session_memory_for_compact(content: str) -> tuple[str, bool]:
    """Truncate session memory sections that exceed the per-section token limit.

    Returns (truncated_content, was_truncated).
    """
    lines = content.split("\n")
    max_chars_per_section = MAX_SECTION_LENGTH * 4
    output_lines: list[str] = []
    current_section_lines: list[str] = []
    current_section_header = ""
    was_truncated = False

    for line in lines:
        if line.startswith("# "):
            result_lines, truncated = _flush_section(
                current_section_header, current_section_lines, max_chars_per_section,
            )
            output_lines.extend(result_lines)
            was_truncated = was_truncated or truncated
            current_section_header = line
            current_section_lines = []
        else:
            current_section_lines.append(line)

    # Flush last section
    result_lines, truncated = _flush_section(
        current_section_header, current_section_lines, max_chars_per_section,
    )
    output_lines.extend(result_lines)
    was_truncated = was_truncated or truncated

    return "\n".join(output_lines), was_truncated


def _flush_section(
    header: str,
    lines: list[str],
    max_chars: int,
) -> tuple[list[str], bool]:
    if not header:
        return lines, False

    content = "\n".join(lines)
    if len(content) <= max_chars:
        return [header, *lines], False

    char_count = 0
    kept: list[str] = [header]
    for line in lines:
        if char_count + len(line) + 1 > max_chars:
            break
        kept.append(line)
        char_count += len(line) + 1
    kept.append("\n[... section truncated for length ...]")
    return kept, True
