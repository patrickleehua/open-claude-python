"""Diff generation and terminal rendering helpers for file mutations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from rich.markup import escape

CONTEXT_LINES = 3


def _expand_path(path_str: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path_str))).resolve()


@dataclass(frozen=True)
class DiffLine:
    """A single rendered line inside a structured diff hunk."""

    kind: str
    old_lineno: int | None
    new_lineno: int | None
    text: str


@dataclass(frozen=True)
class DiffHunk:
    """A contiguous diff hunk with surrounding context lines."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine]


@dataclass(frozen=True)
class FileDiffPreview:
    """Serializable preview payload for permission prompts and result echo."""

    file_path: str
    operation: str
    additions: int
    removals: int
    hunks: list[DiffHunk]

    def to_display_data(self, *, title: str, status: str, dim: bool = False) -> dict[str, object]:
        """Convert preview data into a UI-friendly payload."""
        return {
            "kind": "file_diff",
            "title": title,
            "status": status,
            "file_path": self.file_path,
            "operation": self.operation,
            "additions": self.additions,
            "removals": self.removals,
            "markup": render_diff_preview_markup(self, dim=dim),
        }


def _split_lines(content: str) -> list[str]:
    return content.splitlines()


def _count_lines(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + (0 if content.endswith("\n") else 1)


def build_file_diff_preview(
    *,
    file_path: str,
    old_content: str,
    new_content: str,
    operation: str,
    context_lines: int = CONTEXT_LINES,
) -> FileDiffPreview:
    """Build a structured diff preview with context lines."""
    old_lines = _split_lines(old_content)
    new_lines = _split_lines(new_content)
    matcher = SequenceMatcher(a=old_lines, b=new_lines)
    grouped = matcher.get_grouped_opcodes(context_lines)
    hunks: list[DiffHunk] = []
    additions = 0
    removals = 0

    for group in grouped:
        hunk_lines: list[DiffLine] = []
        old_start = group[0][1] + 1
        new_start = group[0][3] + 1
        old_count = group[-1][2] - group[0][1]
        new_count = group[-1][4] - group[0][3]

        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for old_idx, new_idx in zip(range(i1, i2), range(j1, j2), strict=False):
                    hunk_lines.append(
                        DiffLine(
                            kind="context",
                            old_lineno=old_idx + 1,
                            new_lineno=new_idx + 1,
                            text=old_lines[old_idx],
                        )
                    )
            elif tag == "delete":
                removals += i2 - i1
                for old_idx in range(i1, i2):
                    hunk_lines.append(
                        DiffLine(
                            kind="delete",
                            old_lineno=old_idx + 1,
                            new_lineno=None,
                            text=old_lines[old_idx],
                        )
                    )
            elif tag == "insert":
                additions += j2 - j1
                for new_idx in range(j1, j2):
                    hunk_lines.append(
                        DiffLine(
                            kind="insert",
                            old_lineno=None,
                            new_lineno=new_idx + 1,
                            text=new_lines[new_idx],
                        )
                    )
            elif tag == "replace":
                removals += i2 - i1
                additions += j2 - j1
                for old_idx in range(i1, i2):
                    hunk_lines.append(
                        DiffLine(
                            kind="delete",
                            old_lineno=old_idx + 1,
                            new_lineno=None,
                            text=old_lines[old_idx],
                        )
                    )
                for new_idx in range(j1, j2):
                    hunk_lines.append(
                        DiffLine(
                            kind="insert",
                            old_lineno=None,
                            new_lineno=new_idx + 1,
                            text=new_lines[new_idx],
                        )
                    )

        hunks.append(
            DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=hunk_lines,
            )
        )

    if not hunks and operation == "create" and new_lines:
        additions = _count_lines(new_content)
        hunks = [
            DiffHunk(
                old_start=1,
                old_count=0,
                new_start=1,
                new_count=len(new_lines),
                lines=[
                    DiffLine(kind="insert", old_lineno=None, new_lineno=index + 1, text=line)
                    for index, line in enumerate(new_lines)
                ],
            )
        ]
    elif not hunks and operation == "overwrite":
        additions = _count_lines(new_content)
        removals = _count_lines(old_content)
        hunks = [
            DiffHunk(
                old_start=1,
                old_count=len(old_lines),
                new_start=1,
                new_count=len(new_lines),
                lines=[
                    *[
                        DiffLine(kind="delete", old_lineno=index + 1, new_lineno=None, text=line)
                        for index, line in enumerate(old_lines)
                    ],
                    *[
                        DiffLine(kind="insert", old_lineno=None, new_lineno=index + 1, text=line)
                        for index, line in enumerate(new_lines)
                    ],
                ],
            )
        ]

    return FileDiffPreview(
        file_path=file_path,
        operation=operation,
        additions=additions,
        removals=removals,
        hunks=hunks,
    )


