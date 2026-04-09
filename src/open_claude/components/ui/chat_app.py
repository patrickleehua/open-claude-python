"""Textual TUI chat application — minimal style matching Claude Code CLI."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Key, MouseDown, Paste
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

try:
    from textual.worker import NoActiveWorker, get_current_worker
except ImportError:
    NoActiveWorker = RuntimeError

    def get_current_worker():
        raise NoActiveWorker

from open_claude.components.ui.message_widgets import (
    AssistantMessage,
    UserMessage,
)
from open_claude.utils.diff import display_data_for_preview, preview_for_tool_input

try:
    from open_claude.commands import get_registry
    from open_claude.commands.base import CommandResultType
    from open_claude.constants import APP_NAME, APP_VERSION, CLI_NAME, DEFAULT_MODEL, SYSTEM_PROMPT_DEFAULT
    from open_claude.context.prompt_builder import PromptAssembly, build_prompt_assembly
    from open_claude.query import QueryEngine
    from open_claude.query.message_builder import build_user_message
    from open_claude.query.types import ContentBlock
    from open_claude.schemas import ToolResult
    from open_claude.schemas.permissions import PermissionAskDecision, PermissionMode, ToolPermissionContext
    from open_claude.services.api import ClientConfig, get_client
    from open_claude.services.settings import load_settings
    from open_claude.tools import create_tool_executor, get_all_tools_async, get_builtin_tools
    from open_claude.utils.message_queue_manager import (
        QueuedCommand,
        dequeue,
        drain_pending_task_notifications,
        enqueue,
        peek,
        snapshot,
    )
    from open_claude.utils.query_guard import QueryGuard
except ImportError:
    APP_NAME = "open-claude-python"
    APP_VERSION = "0.1.0"
    CLI_NAME = "claude-py"
    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    SYSTEM_PROMPT_DEFAULT = ""

class _PermissionDialog(ModalScreen[str]):
    """Transient modal used for permission approval."""

    CSS = """
    _PermissionDialog {
        align: center middle;
        background: $background 60%;
    }
    #permission-dialog {
        width: 76;
        max-width: 90%;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: round $warning;
    }
    #permission-title {
        margin: 0 0 1 0;
        color: $warning;
    }
    .permission-details {
        margin: 1 0;
        color: $text-disabled;
    }
    #permission-actions {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
    }
    #permission-actions Button {
        margin: 0 1 0 0;
    }
    """

    BINDINGS = [
        Binding("left", "focus_previous", "Previous", show=False),
        Binding("right", "focus_next", "Next", show=False),
        Binding("enter", "submit_choice", "Submit", show=False),
        Binding("space", "submit_choice", "Submit", show=False),
        Binding("escape", "deny", "Deny", show=False),
    ]

    def __init__(self, tool_name: str, message: str, details: str, mode: str) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.message = message
        self.details = details
        self.mode = mode

    def compose(self) -> ComposeResult:
        with Container(id="permission-dialog"):
            yield Static(f"Permission Required: {self.tool_name}", id="permission-title")
            yield Static(self.message)
            if self.details:
                yield Static(self.details, id="permission-tool-details", classes="permission-details")
            yield Static(f"Current mode: {self.mode}", id="permission-mode-details", classes="permission-details")
            with Horizontal(id="permission-actions"):
                yield Button("Allow Once", id="allow_once", variant="primary")
                yield Button("Allow Session", id="allow_session")
                yield Button("Deny", id="deny", variant="error")
                yield Button("Mode Auto", id="mode_auto")
                yield Button("Mode Bypass", id="mode_bypass")

    def on_mount(self) -> None:
        button = self.query_one("#allow_once")
        if isinstance(button, Button):
            button.focus()

    def _buttons(self) -> list[Button]:
        return [node for node in self.query("#permission-actions Button") if isinstance(node, Button)]

    def action_focus_previous(self) -> None:
        buttons = self._buttons()
        if not buttons:
            return
        focused = self.focused if isinstance(self.focused, Button) else buttons[0]
        try:
            index = buttons.index(focused)
        except ValueError:
            index = 0
        buttons[(index - 1) % len(buttons)].focus()

    def action_focus_next(self) -> None:
        buttons = self._buttons()
        if not buttons:
            return
        focused = self.focused if isinstance(self.focused, Button) else buttons[0]
        try:
            index = buttons.index(focused)
        except ValueError:
            index = -1
        buttons[(index + 1) % len(buttons)].focus()

    def action_submit_choice(self) -> None:
        if isinstance(self.focused, Button):
            self.dismiss(self.focused.id or "deny")

    def action_deny(self) -> None:
        self.dismiss("deny")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "deny")


class _PermissionModeDialog(ModalScreen[str]):
    """Transient modal for selecting a global permission mode."""

    CSS = """
    _PermissionModeDialog {
        align: center middle;
        background: $background 60%;
    }
    #permission-mode-dialog {
        width: 72;
        max-width: 90%;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: round $accent;
    }
    .permission-mode-option {
        margin: 0 1 0 0;
    }
    """

    BINDINGS = [
        Binding("left", "focus_previous", "Previous", show=False),
        Binding("right", "focus_next", "Next", show=False),
        Binding("enter", "submit_choice", "Submit", show=False),
        Binding("space", "submit_choice", "Submit", show=False),
        Binding("escape", "dismiss_modal", "Close", show=False),
    ]

    def __init__(self, current_mode: str) -> None:
        super().__init__()
        self.current_mode = current_mode

    def compose(self) -> ComposeResult:
        with Container(id="permission-mode-dialog"):
            yield Static("Permission Mode", id="permission-title")
            yield Static(f"Current mode: {self.current_mode}", classes="permission-details")
            with Horizontal(id="permission-actions"):
                yield Button("Default", id=PermissionMode.DEFAULT.value, classes="permission-mode-option")
                yield Button("Auto", id=PermissionMode.AUTO.value, classes="permission-mode-option")
                yield Button("Bypass", id=PermissionMode.BYPASS_PERMISSIONS.value, classes="permission-mode-option")
                yield Button("Dont Ask", id=PermissionMode.DONT_ASK.value, classes="permission-mode-option")
                yield Button("Accept Edits", id=PermissionMode.ACCEPT_EDITS.value, classes="permission-mode-option")
                yield Button("Plan", id=PermissionMode.PLAN.value, classes="permission-mode-option")

    def on_mount(self) -> None:
        current_id = self.current_mode if self.current_mode in {mode.value for mode in PermissionMode} else PermissionMode.DEFAULT.value
        for button in self._buttons():
            if button.id == current_id:
                button.focus()
                return
        buttons = self._buttons()
        if buttons:
            buttons[0].focus()

    def _buttons(self) -> list[Button]:
        return [node for node in self.query("#permission-actions Button") if isinstance(node, Button)]

    def action_focus_previous(self) -> None:
        buttons = self._buttons()
        if not buttons:
            return
        focused = self.focused if isinstance(self.focused, Button) else buttons[0]
        try:
            index = buttons.index(focused)
        except ValueError:
            index = 0
        buttons[(index - 1) % len(buttons)].focus()

    def action_focus_next(self) -> None:
        buttons = self._buttons()
        if not buttons:
            return
        focused = self.focused if isinstance(self.focused, Button) else buttons[0]
        try:
            index = buttons.index(focused)
        except ValueError:
            index = -1
        buttons[(index + 1) % len(buttons)].focus()

    def action_submit_choice(self) -> None:
        if isinstance(self.focused, Button):
            self.dismiss(self.focused.id or "")

    def action_dismiss_modal(self) -> None:
        self.dismiss("")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "")


class _ContextMenuDialog(ModalScreen[str]):
    """Simple context menu for copy / paste actions."""

    CSS = """
    _ContextMenuDialog {
        align: center middle;
        background: $background 35%;
    }
    #context-menu {
        width: 36;
        max-width: 90%;
        height: auto;
        padding: 1;
        background: $surface;
        border: round $accent;
    }
    #context-menu-title {
        margin: 0 0 1 0;
        color: $accent;
    }
    .context-menu-button {
        width: 100%;
        margin: 0 0 1 0;
    }
    .context-menu-button:last-child {
        margin: 0;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_menu", "Close", show=False),
    ]

    def __init__(self, title: str, options: list[tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._options = options

    def compose(self) -> ComposeResult:
        with Container(id="context-menu"):
            yield Static(self._title, id="context-menu-title")
            for button_id, label in self._options:
                yield Button(label, id=button_id, classes="context-menu-button")

    def on_mount(self) -> None:
        buttons = [node for node in self.query("Button") if isinstance(node, Button)]
        if buttons:
            buttons[0].focus()

    def action_dismiss_menu(self) -> None:
        self.dismiss("")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "")


class _ChatAppContext:
    """Adapts a ChatApp instance to the CommandContext protocol.

    Allows command objects to access conversation state, token usage, and
    settings without depending on Textual widgets.
    """

    def __init__(self, app: ChatApp) -> None:
        self._app = app

    @property
    def messages(self) -> list[dict]:
        return self._app._conversation

    @property
    def model_name(self) -> str:
        return self._app._model_name

    @property
    def token_usage(self):
        return getattr(self._app._engine, "token_usage", None)

    def clear_conversation(self) -> None:
        self._app._conversation.clear()

    async def compact_conversation(self, instructions: str = ""):
        """Compact conversation via the compact service."""
        from open_claude.commands.base import CommandResult, CommandResultType
        from open_claude.services.compact import execute_compact

        result = await execute_compact(
            self._app._conversation, instructions=instructions,
        )
        if result.success:
            self._app._conversation.clear()
            self._app._conversation.extend(result.compacted_messages)
        return CommandResult(
            type=CommandResultType.COMPACT,
            compacted_messages=result.compacted_messages,
            display_text=result.display_text,
        )

    def load_settings(self) -> dict:
        return load_settings().__dict__ if hasattr(load_settings(), "__dict__") else {}

    @property
    def permission_context(self) -> ToolPermissionContext:
        return self._app._permission_context

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self._app._set_permission_mode(mode)

    async def refresh_tools(self) -> None:
        await self._app._refresh_tooling()


class ChatApp(App):
    """Interactive Claude Code chat session — minimal dark CLI."""

    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }
    #chat-area {
        height: 1fr;
        min-height: 0;
        overflow-y: auto;
        scrollbar-size: 1 1;
        padding: 1 2 0 2;
    }
    #input-border {
        dock: bottom;
        height: auto;
        min-height: 3;
        padding: 0 2 1 2;
        background: $surface;
        border-top: solid $surface-lighten-1;
    }
    #permission-status {
        padding: 0 0 1 0;
        color: $text-disabled;
    }
    #command-suggestions {
        display: none;
        padding: 0 0 1 0;
        color: $text-disabled;
    }
    #command-suggestions.visible {
        display: block;
    }
    #queue-status {
        display: none;
        height: auto;
        margin: 0 0 1 0;
        padding: 1 1;
        background: $surface-lighten-1;
        border: round $surface-lighten-2;
        color: $text-disabled;
    }
    #queue-status.visible {
        display: block;
    }
    #user-input {
        width: 100%;
        background: transparent;
        border: none;
        padding: 0;
        color: $text;
    }
    #user-input:focus {
        border: none;
    }
    #user-input .input--placeholder {
        color: $text-disabled;
    }
    AssistantMessage {
        margin: 0 0 1 0;
    }
    UserMessage {
        margin: 0 0 1 0;
        color: $text;
    }
    .welcome-block {
        margin: 0 0 1 0;
        color: $text-disabled;
    }
    """

    # No Header/Footer — matches Claude Code CLI
    BINDINGS: list[Binding] = [
        Binding("ctrl+o", "toggle_thinking", "Toggle thinking", show=False),
        Binding("ctrl+shift+c", "copy_selected_text", "Copy selected text", show=False),
        Binding("shift+tab", "cycle_permission_mode", "Cycle permission mode", show=False),
        Binding("backtab", "cycle_permission_mode", "Cycle permission mode", show=False),
        Binding("pageup", "scroll_page_up", "Scroll up", show=False),
        Binding("pagedown", "scroll_page_down", "Scroll down", show=False),
        Binding("home", "scroll_home", "Scroll to top", show=False),
        Binding("end", "scroll_bottom", "Scroll to bottom", show=False),
    ]

    def __init__(
        self,
        model: str | None = None,
        system_prompt: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._override_model = model
        self._override_system_prompt = system_prompt
        self._conversation: list[dict] = []
        self._engine: QueryEngine | None = None
        self._model_name: str = DEFAULT_MODEL
        self._is_streaming = False
        self._current_assistant: AssistantMessage | None = None
        self._last_ctrl_c: float = 0
        self._auto_follow_output = True
        self._tool_defs: list[dict] | None = None
        self._tool_executor = None
        self._permission_context: ToolPermissionContext = ToolPermissionContext()
        self._query_guard = QueryGuard()
        self._active_abort_event: asyncio.Event | None = None
        self._queue_processing = False
        self._default_input_placeholder = '> Try "help" for commands'
        self._command_suggestions: list[tuple[str, str]] = []
        self._selected_command_index = 0
        self._input_history: list[str] = []
        self._history_index: int | None = None
        self._mcp_refresh_task_started = False
        self._scroll_sync_pending = False

    # ------------------------------------------------------------------ compose

    def compose(self) -> ComposeResult:
        # Keep the input focused when the user clicks empty chat-space while
        # still allowing Textual's built-in text selection on message widgets.
        yield VerticalScroll(id="chat-area", can_focus=False)
        with Static(id="input-border"):
            yield Static("", id="permission-status")
            yield Static("", id="command-suggestions")
            yield Static("", id="queue-status")
            yield Input(
                placeholder=self._default_input_placeholder,
                id="user-input",
            )

    # ---------------------------------------------------------------- lifecycle

    async def on_mount(self) -> None:
        settings = load_settings()
        self._model_name = self._override_model or settings.model or DEFAULT_MODEL

        from open_claude.utils.permissions.setup import initialize_tool_permission_context
        self._permission_context = initialize_tool_permission_context()

        try:
            perm_mode_str = settings.raw.get("permissions", {}).get("defaultMode", PermissionMode.DEFAULT.value)
            perm_mode = PermissionMode(perm_mode_str)
        except Exception:
            perm_mode = PermissionMode.DEFAULT

        allow_list = settings.raw.get("permissions", {}).get("allow", [])
        self._permission_context = initialize_tool_permission_context(
            mode=perm_mode,
            allowed_tools=allow_list,
        )

        # Initialize bundled skills
        from open_claude.skills import init_bundled_skills, get_skill_registry
        init_bundled_skills()

        # Load disk-based skills (~/.claude/skills/, .claude/skills/, .claude/commands/)
        from open_claude.skills.load_skills_dir import load_all_disk_skills
        disk_skills = await load_all_disk_skills(os.getcwd())
        registry = get_skill_registry()
        for skill in disk_skills:
            registry.register(skill)

        # Load tools FIRST so we can pass enabled_tools to prompt assembly
        await self._refresh_tooling(include_mcp=False)
        enabled_tool_names = {t.name for t in get_builtin_tools()}

        try:
            assembly = await build_prompt_assembly(
                messages=[], custom_prompt=self._override_system_prompt,
                enabled_tools=enabled_tool_names,
                skill_tool_commands=get_skill_registry().get_skill_commands_for_prompt(),
            )
        except Exception:
            assembly = PromptAssembly(
                system_prompt=self._override_system_prompt or SYSTEM_PROMPT_DEFAULT,
                system_reminder=None,
                messages=[],
            )

        client = get_client(ClientConfig(api_key=settings.api_key, api_url=settings.base_url))

        # Initialize compact service with an LLM callback
        from open_claude.services.compact import init_compact

        async def _compact_llm_call(*, system: str, messages: list[dict]) -> str:
            response = await client.messages.create(
                model=self._model_name,
                max_tokens=8096,
                system=system,
                messages=messages,
            )
            parts = []
            for block in response.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
            return "".join(parts)

        init_compact(llm_call_fn=_compact_llm_call)

        self._engine = QueryEngine(
            client,
            model=self._model_name,
            system_prompt=assembly.system_prompt,
            permission_context=self._permission_context,
            permission_handler=self._handle_permission_request,
        )
        self._conversation = list(assembly.messages)
        self._sync_permission_context_to_engine()

        chat_area = self.query_one("#chat-area", VerticalScroll)
        await chat_area.mount(Static(
            f"[bold]{APP_NAME}[/bold] v{APP_VERSION}\n"
            f"Model: {self._model_name}",
            id="welcome",
            classes="welcome-block",
        ))
        self._update_permission_status()
        self._render_queue_status()
        self._scroll_chat_to_end(force=True)

        self.query_one("#user-input", Input).focus()
        self._schedule_mcp_tool_refresh()

    # ----------------------------------------------------------- key handling

    async def on_key(self, event: Key) -> None:
        """Handle Ctrl+C: first press cancels streaming, second press exits."""
        if event.key == "ctrl+c":
            event.prevent_default()
            selected_text = self.screen.get_selected_text()
            if selected_text:
                self.copy_to_clipboard(selected_text)
                return
            now = time.monotonic()
            if self._is_streaming:
                # Cancel current streaming
                self._interrupt_current_turn()
                chat_area = self.query_one("#chat-area", VerticalScroll)
                await chat_area.mount(Static("[dim]— interrupted —[/dim]"))
                self._scroll_chat_to_end(force=True)
                self.query_one("#user-input", Input).focus()
            elif now - self._last_ctrl_c < 1.0:
                # Double Ctrl+C — exit
                self.exit()
            else:
                # First Ctrl+C while idle — show hint
                chat_area = self.query_one("#chat-area", VerticalScroll)
                await chat_area.mount(Static("[dim]Press Ctrl+C again to exit[/dim]"))
                self._scroll_chat_to_end(force=True)
            self._last_ctrl_c = now
            return

        if event.key in {"shift+tab", "backtab", "shift_tab"}:
            event.prevent_default()
            self.action_cycle_permission_mode()
            return

        input_widget = self.query_one("#user-input", Input)
        if not input_widget.has_focus:
            return

        if input_widget.cursor_position == 0 and self._handle_history_navigation(event.key, input_widget):
            event.prevent_default()
            return

        if not self._command_suggestions:
            return

        if event.key == "up":
            event.prevent_default()
            self._selected_command_index = (
                (self._selected_command_index - 1) % len(self._command_suggestions)
            )
            self._render_command_suggestions()
            return

        if event.key == "down":
            event.prevent_default()
            self._selected_command_index = (
                (self._selected_command_index + 1) % len(self._command_suggestions)
            )
            self._render_command_suggestions()
            return

        if event.key == "tab":
            event.prevent_default()
            self._apply_selected_command_suggestion()
            return

    async def on_mouse_down(self, event: MouseDown) -> None:
        if getattr(event, "button", 0) != 3:
            return

        input_widget = self.query_one("#user-input", Input)
        if self._event_targets_widget(event, input_widget):
            event.stop()
            event.prevent_default()
            await self._show_input_context_menu(input_widget)
            return

        chat_area = self._chat_area()
        if self._event_targets_widget(event, chat_area):
            selected_text = self.screen.get_selected_text()
            if selected_text:
                event.stop()
                event.prevent_default()
                await self._show_chat_context_menu(selected_text)

    def on_paste(self, event: Paste) -> None:
        input_widget = self.query_one("#user-input", Input)
        if not input_widget.has_focus:
            return
        text = getattr(event, "text", "")
        if not text:
            return
        input_widget.insert_text_at_cursor(text)
        self._update_command_suggestions(input_widget.value)
        event.stop()

    # -------------------------------------------------------------- user input

    @on(Input.Submitted)
    async def on_input(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        event.input.clear()
        self._update_command_suggestions("")
        self._history_index = None

        if not user_input:
            return

        self._record_input_history(user_input)

        chat_area = self.query_one("#chat-area", VerticalScroll)

        if self._query_guard.is_active:
            await self._enqueue_user_input(user_input)
            return

        if user_input.startswith("/"):
            await self._handle_slash_command(user_input, chat_area)
            await self._process_queue_if_ready()
            return

        await self._begin_prompt_turn(user_input)

    @on(Input.Changed)
    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_command_suggestions(event.value)

    # --------------------------------------------------------------- streaming

    @work(exclusive=True)
    async def _stream_response(self, generation: int, abort_event: asyncio.Event) -> None:
        if not self._engine:
            return

        chat_area = self.query_one("#chat-area", VerticalScroll)
        response_text = ""
        thinking_text = ""
        tool_counter = 0

        try:
            async for event in self._engine.query_with_tool_loop(
                self._conversation,
                tools=self._tool_defs,
                tool_executor=self._tool_executor,
                abort_event=abort_event,
            ):
                if not self._is_streaming:
                    break

                if event.type == "thinking" and event.content:
                    thinking_text += event.content
                    if self._current_assistant:
                        await self._current_assistant.set_thinking(thinking_text, streaming=True)

                elif event.type == "text" and event.content:
                    response_text += event.content
                    if self._current_assistant:
                        self._current_assistant.update_text(response_text)

                elif event.type == "tool_use" and isinstance(event.content, ContentBlock):
                    tool_name = event.content.name or "unknown"
                    tool_input = event.content.input or {}
                    tool_id = event.content.id or f"{tool_name}-{tool_counter}"
                    tool_counter += 1
                    if self._current_assistant:
                        await self._current_assistant.add_tool_use(tool_id, tool_name, tool_input)
                    self._scroll_chat_to_end()

                elif event.type == "tool_result" and isinstance(event.content, ToolResult):
                    tr: ToolResult = event.content
                    if self._current_assistant:
                        await self._current_assistant.set_tool_result(
                            tr.tool_call_id,
                            tr.output,
                            tr.is_error,
                            tr.display_data,
                        )
                    self._scroll_chat_to_end()

                elif event.type == "error":
                    await chat_area.mount(Static(f"[red]Error: {event.content}[/red]"))

                self._scroll_chat_to_end()

        except Exception as exc:
            await chat_area.mount(Static(f"[red]API error: {exc}[/red]"))
            if self._conversation and self._conversation[-1]["role"] == "user":
                self._conversation.pop()
        finally:
            self._is_streaming = False
            self._active_abort_event = None
            self._query_guard.end(generation)

            if self._current_assistant:
                self._current_assistant.finalize_pending_state()

            if self._current_assistant and thinking_text:
                await self._current_assistant.set_thinking(thinking_text, streaming=False)

            # The conversation is already updated by query_with_tool_loop
            # (it appends assistant + tool_result messages internally).
            # But we need to append the final assistant text/thinking if any.
            # query_with_tool_loop mutates messages in-place via normalize_messages.
            # Since we passed self._conversation, the tool messages are already appended.
            # We just need to handle the final assistant content for display purposes.
            self.query_one("#user-input", Input).focus()
            self._scroll_chat_to_end(force=True)
            await self._process_queue_if_ready()

    async def _begin_prompt_turn(
        self,
        user_input: str,
        *,
        generation: int | None = None,
        render_user_message: bool = True,
        display_text: str | None = None,
    ) -> bool:
        if generation is None:
            generation = self._query_guard.try_start()
        if generation is None:
            return False

        chat_area = self.query_one("#chat-area", VerticalScroll)

        if render_user_message:
            await chat_area.mount(UserMessage(display_text or user_input))
            self._scroll_chat_to_end(force=True)

        self._conversation.append(build_user_message(user_input))

        assistant = AssistantMessage()
        await chat_area.mount(assistant)
        self._current_assistant = assistant
        self._scroll_chat_to_end(force=True)

        self._active_abort_event = asyncio.Event()
        self._is_streaming = True
        self._stream_response(generation, self._active_abort_event)
        return True

    async def _enqueue_user_input(self, user_input: str) -> None:
        mode = "slash" if user_input.startswith("/") else "prompt"
        enqueue(QueuedCommand(value=user_input, mode=mode, rendered=False))
        self._render_queue_status()

    async def _process_queue_if_ready(self) -> None:
        if self._queue_processing:
            return

        self._queue_processing = True
        try:
            chat_area = self.query_one("#chat-area", VerticalScroll)
            while not self._query_guard.is_active:
                drain_pending_task_notifications()
                next_cmd = peek(lambda cmd: cmd.agent_id is None)
                if next_cmd is None:
                    return
                if not self._query_guard.reserve():
                    return

                cmd = dequeue(lambda cmd: cmd.agent_id is None)
                if cmd is None:
                    self._query_guard.cancel_reservation()
                    self._render_queue_status()
                    return
                self._render_queue_status()

                if cmd.mode == "slash":
                    self._query_guard.cancel_reservation()
                    await self._handle_slash_command(cmd.value, chat_area)
                    continue

                generation = self._query_guard.try_start()
                if generation is None:
                    enqueue(cmd)
                    return

                started = await self._begin_prompt_turn(
                    cmd.value,
                    generation=generation,
                    render_user_message=not cmd.rendered and cmd.mode == "prompt",
                )
                if not started:
                    enqueue(cmd)
                    self._render_queue_status()
                return
        finally:
            self._queue_processing = False

    def _interrupt_current_turn(self) -> None:
        if self._active_abort_event is not None and not self._active_abort_event.is_set():
            self._active_abort_event.set()
        self._is_streaming = False

    def _render_queue_status(self) -> None:
        if not self.is_mounted:
            return
        widget = self.query_one("#queue-status", Static)
        queued = [cmd for cmd in snapshot() if cmd.agent_id is None and cmd.mode in {"prompt", "slash"}]
        if not queued:
            widget.update("")
            widget.remove_class("visible")
            return

        head = queued[0]
        lines = [
            f"[bold]Queued {len(queued)}[/bold]  next up pops in when the current turn finishes",
            f"◉ {self._format_queue_label(head)}",
        ]
        for cmd in queued[1:4]:
            lines.append(f"○ {self._format_queue_label(cmd)}")
        if len(queued) > 4:
            lines.append(f"[dim]+{len(queued) - 4} more[/dim]")

        widget.update("\n".join(lines))
        widget.add_class("visible")

    def _format_queue_label(self, cmd: QueuedCommand) -> str:
        text = cmd.value.strip().replace("\n", " ")
        if len(text) > 72:
            text = f"{text[:69]}..."
        prefix = "/ " if cmd.mode == "slash" else ""
        return f"{prefix}{text}"

    # ------------------------------------------------------------ key actions

    async def _refresh_tooling(self, include_mcp: bool = True) -> None:
        if include_mcp:
            try:
                tools = await asyncio.wait_for(get_all_tools_async(), timeout=1.5)
            except Exception:
                tools = get_builtin_tools()
        else:
            tools = get_builtin_tools()
        self._tool_defs = [tool.get_api_definition() for tool in tools]
        self._tool_executor = create_tool_executor(tools)

        # Rebuild system prompt so enabled_tools guidance stays in sync
        await self._rebuild_system_prompt()

    def _schedule_mcp_tool_refresh(self) -> None:
        if self._mcp_refresh_task_started:
            return
        self._mcp_refresh_task_started = True
        self.run_worker(self._background_refresh_mcp_tools(), exclusive=False)

    async def _background_refresh_mcp_tools(self) -> None:
        try:
            await self._refresh_tooling(include_mcp=True)
        finally:
            self._mcp_refresh_task_started = False

    async def _rebuild_system_prompt(self) -> None:
        """Rebuild the system prompt using current enabled tool names."""
        try:
            from open_claude.skills import get_skill_registry
            enabled_tool_names = {t.name for t in get_builtin_tools()}
            assembly = await build_prompt_assembly(
                messages=[],
                custom_prompt=self._override_system_prompt,
                enabled_tools=enabled_tool_names,
                skill_tool_commands=get_skill_registry().get_skill_commands_for_prompt(),
            )
            if self._engine is not None:
                self._engine.system_prompt = assembly.system_prompt
        except Exception:
            pass

    def action_toggle_thinking(self) -> None:
        chat_area = self._chat_area()
        assistants = list(chat_area.query(AssistantMessage))
        for assistant in reversed(assistants):
            if assistant.toggle_thinking():
                self._scroll_chat_to_end(force=True)
                break

    def action_cycle_permission_mode(self) -> None:
        modes = [
            PermissionMode.DEFAULT,
            PermissionMode.AUTO,
            PermissionMode.BYPASS_PERMISSIONS,
            PermissionMode.DONT_ASK,
            PermissionMode.ACCEPT_EDITS,
            PermissionMode.PLAN,
        ]
        try:
            current_index = modes.index(self._permission_context.mode)
        except ValueError:
            current_index = 0
        next_mode = modes[(current_index + 1) % len(modes)]
        self._set_permission_mode(next_mode)

    def action_scroll_page_up(self) -> None:
        chat_area = self._chat_area()
        self._auto_follow_output = False
        chat_area.scroll_page_up(animate=False)

    def action_scroll_page_down(self) -> None:
        chat_area = self._chat_area()
        chat_area.scroll_page_down(animate=False)
        self._auto_follow_output = self._is_near_bottom()

    def action_scroll_home(self) -> None:
        chat_area = self._chat_area()
        self._auto_follow_output = False
        chat_area.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        self._scroll_chat_to_end(force=True)

    def action_copy_selected_text(self) -> None:
        selected_text = self.screen.get_selected_text()
        if selected_text:
            self.copy_to_clipboard(selected_text)

    # ---------------------------------------------------------- slash commands

    async def _handle_slash_command(self, input_text: str, chat_area: VerticalScroll) -> None:
        """Dispatch slash commands through the CommandRegistry.

        Built-in exit/version commands are handled inline; everything else
        is delegated to registered command objects.
        """
        raw = input_text.strip()
        cmd_lower = raw.lower()

        # --- hard-coded navigation commands (not in registry) ----------------
        if cmd_lower in ("/exit", "/quit", "/q"):
            self.exit()
            return
        if cmd_lower == "/version":
            await chat_area.mount(Static(f"{APP_NAME} v{APP_VERSION}"))
            self._scroll_chat_to_end(force=True)
            return
        if cmd_lower == "/model":
            await chat_area.mount(Static(f"Model: {self._model_name}"))
            self._scroll_chat_to_end(force=True)
            return
        if cmd_lower in ("/permission", "/permissions", "/perm"):
            await self._show_permission_mode_dialog()
            return

        # --- skill-based commands (e.g. /simplify, /batch, /debug) -----------
        from open_claude.skills import get_skill_registry as get_skill_reg
        skill_registry = get_skill_reg()

        # Parse skill name and args from "/skill-name args..."
        skill_part = raw[1:]  # strip leading /
        skill_name, _, skill_args = skill_part.partition(" ")
        skill_name = skill_name.strip()
        skill_args = skill_args.strip()

        skill = skill_registry.find(skill_name)
        if skill and skill.user_invocable and skill.is_enabled():
            # Skill found — render the user's slash command, then send the
            # skill prompt content as a user message so the model acts on it.
            if skill.get_prompt_for_command:
                import asyncio
                blocks = await skill.get_prompt_for_command(skill_args, {})
                text_parts = [
                    b.get("text", "") for b in blocks
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                prompt_content = "\n".join(t for t in text_parts if t)
                if prompt_content:
                    # Build metadata wrapping (matches TS formatSlashCommandLoadingMetadata)
                    metadata_lines = [
                        f"<command-message>{skill_name}</command-message>",
                        f"<command-name>/{skill_name}</command-name>",
                    ]
                    if skill_args:
                        metadata_lines.append(f"<command-args>{skill_args}</command-args>")
                    full_content = "\n".join(metadata_lines) + "\n\n" + prompt_content
                    await self._begin_prompt_turn(
                        full_content,
                        display_text=raw,
                        render_user_message=True,
                    )
                    return

        # --- registry-based commands -----------------------------------------
        registry = get_registry()
        ctx = _ChatAppContext(self)

        result = await registry.dispatch(raw, ctx)
        if result is None:
            # Not recognised — show warning
            suggestions = self._get_command_suggestions(raw)
            suffix = ""
            if suggestions:
                suffix = "\n" + "\n".join(
                    f"  {label}  {description}"
                    for label, description in suggestions
                )
            await chat_area.mount(Static(
                f"[yellow]Unknown command: {input_text}[/yellow]{suffix}"
            ))
            self._scroll_chat_to_end(force=True)
            return

        # Handle the result according to its type
        if result.type == CommandResultType.SKIP:
            return

        if result.type == CommandResultType.COMPACT:
            # compact_conversation already cleared/rebuilt messages
            if result.display_text:
                await chat_area.remove_children()
                await chat_area.mount(Static(result.display_text))
            else:
                await chat_area.remove_children()
                await chat_area.mount(Static("[dim]Conversation compacted.[/dim]"))
            self._scroll_chat_to_end(force=True)
            return

        if result.should_query and result.prompt_content:
            # PromptCommand — inject the prompt as a user message and stream
            await self._begin_prompt_turn(
                result.prompt_content,
                display_text=input_text,
            )
            return

        # Default: display the text result
        if result.value:
            # For /clear, also clear the UI
            if cmd_lower in ("/clear", "/reset", "/new"):
                await chat_area.remove_children()
            await chat_area.mount(Static(result.value))
            self._scroll_chat_to_end(force=True)

    def _chat_area(self) -> VerticalScroll:
        return self.query_one("#chat-area", VerticalScroll)

    def _sync_permission_context_to_engine(self) -> None:
        if self._engine is not None:
            self._engine.permission_context = self._permission_context

    def _set_permission_context(self, context: ToolPermissionContext) -> None:
        self._permission_context = context
        self._sync_permission_context_to_engine()
        self._update_permission_status()

    def _set_permission_mode(self, mode: PermissionMode) -> None:
        from open_claude.utils.permissions.setup import transition_permission_mode

        self._set_permission_context(transition_permission_mode(self._permission_context, mode))
 
    def _update_permission_status(self) -> None:
        if not self.is_mounted:
            return
        widget = self.query_one("#permission-status", Static)
        mode = self._permission_context.mode
        color = {
            PermissionMode.DEFAULT: "white",
            PermissionMode.AUTO: "yellow",
            PermissionMode.BYPASS_PERMISSIONS: "red",
            PermissionMode.DONT_ASK: "orange3",
            PermissionMode.ACCEPT_EDITS: "green",
            PermissionMode.PLAN: "cyan",
            PermissionMode.BUBBLE: "magenta",
        }.get(mode, "white")
        widget.update(
            f"[dim]Permissions:[/dim] [{color}][bold]{mode.value}[/bold][/{color}]  "
            "[dim]Shift+Tab cycle[/dim]"
        )

    def _format_permission_prompt(self, tool_name: str, tool_input: dict[str, Any], message: str) -> str:
        details = self._summarize_tool_input(tool_name, tool_input)
        lines = [
            f"[bold yellow]Permission required:[/bold yellow] {tool_name}",
            message,
        ]
        if details:
            lines.append(f"[dim]Details:[/dim] {details}")
        lines.append(f"[dim]Current mode:[/dim] {self._permission_context.mode.value}")
        lines.append("")
        lines.append("[dim]1.[/dim] allow once")
        lines.append("[dim]2.[/dim] allow this tool for session")
        lines.append("[dim]3.[/dim] deny")
        lines.append("[dim]4.[/dim] switch mode to auto")
        lines.append("[dim]5.[/dim] switch mode to bypassPermissions")
        return "\n".join(lines)

    def _summarize_tool_input(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        preview = preview_for_tool_input(tool_name, tool_input)
        if preview is not None:
            return display_data_for_preview(
                preview,
                tool_name=tool_name,
                status="preview",
                dim=False,
            )["markup"]  # type: ignore[index]
        if tool_name == "Bash":
            return str(tool_input.get("command", ""))
        if tool_name in {"Read", "Write", "Edit"}:
            return str(tool_input.get("file_path", ""))
        if tool_name in {"Glob", "Grep"}:
            return str(tool_input.get("pattern", ""))
        return str(tool_input)[:200]

    async def _handle_permission_request(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        permission_context: ToolPermissionContext,
        set_permission_context,
        tool_use_id: str,
        decision: PermissionAskDecision,
    ):
        preview = preview_for_tool_input(tool_name, tool_input)
        preview_display = display_data_for_preview(
            preview,
            tool_name=tool_name,
            status="preview",
            dim=False,
        )
        dialog = _PermissionDialog(
            tool_name=tool_name,
            message=decision.message,
            details=(preview_display or {}).get("markup", self._summarize_tool_input(tool_name, tool_input)),
            mode=self._permission_context.mode.value,
        )
        choice = await self._show_permission_dialog(dialog)

        from open_claude.hooks.tool_permission import create_permission_context
        from open_claude.schemas.permissions import (
            AddRulesUpdate,
            PermissionBehavior,
            PermissionRuleValue,
            PermissionUpdateDestination,
        )

        ctx = create_permission_context(
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id=tool_use_id,
            permission_context=permission_context,
            set_permission_context=self._set_permission_context,
        )

        if choice == "allow_once":
            return await ctx.handle_user_allow(
                updated_input=tool_input,
                permission_updates=[],
                decision_reason=getattr(decision, "decision_reason", None),
                display_data=preview_display,
            )
        if choice == "allow_session":
            return await ctx.handle_user_allow(
                updated_input=tool_input,
                permission_updates=[
                    AddRulesUpdate(
                        destination=PermissionUpdateDestination.SESSION,
                        rules=[PermissionRuleValue(tool_name=tool_name)],
                        behavior=PermissionBehavior.ALLOW,
                    )
                ],
                decision_reason=getattr(decision, "decision_reason", None),
                display_data=preview_display,
            )
        if choice == "mode_auto":
            self._set_permission_mode(PermissionMode.AUTO)
            return ctx.build_allow(
                updated_input=tool_input,
                decision_reason=getattr(decision, "decision_reason", None),
                display_data=preview_display,
            )
        if choice == "mode_bypass":
            self._set_permission_mode(PermissionMode.BYPASS_PERMISSIONS)
            return ctx.build_allow(
                updated_input=tool_input,
                decision_reason=getattr(decision, "decision_reason", None),
                display_data=preview_display,
            )

        from open_claude.schemas.permissions import PermissionDenyDecision

        return PermissionDenyDecision(
            message=f"User denied permission for {tool_name}.",
            decision_reason=getattr(decision, "decision_reason", None),
            display_data=display_data_for_preview(
                preview,
                tool_name=tool_name,
                status="rejected",
                dim=True,
            ),
        )

    def _record_input_history(self, user_input: str) -> None:
        if not user_input:
            return
        if not self._input_history or self._input_history[-1] != user_input:
            self._input_history.append(user_input)

    async def _show_permission_dialog(self, dialog: _PermissionDialog) -> str:
        return await self._show_permission_dialog_like(dialog)

    async def _show_permission_mode_dialog(self) -> None:
        dialog = _PermissionModeDialog(self._permission_context.mode.value)

        def _apply_mode(result: str) -> None:
            if not result:
                return
            try:
                self._set_permission_mode(PermissionMode(result))
            except ValueError:
                return

        self.push_screen(dialog, callback=_apply_mode)

    async def _show_permission_dialog_like(self, dialog: ModalScreen[str]) -> str:
        # Textual only allows wait_for_dismiss inside an active worker.
        # Slash commands run from input handlers, so fall back to the callback
        # bridge in that path and reserve wait_for_dismiss for worker contexts.
        has_active_worker = True
        try:
            get_current_worker()
        except NoActiveWorker:
            has_active_worker = False

        if has_active_worker:
            try:
                future = self.push_screen(dialog, wait_for_dismiss=True)
                return await future
            except TypeError:
                pass

        future = asyncio.get_running_loop().create_future()

        def _set_result(result: str) -> None:
            if not future.done():
                future.set_result(result)

        self.push_screen(dialog, callback=_set_result)
        return await future

    async def _show_chat_context_menu(self, selected_text: str) -> None:
        choice = await self._show_permission_dialog_like(
            _ContextMenuDialog(
                title="Chat Menu",
                options=[("copy", "Copy")],
            )
        )
        if choice == "copy" and selected_text:
            self.copy_to_clipboard(selected_text)

    async def _show_input_context_menu(self, input_widget: Input) -> None:
        has_selection = bool(input_widget.selected_text)
        has_clipboard = bool(self.clipboard)
        options = [("paste", "Paste"), ("select_all", "Select All")]
        if has_selection:
            options.insert(0, ("copy", "Copy"))
        if not has_clipboard:
            options = [option for option in options if option[0] != "paste"]
        if not options:
            return

        choice = await self._show_permission_dialog_like(
            _ContextMenuDialog(
                title="Input Menu",
                options=options,
            )
        )
        if choice == "copy":
            input_widget.action_copy()
        elif choice == "paste":
            input_widget.action_paste()
        elif choice == "select_all":
            input_widget.action_select_all()
        self._update_command_suggestions(input_widget.value)
        input_widget.focus()

    def _handle_history_navigation(self, key: str, input_widget: Input) -> bool:
        if not self._input_history:
            return False

        if key == "up":
            if self._history_index is None:
                self._history_index = len(self._input_history) - 1
            elif self._history_index > 0:
                self._history_index -= 1
            input_widget.value = self._input_history[self._history_index]
            input_widget.cursor_position = 0
            return True

        if key == "down" and self._history_index is not None:
            if self._history_index < len(self._input_history) - 1:
                self._history_index += 1
                input_widget.value = self._input_history[self._history_index]
            else:
                self._history_index = None
                input_widget.value = ""
            input_widget.cursor_position = 0
            return True

        return False

    def _get_command_suggestions(self, input_text: str) -> list[tuple[str, str]]:
        text = input_text.strip()
        if not text.startswith("/"):
            return []

        command_part = text[1:]
        if " " in command_part:
            return []

        prefix = command_part.lower()
        registry = get_registry()
        suggestions: list[tuple[str, str]] = []
        seen: set[str] = set()

        builtins = [
            ("exit", "Exit the application"),
            ("quit", "Exit the application"),
            ("q", "Exit the application"),
            ("version", "Show application version"),
            ("model", "Show current model"),
        ]

        for name, description in builtins:
            if prefix and not name.startswith(prefix):
                continue
            label = f"/{name}"
            if label not in seen:
                suggestions.append((label, description))
                seen.add(label)

        for cmd in sorted(registry.get_visible(), key=lambda item: item.name):
            names = [cmd.name, *cmd.aliases]
            matched_name = next((name for name in names if not prefix or name.lower().startswith(prefix)), None)
            if matched_name is None:
                continue
            label = f"/{matched_name}"
            if label in seen:
                continue
            suggestions.append((label, cmd.description))
            seen.add(label)

        # Include skill suggestions
        from open_claude.skills import get_skill_registry as get_skill_reg
        for skill in sorted(get_skill_reg().get_user_invocable(), key=lambda s: s.name):
            names = [skill.name, *skill.aliases]
            matched_name = next((n for n in names if not prefix or n.lower().startswith(prefix)), None)
            if matched_name is None:
                continue
            label = f"/{matched_name}"
            if label in seen:
                continue
            desc = skill.description[:80] + "..." if len(skill.description) > 80 else skill.description
            suggestions.append((label, desc))
            seen.add(label)

        return suggestions

    def _update_command_suggestions(self, input_text: str) -> None:
        self._command_suggestions = self._get_command_suggestions(input_text)
        self._selected_command_index = 0
        self._render_command_suggestions()

    def _render_command_suggestions(self) -> None:
        widget = self.query_one("#command-suggestions", Static)
        if not self._command_suggestions:
            widget.update("")
            widget.remove_class("visible")
            return

        max_visible = 8
        total = len(self._command_suggestions)
        start = 0
        if total > max_visible:
            start = max(
                0,
                min(
                    self._selected_command_index - max_visible // 2,
                    total - max_visible,
                ),
            )
        end = min(total, start + max_visible)
        visible = self._command_suggestions[start:end]

        lines = ["[dim]Commands: ↑/↓ select, Tab complete[/dim]"]
        if total > max_visible:
            lines[0] += f" [dim]({self._selected_command_index + 1}/{total})[/dim]"

        for offset, (label, description) in enumerate(visible, start=start):
            prefix = "›" if offset == self._selected_command_index else " "
            style_open = "[bold]" if offset == self._selected_command_index else ""
            style_close = "[/bold]" if offset == self._selected_command_index else ""
            lines.append(f"{prefix} {style_open}{label:<12}{style_close} {description}")
        widget.update("\n".join(lines))
        widget.add_class("visible")

    def _apply_selected_command_suggestion(self) -> None:
        if not self._command_suggestions:
            return
        label, _ = self._command_suggestions[self._selected_command_index]
        input_widget = self.query_one("#user-input", Input)
        input_widget.value = f"{label} "
        input_widget.cursor_position = len(input_widget.value)
        self._update_command_suggestions(input_widget.value)

    def _event_targets_widget(self, event: MouseDown, target: Static | Input | VerticalScroll) -> bool:
        widget = getattr(event, "widget", None)
        if widget is None:
            return False
        if widget is target:
            return True
        ancestors = getattr(widget, "ancestors_with_self", None)
        if ancestors is None:
            ancestors = getattr(widget, "ancestors", ())
        return target in ancestors

    def _is_near_bottom(self) -> bool:
        chat_area = self._chat_area()
        return (chat_area.max_scroll_y - chat_area.scroll_y) <= 2

    def _scroll_chat_to_end(self, force: bool = False) -> None:
        if force:
            self._auto_follow_output = True
        if not (force or self._auto_follow_output or self._is_near_bottom()):
            return
        if self._scroll_sync_pending:
            return
        self._scroll_sync_pending = True
        self.call_after_refresh(self._scroll_chat_to_end_after_refresh, force)

    def _scroll_chat_to_end_after_refresh(self, force: bool) -> None:
        self._scroll_sync_pending = False
        if force:
            self._auto_follow_output = True
        if force or self._auto_follow_output or self._is_near_bottom():
            self._chat_area().scroll_end(animate=False)
