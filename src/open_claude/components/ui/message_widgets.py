"""Chat message widgets — minimal Claude Code CLI style."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.timer import Timer
from textual.widgets import Markdown, Static


class UserMessage(Static):
    """Displays a user prompt with > prefix."""

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(f"[bold cyan]>[/bold cyan] {text}", **kwargs)


class AssistantLoadingIndicator(Static):
    """Animated pending-response indicator."""

    DEFAULT_CSS = """
    AssistantLoadingIndicator {
        height: auto;
        color: $text-disabled;
        margin: 0 0 1 0;
    }
    """

    _DOT_FRAMES = [
        "○",
        "●",
    ]
    _GLOW_WIDTH = 6

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._frame_index = 0
        self._glow_position = -8.0
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.22, self._tick)
        self._refresh_display()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self._frame_index = (self._frame_index + 1) % len(self._DOT_FRAMES)
        self._glow_position += 0.55
        if self._glow_position > 24:
            self._glow_position = -8.0
        self._refresh_display()

    def _refresh_display(self) -> None:
        self.update(
            "[white]"
            f"{self._DOT_FRAMES[self._frame_index]}  {self._render_glowing_word()}[/white]"
        )

    def _render_glowing_word(self) -> str:
        word = "Clauding"
        chars: list[str] = []
        for idx, char in enumerate(word):
            distance = abs(idx - self._glow_position)
            if distance < 0.45:
                chars.append(f"[bold white]{char}[/bold white]")
            elif distance < 1.1:
                chars.append(f"[white]{char}[/white]")
            elif distance < 2.0:
                chars.append(f"[grey70]{char}[/grey70]")
            elif distance < self._GLOW_WIDTH:
                chars.append(f"[grey50]{char}[/grey50]")
            else:
                chars.append(f"[grey35]{char}[/grey35]")
        return "".join(chars)


class ThinkingSection(Static):
    """Thinking panel with explicit collapsed state."""

    DEFAULT_CSS = """
    ThinkingSection {
        height: auto;
        color: $text-disabled;
        margin: 0 0 0 0;
    }
    """

    def __init__(self, streaming: bool = True, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.collapsed = True
        self._streaming = streaming
        self._text = ""
        self._display = ""

    def on_mount(self) -> None:
        self._refresh_display()

    def toggle(self) -> None:
        self.collapsed = not self.collapsed
        self._refresh_display()

    def update_thinking(self, text: str, streaming: bool) -> None:
        self._text = text
        self._streaming = streaming
        self._refresh_display()

    def render(self) -> str:
        return self._display

    def _refresh_display(self) -> None:
        title = "Thinking..." if self._streaming else "Thought"
        state = "collapsed" if self.collapsed else "expanded"
        body = "" if self.collapsed else f"\n\n{self._text}"
        self._display = f"{title} [{state}]{body}"
        self.update(self._display)


class ToolSummarySection(Static):
    """Collapsed tool summary with optional expanded details."""

    DEFAULT_CSS = """
    ToolSummarySection {
        height: auto;
        color: $text-muted;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.collapsed = True
        self._display = ""
        self._items: list[dict] = []

    def on_mount(self) -> None:
        self._refresh_display()

    def render(self) -> str:
        return self._display

    def toggle(self) -> None:
        self.collapsed = not self.collapsed
        self._refresh_display()

    def add_tool_use(self, tool_call_id: str, tool_name: str, tool_input: dict | None) -> None:
        self._items.append({
            "id": tool_call_id,
            "name": tool_name,
            "input": tool_input or {},
            "output": None,
            "is_error": False,
            "display_data": None,
        })
        self._refresh_display()

    def set_tool_result(
        self,
        tool_call_id: str,
        output: str,
        is_error: bool,
        display_data: dict | None = None,
    ) -> None:
        for item in self._items:
            if item["id"] == tool_call_id:
                item["output"] = output
                item["is_error"] = is_error
                item["display_data"] = display_data
                break
        self._refresh_display()

    def has_items(self) -> bool:
        return bool(self._items)

    def _refresh_display(self) -> None:
        if not self._items:
            self._display = ""
        else:
            summary = self._build_summary()
            details = self._build_details()
            self._display = summary if self.collapsed or not details else f"{summary}\n\n{details}"
        self.update(self._display)

    def _build_summary(self) -> str:
        grep_count = sum(1 for item in self._items if item["name"] == "Grep")
        glob_count = sum(1 for item in self._items if item["name"] == "Glob")
        read_count = sum(1 for item in self._items if item["name"] == "Read")

        parts: list[str] = []
        if grep_count:
            parts.append(f"Searched for {grep_count} pattern{'s' if grep_count != 1 else ''}")
        if glob_count:
            parts.append(f"matched {glob_count} file pattern{'s' if glob_count != 1 else ''}")
        if read_count:
            parts.append(f"read {read_count} file{'s' if read_count != 1 else ''}")

        if not parts:
            parts.append(f"Used {len(self._items)} tool{'s' if len(self._items) != 1 else ''}")

        return f"{', '.join(parts)} (ctrl+o to expand)"

    def _build_details(self) -> str:
        lines: list[str] = []
        for item in self._items:
            lines.extend(self._build_item_details(item))
        return "\n".join(line for line in lines if line)

    def _build_item_details(self, item: dict) -> list[str]:
        name = item["name"]
        input_data = item["input"]
        output = item["output"]
        is_error = item["is_error"]
        display_data = item.get("display_data")

        if isinstance(display_data, dict) and display_data.get("kind") == "file_diff":
            title = str(display_data.get("title") or name)
            status = str(display_data.get("status") or ("failed" if is_error else "applied"))
            markup = str(display_data.get("markup") or "")
            summary = self._format_diff_summary(display_data)
            return [f"● {title} [{status}]", f"  {summary}", *markup.splitlines()]

        if is_error:
            return [f"● {name} failed"]

        if name == "Grep":
            pattern = input_data.get("pattern", "")
            result_lines = [line for line in (output or "").splitlines() if line.strip()]
            if result_lines and result_lines[0] == "No matches found.":
                return [f"● Search(pattern: {pattern!r})", "  No matches found"]
            file_lines = [line for line in result_lines if ":" in line or "/" in line or "\\" in line]
            detail = file_lines[:8] if file_lines else result_lines[:8]
            return [f"● Search(pattern: {pattern!r})"] + [f"  {line}" for line in detail]

        if name == "Glob":
            pattern = input_data.get("pattern", "")
            result_lines = [line for line in (output or "").splitlines() if line.strip()]
            files = result_lines[1:] if result_lines and result_lines[0].startswith("Found ") else result_lines
            return [f"● Glob(pattern: {pattern!r})"] + [f"  {line}" for line in files[:8]]

        if name == "Read":
            path = input_data.get("file_path", "")
            line_count = self._count_read_lines(output or "")
            return [f"● Read({path})", f"  Read {line_count} lines"]

        return [f"● {name}"]

    def _count_read_lines(self, output: str) -> int:
        lines = [line for line in output.splitlines() if line.strip()]
        if lines and lines[-1].startswith("(total ") and " lines)" in lines[-1]:
            lines = lines[:-1]
        return len(lines)

    def _format_diff_summary(self, display_data: dict) -> str:
        additions = int(display_data.get("additions", 0) or 0)
        removals = int(display_data.get("removals", 0) or 0)
        parts: list[str] = []
        if additions:
            parts.append(f"Added {additions} line{'s' if additions != 1 else ''}")
        if removals:
            parts.append(f"Removed {removals} line{'s' if removals != 1 else ''}")
        return ", ".join(parts) if parts else "No line changes"


class AssistantMessage(Container):
    """Container: optional thinking + markdown response."""

    DEFAULT_CSS = """
    AssistantMessage {
        height: auto;
        margin: 0 0 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield AssistantLoadingIndicator(id="assistant-loading")
        yield Markdown()

    def on_resize(self, event) -> None:
        """Auto-scroll chat area when content grows during streaming."""
        try:
            app = self.app
            if getattr(app, "_is_streaming", False):
                app._scroll_chat_to_end()
        except Exception:
            pass

    def update_text(self, text: str) -> None:
        self._stop_loading()
        self.query_one(Markdown).update(text)

    async def set_thinking(self, text: str, streaming: bool) -> None:
        self._stop_loading()
        section = self._get_thinking_section()
        if section is None:
            section = ThinkingSection(streaming=streaming, id="thinking-section")
            md = self.query_one(Markdown)
            await self.mount(section, before=md)
        section.update_thinking(text, streaming)

    async def add_tool_use(self, tool_call_id: str, tool_name: str, tool_input: dict | None) -> None:
        self._stop_loading()
        section = await self._ensure_tool_summary_section()
        section.add_tool_use(tool_call_id, tool_name, tool_input)

    async def set_tool_result(
        self,
        tool_call_id: str,
        output: str,
        is_error: bool,
        display_data: dict | None = None,
    ) -> None:
        self._stop_loading()
        section = await self._ensure_tool_summary_section()
        section.set_tool_result(tool_call_id, output, is_error, display_data)

    def toggle_thinking(self) -> bool:
        toggled = False
        section = self._get_thinking_section()
        if section is not None:
            section.toggle()
            toggled = True
        tool_section = self._get_tool_summary_section()
        if tool_section is not None and tool_section.has_items():
            tool_section.toggle()
            toggled = True
        return toggled

    def _get_thinking_section(self) -> ThinkingSection | None:
        try:
            return self.query_one("#thinking-section", ThinkingSection)
        except Exception:
            return None

    def _get_tool_summary_section(self) -> ToolSummarySection | None:
        try:
            return self.query_one("#tool-summary-section", ToolSummarySection)
        except Exception:
            return None

    async def _ensure_tool_summary_section(self) -> ToolSummarySection:
        section = self._get_tool_summary_section()
        if section is None:
            section = ToolSummarySection(id="tool-summary-section")
            md = self.query_one(Markdown)
            await self.mount(section, before=md)
        return section

    def _stop_loading(self) -> None:
        try:
            loading = self.query_one("#assistant-loading", AssistantLoadingIndicator)
        except Exception:
            return
        loading.stop()
        loading.display = False

    def finalize_pending_state(self) -> None:
        self._stop_loading()