def build_edit_preview(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> FileDiffPreview:
    """Build a preview for an Edit tool invocation."""
    path = _expand_path(file_path)
    old_content = path.read_text(encoding="utf-8")
    if replace_all:
        new_content = old_content.replace(old_string, new_string)
    else:
        new_content = old_content.replace(old_string, new_string, 1)
    return build_file_diff_preview(
        file_path=str(path),
        old_content=old_content,
        new_content=new_content,
        operation="edit",
    )


def build_write_preview(file_path: str, content: str) -> FileDiffPreview:
    """Build a preview for a Write tool invocation."""
    path = _expand_path(file_path)
    if path.exists():
        old_content = path.read_text(encoding="utf-8")
        operation = "overwrite"
    else:
        old_content = ""
        operation = "create"
    return build_file_diff_preview(
        file_path=str(path),
        old_content=old_content,
        new_content=content,
        operation=operation,
    )


def preview_for_tool_input(tool_name: str, tool_input: dict[str, object]) -> FileDiffPreview | None:
    """Build a diff preview for supported mutating file tools."""
    try:
        if tool_name == "Edit":
            return build_edit_preview(
                str(tool_input.get("file_path", "")),
                str(tool_input.get("old_string", "")),
                str(tool_input.get("new_string", "")),
                bool(tool_input.get("replace_all", False)),
            )
        if tool_name == "Write":
            return build_write_preview(
                str(tool_input.get("file_path", "")),
                str(tool_input.get("content", "")),
            )
    except (OSError, UnicodeDecodeError, FileNotFoundError):
        return None
    return None


def render_diff_preview_markup(preview: FileDiffPreview, *, dim: bool = False) -> str:
    """Render a structured diff preview as Rich markup text."""
    style_dim = "dim " if dim else ""
    lines = [
        f"[dim]{escape(preview.file_path)}[/dim]",
        f"[{style_dim}green]Added {preview.additions} line{'s' if preview.additions != 1 else ''}[/{style_dim}green]"
        + (
            f" [{style_dim}white],[/{style_dim}white] "
            f"[{style_dim}red]Removed {preview.removals} line{'s' if preview.removals != 1 else ''}[/{style_dim}red]"
            if preview.removals
            else ""
        ),
    ]
    for hunk_index, hunk in enumerate(preview.hunks):
        if hunk_index:
            lines.append(f"[dim]{'-' * 12}[/dim]")
        lines.append(
            f"[dim]@@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@[/dim]"
        )
        for line in hunk.lines:
            old_no = "" if line.old_lineno is None else str(line.old_lineno)
            new_no = "" if line.new_lineno is None else str(line.new_lineno)
            escaped = escape(line.text) if line.text else " "
            if line.kind == "delete":
                lines.append(f"[{style_dim}red]{old_no:>4} {'':>4} - {escaped}[/{style_dim}red]")
            elif line.kind == "insert":
                lines.append(f"[{style_dim}green]{'':>4} {new_no:>4} + {escaped}[/{style_dim}green]")
            else:
                lines.append(f"[dim]{old_no:>4} {new_no:>4}   {escaped}[/dim]")
    return "\n".join(lines)


def display_data_for_preview(
    preview: FileDiffPreview | None,
    *,
    tool_name: str,
    status: str,
    dim: bool = False,
) -> dict[str, object] | None:
    """Convert a preview into a display payload, if available."""
    if preview is None:
        return None
    action = {
        "Edit": "Edit",
        "Write": "Write",
    }.get(tool_name, tool_name)
    title = f"{action} {Path(preview.file_path).name}"
    return preview.to_display_data(title=title, status=status, dim=dim)
