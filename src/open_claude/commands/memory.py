"""/memory command — inspect and manage memory files."""

from __future__ import annotations

import os
from pathlib import Path

from open_claude.commands.base import CommandResult, CommandResultType, LocalCommand
from open_claude.services.api import ClientConfig, get_client
from open_claude.services.settings import load_settings
from open_claude.services.session_memory import (
    get_session_memory_config,
    get_session_memory_content,
    get_session_memory_path,
    is_session_memory_initialized,
    manually_extract_session_memory,
    setup_session_memory_file,
)
from open_claude.utils.editor import open_file_in_editor
from open_claude.utils.memory.memdir import ENTRYPOINT_NAME, ensure_memory_dir_exists
from open_claude.utils.memory.paths import get_memory_dir, get_memory_entrypoint, is_auto_memory_enabled
from open_claude.utils.memory.scanner import scan_memory_files


class MemoryCommand(LocalCommand):
    name = "memory"
    description = "Edit Claude memory files"
    argument_hint = "[status|path|list|show|open|init|extract|<target>|<index>]"

    async def execute(self, args: str, context) -> CommandResult:  # type: ignore[override]
        parts = args.strip().split()
        action = parts[0] if parts else "status"
        rest = parts[1:] if parts else []

        if not parts:
            return await self._list()
        if action == "status":
            return await self._status()
        if action == "path":
            return self._path()
        if action == "list":
            return await self._list()
        if action == "show":
            return await self._show(rest)
        if action == "open":
            return await self._open(rest)
        if action == "init":
            return await self._init()
        if action == "extract":
            return await self._extract(context)
        if not rest:
            return await self._open([action])

        return CommandResult(
            type=CommandResultType.TEXT,
            value=self._usage(f"Unknown subcommand: {action}"),
        )

    async def _status(self) -> CommandResult:
        session_content = await get_session_memory_content()
        session_path = get_session_memory_path()
        auto_dir = get_memory_dir()
        auto_entrypoint = get_memory_entrypoint()
        config = get_session_memory_config()

        lines = [
            "[bold]Memory Status[/bold]",
            f"  Auto memory enabled: {'yes' if is_auto_memory_enabled() else 'no'}",
            f"  Auto memory dir: {auto_dir}",
            f"  Auto memory entrypoint: {auto_entrypoint}",
            f"  Session memory path: {session_path}",
            f"  Session memory initialized: {'yes' if is_session_memory_initialized() else 'no'}",
            f"  Session memory file exists: {'yes' if session_path.exists() else 'no'}",
            f"  Session memory has content: {'yes' if bool(session_content and session_content.strip()) else 'no'}",
            "  Session memory config:",
            f"    minimum_message_tokens_to_init={config.minimum_message_tokens_to_init}",
            f"    minimum_tokens_between_update={config.minimum_tokens_between_update}",
            f"    tool_calls_between_updates={config.tool_calls_between_updates}",
            "",
            self._usage(),
        ]
        return CommandResult(type=CommandResultType.TEXT, value="\n".join(lines))

    def _path(self) -> CommandResult:
        auto_dir = get_memory_dir()
        auto_entrypoint = get_memory_entrypoint()
        session_path = get_session_memory_path()
        lines = [
            "[bold]Memory Paths[/bold]",
            f"  Auto memory dir: {auto_dir}",
            f"  Auto memory entrypoint: {auto_entrypoint}",
            f"  Session memory path: {session_path}",
        ]
        return CommandResult(type=CommandResultType.TEXT, value="\n".join(lines))

    async def _list(self) -> CommandResult:
        auto_dir = get_memory_dir()
        await ensure_memory_dir_exists(auto_dir)
        files = await scan_memory_files(auto_dir)
        options = self._build_memory_options(files)
        lines = [
            "[bold]Memory Files[/bold]",
            f"  1. Session memory -> {self._get_relative_memory_path(get_session_memory_path())}",
            f"  2. Auto memory -> {self._get_relative_memory_path(get_memory_entrypoint())}",
        ]
        if len(options) > 2:
            lines.append("  Saved memory files:")
            for index, label, description in options[2:]:
                suffix = f" — {description}" if description else ""
                lines.append(f"  {index}. {label}{suffix}")
        else:
            lines.append("  [dim]No saved memory topic files yet.[/dim]")
        lines.append("")
        lines.append("[dim]Use `/memory open <name>` or `/memory <index>` to edit a file.[/dim]")
        lines.append("")
        lines.append(self._usage())
        return CommandResult(type=CommandResultType.TEXT, value="\n".join(lines))

    async def _show(self, rest: list[str]) -> CommandResult:
        target = rest[0] if rest else "session"
        try:
            path = await self._resolve_target_path(target)
        except ValueError as exc:
            return CommandResult(type=CommandResultType.TEXT, value=self._usage(str(exc)))

        if target == "session":
            content = await get_session_memory_content()
        else:
            content = await self._read_text(path)

        if not content:
            return CommandResult(
                type=CommandResultType.TEXT,
                value=f"[yellow]{target} memory file is empty or not initialized.[/yellow]\nPath: {path}",
            )

        return CommandResult(
            type=CommandResultType.TEXT,
            value=f"[bold]{target.title()} Memory[/bold]\nPath: {path}\n\n{content}",
        )

    async def _open(self, rest: list[str]) -> CommandResult:
        target = rest[0] if rest else "session"
        try:
            path = await self._resolve_target_path(target, create_if_missing=True)
            source = open_file_in_editor(path)
        except Exception as exc:
            return CommandResult(
                type=CommandResultType.TEXT,
                value=f"[yellow]Failed to open memory file: {exc}[/yellow]",
            )

        editor_hint = (
            f'Using ${source}="{os.environ.get(source, "")}".'
            if source in {"VISUAL", "EDITOR"}
            else "To use a different editor, set the $EDITOR or $VISUAL environment variable."
        )
        return CommandResult(
            type=CommandResultType.TEXT,
            value=(
                f"[green]Opened memory file at {self._get_relative_memory_path(path)}[/green]\n\n"
                f"> {editor_hint}"
            ),
        )

    async def _init(self) -> CommandResult:
        auto_dir = get_memory_dir()
        auto_entrypoint = get_memory_entrypoint()
        await ensure_memory_dir_exists(auto_dir)
        if not auto_entrypoint.exists():
            auto_entrypoint.parent.mkdir(parents=True, exist_ok=True)
            auto_entrypoint.write_text("", encoding="utf-8")

        session_path, _ = await setup_session_memory_file()
        return CommandResult(
            type=CommandResultType.TEXT,
            value=(
                "[green]Initialized memory files.[/green]\n"
                f"Auto memory: {auto_entrypoint}\n"
                f"Session memory: {session_path}"
            ),
        )

    async def _extract(self, context) -> CommandResult:
        if not context.messages:
            return CommandResult(type=CommandResultType.TEXT, value="[yellow]No messages to summarize.[/yellow]")

        settings = load_settings()
        client = get_client(ClientConfig(api_key=settings.api_key, api_url=settings.base_url))

        async def llm_call_fn(*, system: str, messages: list[dict]) -> str:
            response = await client.messages.create(
                model=context.model_name,
                max_tokens=4096,
                system=system,
                messages=messages,
            )
            parts: list[str] = []
            for block in response.content:
                text = getattr(block, "text", None)
                if text:
                    parts.append(text)
            return "".join(parts)

        result = await manually_extract_session_memory(
            context.messages,
            llm_call_fn=llm_call_fn,
        )
        await client.close()

        if not result.success:
            return CommandResult(
                type=CommandResultType.TEXT,
                value=f"[yellow]Session memory extraction failed: {result.error}[/yellow]",
            )

        return CommandResult(
            type=CommandResultType.TEXT,
            value=f"[green]Session memory extracted.[/green]\nPath: {result.memory_path}",
        )

    async def _read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError, OSError):
            return None

    async def _resolve_target_path(self, target: str, create_if_missing: bool = False) -> Path:
        auto_dir = get_memory_dir()
        await ensure_memory_dir_exists(auto_dir)
        resolved_index = await self._resolve_index_target(target, auto_dir)
        if resolved_index is not None:
            target = resolved_index

        if target == "session":
            path = get_session_memory_path()
            if create_if_missing:
                await setup_session_memory_file()
            return path
        if target == "auto":
            path = get_memory_entrypoint()
            if create_if_missing and not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            return path

        path = auto_dir / target
        if path.suffix != ".md":
            path = path.with_suffix(".md")
        try:
            path.relative_to(auto_dir)
        except ValueError as exc:
            raise ValueError("Usage error: /memory target must stay inside the memory directory") from exc
        if create_if_missing and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        if not path.exists():
            raise ValueError(f"Usage error: memory file not found: {target}")
        return path

    async def _resolve_index_target(self, target: str, auto_dir: Path) -> str | None:
        if not target.isdigit():
            return None
        index = int(target)
        options = self._build_memory_options(await scan_memory_files(auto_dir))
        for option_index, option_target, _description in options:
            if option_index == index:
                return option_target
        raise ValueError(f"Usage error: memory file index not found: {target}")

    def _build_memory_options(self, files) -> list[tuple[int, str, str]]:
        options: list[tuple[int, str, str]] = [
            (1, "session", "Saved in ~/.claude/session-memory/session.md"),
            (2, "auto", "Saved in the project auto-memory entrypoint"),
        ]
        for offset, item in enumerate(files, start=3):
            options.append((offset, item.filename, item.description or ""))
        return options

    def _get_relative_memory_path(self, path: str | Path) -> str:
        path_str = str(Path(path))
        home_dir = str(Path.home())
        cwd = os.getcwd()
        relative_to_home = f"~{path_str[len(home_dir):]}" if path_str.startswith(home_dir) else None
        relative_to_cwd = f"./{os.path.relpath(path_str, cwd)}" if path_str.startswith(cwd) else None
        if relative_to_home and relative_to_cwd:
            return relative_to_home if len(relative_to_home) <= len(relative_to_cwd) else relative_to_cwd
        return relative_to_home or relative_to_cwd or path_str

    def _usage(self, error: str | None = None) -> str:
        lines: list[str] = []
        if error:
            lines.append(f"[yellow]{error}[/yellow]")
            lines.append("")
        lines.extend(
            [
                "[dim]Examples:[/dim]",
                "  /memory",
                "  /memory status",
                "  /memory path",
                "  /memory list",
                "  /memory init",
                f"  /memory show session",
                f"  /memory show auto",
                "  /memory show feedback_testing.md",
                "  /memory 1",
                "  /memory open session",
                "  /memory open auto",
                "  /memory open feedback_testing.md",
                "  /memory extract",
            ]
        )
        return "\n".join(lines)
