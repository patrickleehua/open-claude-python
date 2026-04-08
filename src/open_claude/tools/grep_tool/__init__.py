"""GrepTool - content search using ripgrep (name: 'Grep')."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError
from open_claude.tools.shared.utils import expand_path, to_relative_path

DEFAULT_HEAD_LIMIT = 250
MAX_COLUMNS = 500

# VCS directories to exclude
VCS_EXCLUDES = [".git", ".svn", ".hg", ".bzr", ".jj", ".sl"]


class GrepToolInput(BaseModel):
    """Input schema for GrepTool."""

    pattern: str = Field(
        description="The regular expression pattern to search for in file contents"
    )
    path: str | None = Field(
        default=None,
        description="File or directory to search in. Defaults to CWD.",
    )
    glob: str | None = Field(
        default=None,
        description='Glob pattern to filter files (e.g. "*.js", "*.{ts,tsx}")',
    )
    output_mode: str = Field(
        default="files_with_matches",
        description="Output mode: 'content', 'files_with_matches', or 'count'",
    )
    context: int | None = Field(
        default=None,
        ge=0,
        description="Number of lines before and after each match",
    )
    case_insensitive: bool | None = Field(
        default=None,
        description="Case insensitive search",
    )
    type: str | None = Field(
        default=None,
        description='File type to search (e.g. "js", "py", "rust")',
    )
    head_limit: int | None = Field(
        default=DEFAULT_HEAD_LIMIT,
        description="Limit number of output entries. Default 250. Use 0 for unlimited.",
    )
    multiline: bool | None = Field(
        default=None,
        description="Enable multiline mode where . matches newlines",
    )


class GrepTool(Tool):
    """A powerful search tool built on ripgrep."""

    @property
    def name(self) -> str:
        return "Grep"

    @property
    def aliases(self) -> list[str]:
        return ["Search"]

    @property
    def input_schema(self) -> type[BaseModel]:
        return GrepToolInput

    @property
    def description(self) -> str:
        return (
            "A powerful search tool built on ripgrep\n"
            "\n"
            "  Usage:\n"
            "  - ALWAYS use Grep for search tasks. NEVER invoke `grep` or `rg` as a Bash command. "
            "The Grep tool has been optimized for correct permissions and access.\n"
            '  - Supports full regex syntax (e.g., "log.*Error", "function\\s+\\w+")\n'
            '  - Filter files with glob parameter (e.g., "*.js", "**/*.tsx") or type parameter '
            '(e.g., "js", "py", "rust")\n'
            '  - Output modes: "content" shows matching lines, "files_with_matches" shows only '
            'file paths (default), "count" shows match counts\n'
            "  - Use Agent tool for open-ended searches requiring multiple rounds\n"
            "  - Pattern syntax: Uses ripgrep (not grep) - literal braces need escaping "
            "(use `interface\\{\\}` to find `interface{}` in Go code)\n"
            "  - Multiline matching: By default patterns match within single lines only. For "
            "cross-line patterns like `struct \\{[\\s\\S]*?field`, use `multiline: true`"
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return True

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: GrepToolInput

        # Resolve search path
        if data.path:
            search_path = expand_path(data.path)
            if not search_path.exists():
                raise ToolError(
                    f"Path not found: {search_path}. "
                    f"Use a valid file or directory path."
                )
        else:
            search_path = Path.cwd()

        # Try ripgrep first, fall back to Python implementation
        if shutil.which("rg"):
            return await self._grep_ripgrep(data, search_path)
        return await self._grep_python(data, search_path)

    async def _grep_ripgrep(self, data: GrepToolInput, search_path: Path) -> str:
        """Search using ripgrep binary."""
        args: list[str] = [
            "--hidden",
            "--max-columns", str(MAX_COLUMNS),
        ]

        # Exclude VCS directories
        for vcs_dir in VCS_EXCLUDES:
            args.extend(["--glob", f"!{vcs_dir}"])

        # Multiline
        if data.multiline:
            args.extend(["-U", "--multiline-dotall"])

        # Case insensitive
        if data.case_insensitive:
            args.append("-i")

        # Output mode
        if data.output_mode == "files_with_matches":
            args.append("-l")
        elif data.output_mode == "count":
            args.append("-c")

        # Context (content mode)
        if data.context is not None and data.output_mode == "content":
            args.extend(["-C", str(data.context)])

        # Line numbers in content mode
        if data.output_mode == "content":
            args.append("-n")

        # Type filter
        if data.type:
            args.extend(["--type", data.type])

        # Glob filter
        if data.glob:
            args.extend(["--glob", data.glob])

        # Pattern (use -e to handle patterns starting with -)
        args.extend(["-e", data.pattern])

        # Search path
        args.append(str(search_path))

        proc = await asyncio.create_subprocess_exec(
            "rg",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        # rg returns exit code 1 when no matches found
        if proc.returncode == 1:
            return "No matches found."
        if proc.returncode and proc.returncode > 1:
            error_msg = stderr.strip() or f"ripgrep exited with code {proc.returncode}"
            raise ToolError(f"ripgrep error: {error_msg}")

        if not stdout.strip():
            return "No matches found."

        return self._format_output(data, stdout, search_path)

    async def _grep_python(self, data: GrepToolInput, search_path: Path) -> str:
        """Fallback search using Python re module."""
        try:
            flags = re.MULTILINE
            if data.case_insensitive:
                flags |= re.IGNORECASE
            pattern = re.compile(data.pattern, flags)
        except re.error as exc:
            raise ToolError(f"Invalid regex pattern: {exc}")

        results: list[tuple[Path, list[str]]] = []
        files_to_search = self._collect_files(search_path, data.glob)

        for file_path in files_to_search:
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            if data.output_mode == "files_with_matches":
                if pattern.search(content):
                    results.append((file_path, []))
            elif data.output_mode == "count":
                count = len(pattern.findall(content))
                if count > 0:
                    results.append((file_path, [str(count)]))
            else:  # content mode
                matching_lines: list[str] = []
                for i, line in enumerate(content.split("\n")):
                    if pattern.search(line):
                        rel = to_relative_path(file_path, search_path)
                        matching_lines.append(f"{rel}:{i + 1}:{line.rstrip()}")
                if matching_lines:
                    results.append((file_path, matching_lines))

        if not results:
            return "No matches found."

        return self._format_python_output(data, results, search_path)

    def _collect_files(self, search_path: Path, glob_pattern: str | None) -> list[Path]:
        """Collect files to search, respecting glob filter."""
        if search_path.is_file():
            return [search_path]

        files: list[Path] = []
        for p in search_path.rglob("*"):
            if not p.is_file():
                continue
            # Skip VCS directories
            if any(part in VCS_EXCLUDES for part in p.parts):
                continue
            # Apply glob filter
            if glob_pattern:
                if not fnmatch.fnmatch(p.name, glob_pattern):
                    continue
            files.append(p)
        return files

    def _format_output(self, data: GrepToolInput, stdout: str, base_path: Path) -> str:
        """Format ripgrep output for the model."""
        if data.output_mode == "files_with_matches":
            lines = stdout.strip().split("\n")
            lines = [ln for ln in lines if ln.strip()]

            # Sort by mtime (newest first)
            path_lines: list[tuple[float, str]] = []
            for line in lines:
                try:
                    p = Path(line)
                    mtime = os.path.getmtime(p) if p.exists() else 0.0
                except OSError:
                    mtime = 0.0
                rel = to_relative_path(Path(line), base_path)
                path_lines.append((mtime, rel))
            path_lines.sort(key=lambda x: x[0], reverse=True)

            # Apply head_limit
            limit = (
                data.head_limit
                if data.head_limit and data.head_limit > 0
                else len(path_lines)
            )
            path_lines = path_lines[:limit]

            filenames = [pl[1] for pl in path_lines]
            return f"Found {len(filenames)} file(s)\n" + "\n".join(filenames)

        if data.output_mode == "count":
            return stdout.strip()

        # Content mode - relativize paths
        lines = stdout.strip().split("\n")
        limit = (
            data.head_limit if data.head_limit and data.head_limit > 0 else len(lines)
        )
        lines = lines[:limit]
        return "\n".join(lines)

    def _format_python_output(
        self,
        data: GrepToolInput,
        results: list[tuple[Path, list[str]]],
        base_path: Path,
    ) -> str:
        """Format Python fallback output."""
        if data.output_mode == "files_with_matches":
            filenames = [to_relative_path(p, base_path) for p, _ in results]
            return f"Found {len(filenames)} file(s)\n" + "\n".join(filenames)

        if data.output_mode == "count":
            parts = []
            for path, lines in results:
                rel = to_relative_path(path, base_path)
                parts.append(f"{rel}:{lines[0]}")
            return "\n".join(parts)

        # Content mode
        all_lines: list[str] = []
        for _, lines in results:
            all_lines.extend(lines)
        limit = (
            data.head_limit if data.head_limit and data.head_limit > 0 else len(all_lines)
        )
        all_lines = all_lines[:limit]
        return "\n".join(all_lines)
