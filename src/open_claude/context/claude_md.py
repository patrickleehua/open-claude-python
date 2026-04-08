"""CLAUDE.md file discovery and reading for the system prompt."""

from __future__ import annotations

from pathlib import Path


async def find_claude_md_files(work_dir: Path) -> list[Path]:
    """Find all CLAUDE.md files in the project hierarchy.

    Search order:
    1. work_dir/CLAUDE.md
    2. work_dir/.claude/CLAUDE.md
    3. Parent directories up to home (CLAUDE.md files only)
    4. ~/.claude/CLAUDE.md (global user instructions)
    """
    found: list[Path] = []

    # 1 & 2: Project-level files
    project_claude_md = work_dir / "CLAUDE.md"
    if project_claude_md.is_file():
        found.append(project_claude_md)

    dot_claude_md = work_dir / ".claude" / "CLAUDE.md"
    if dot_claude_md.is_file():
        found.append(dot_claude_md)

    # 3: Walk parent directories up to home
    home = Path.home()
    current = work_dir.resolve().parent
    home_resolved = home.resolve()

    while current != current.parent and current != home_resolved:
        candidate = current / "CLAUDE.md"
        if candidate.is_file():
            found.append(candidate)
        current = current.parent

    # 4: Global user instructions
    global_claude_md = home / ".claude" / "CLAUDE.md"
    if global_claude_md.is_file():
        found.append(global_claude_md)

    return found


async def read_claude_md_content(files: list[Path]) -> str:
    """Read and concatenate CLAUDE.md file contents.

    Each file's content is wrapped with a header showing the file path.
    Returns an empty string if no files are provided.
    """
    if not files:
        return ""

    sections: list[str] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if content:
            header = f"# {path}"
            sections.append(f"{header}\n{content}")

    return "\n\n".join(sections)


def format_claude_md_section(content: str) -> str:
    """Wrap CLAUDE.md content in XML tags for the system prompt."""
    if not content:
        return ""
    return f"<user_instructions>\n{content}\n</user_instructions>"
