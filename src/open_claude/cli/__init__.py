"""CLI entry point for open-claude-python using Typer."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console
from rich.table import Table

try:
    from open_claude.constants import APP_NAME, APP_VERSION, DEFAULT_MODEL
except ImportError:
    APP_NAME = "open-claude-python"
    APP_VERSION = "0.1.0"
    DEFAULT_MODEL = "claude-sonnet-4-20250514"

app = typer.Typer(
    name=APP_NAME,
    help="Python implementation of Claude Code CLI.",
    no_args_is_help=False,
    add_completion=False,
    rich_markup_mode="rich",
)
memory_app = typer.Typer(
    name="memory",
    help="Inspect and manage memory files.",
    no_args_is_help=False,
)
mcp_app = typer.Typer(
    name="mcp",
    help="Manage MCP server configuration and connectivity.",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model",
        "-m",
        help="Model to use for conversations.",
    ),
    system_prompt: str | None = typer.Option(
        None,
        "--system-prompt",
        "-s",
        help="Custom system prompt.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output.",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        "-r",
        help="Resume previous conversation.",
    ),
) -> None:
    """Start an interactive Claude Code session."""
    if ctx.invoked_subcommand is not None:
        return

    from open_claude.components.ui import ChatApp

    ChatApp(model=model, system_prompt=system_prompt).run()


@app.command()
def chat(
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model",
        "-m",
        help="Model to use.",
    ),
    system_prompt: str | None = typer.Option(
        None,
        "--system-prompt",
        "-s",
        help="Custom system prompt.",
    ),
) -> None:
    """Start an interactive chat session."""
    from open_claude.components.ui import ChatApp

    ChatApp(model=model, system_prompt=system_prompt).run()


@app.command()
def config() -> None:
    """Display current configuration."""
    from open_claude.cli.handlers import show_config

    show_config()


@app.command()
def version() -> None:
    """Show version information."""
    console = Console()
    console.print(f"[bold cyan]{APP_NAME}[/bold cyan] v{APP_VERSION}")


@app.command()
def models() -> None:
    """List available models."""
    console = Console()

    table = Table(
        title="Available Models",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Model ID", style="cyan")
    table.add_column("Description")

    table.add_row("claude-sonnet-4-20250514", "Claude Sonnet 4 (default)")
    table.add_row("claude-opus-4-20250514", "Claude Opus 4")
    table.add_row("claude-haiku-4-20250514", "Claude Haiku 4")

    console.print(table)


@memory_app.callback(invoke_without_command=True)
def memory_main(ctx: typer.Context) -> None:
    """List memory files by default."""
    if ctx.invoked_subcommand is not None:
        return
    memory_list()


@memory_app.command("status")
def memory_status() -> None:
    """Show memory status."""
    from open_claude.services.session_memory import (
        get_session_memory_config,
        get_session_memory_path,
        is_session_memory_initialized,
    )
    from open_claude.utils.memory.paths import get_memory_dir, get_memory_entrypoint, is_auto_memory_enabled

    console = Console()
    config = get_session_memory_config()
    session_path = get_session_memory_path()
    console.print("[bold]Memory Status[/bold]")
    console.print(f"  Auto memory enabled: {'yes' if is_auto_memory_enabled() else 'no'}")
    console.print(f"  Auto memory dir: {get_memory_dir()}")
    console.print(f"  Auto memory entrypoint: {get_memory_entrypoint()}")
    console.print(f"  Session memory path: {session_path}")
    console.print(f"  Session memory initialized: {'yes' if is_session_memory_initialized() else 'no'}")
    console.print(f"  Session memory file exists: {'yes' if session_path.exists() else 'no'}")
    console.print(f"  minimum_message_tokens_to_init={config.minimum_message_tokens_to_init}")
    console.print(f"  minimum_tokens_between_update={config.minimum_tokens_between_update}")
    console.print(f"  tool_calls_between_updates={config.tool_calls_between_updates}")


@memory_app.command("path")
def memory_path() -> None:
    """Show memory paths."""
    from open_claude.services.session_memory import get_session_memory_path
    from open_claude.utils.memory.paths import get_memory_dir, get_memory_entrypoint

    console = Console()
    console.print(f"Auto memory dir: {get_memory_dir()}")
    console.print(f"Auto memory entrypoint: {get_memory_entrypoint()}")
    console.print(f"Session memory path: {get_session_memory_path()}")


@memory_app.command("list")
def memory_list() -> None:
    """List memory files."""
    from open_claude.commands.memory import MemoryCommand

    class _MemoryCliContext:
        messages: list[dict] = []
        model_name = DEFAULT_MODEL
        token_usage = None
        permission_context = None

        def clear_conversation(self) -> None:
            return None

        def compact_conversation(self, instructions: str = ""):
            return None

        def load_settings(self) -> dict:
            return {}

        def set_permission_mode(self, mode) -> None:
            return None

        async def refresh_tools(self) -> None:
            return None

    async def _run() -> str:
        command = MemoryCommand()
        result = await command.execute("", _MemoryCliContext())
        return result.value

    Console().print(asyncio.run(_run()))


@memory_app.command("show")
def memory_show(
    target: str = typer.Argument("session", help="session, auto, or a memory markdown filename"),
) -> None:
    """Show memory file content."""
    from open_claude.commands.memory import MemoryCommand

    async def _run() -> str:
        command = MemoryCommand()
        result = await command._show([target])
        return result.value

    Console().print(asyncio.run(_run()))


@memory_app.command("open")
def memory_open(
    target: str = typer.Argument("session", help="session, auto, or a memory markdown filename"),
) -> None:
    """Open a memory file in the configured editor."""
    from open_claude.commands.memory import MemoryCommand

    async def _run() -> str:
        command = MemoryCommand()
        result = await command._open([target])
        return result.value

    Console().print(asyncio.run(_run()))


@memory_app.command("init")
def memory_init() -> None:
    """Initialize memory files."""
    from open_claude.services.session_memory import setup_session_memory_file
    from open_claude.utils.memory.memdir import ensure_memory_dir_exists
    from open_claude.utils.memory.paths import get_memory_dir, get_memory_entrypoint

    async def _run() -> tuple[str, str]:
        auto_dir = get_memory_dir()
        auto_entrypoint = get_memory_entrypoint()
        await ensure_memory_dir_exists(auto_dir)
        if not auto_entrypoint.exists():
            auto_entrypoint.parent.mkdir(parents=True, exist_ok=True)
            auto_entrypoint.write_text("", encoding="utf-8")
        session_path, _ = await setup_session_memory_file()
        return str(auto_entrypoint), session_path

    auto_entrypoint, session_path = asyncio.run(_run())
    console = Console()
    console.print("[green]Initialized memory files.[/green]")
    console.print(f"Auto memory: {auto_entrypoint}")
    console.print(f"Session memory: {session_path}")


@mcp_app.command("list")
def mcp_list() -> None:
    """List configured MCP servers."""
    from open_claude.services.mcp import McpConfigLoader

    console = Console()
    loader = McpConfigLoader()
    configs = loader.get_all_configs(include_disabled=True)

    if not configs:
        console.print("[dim]No MCP servers configured.[/dim]")
        return

    table = Table(title="MCP Servers", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan")
    table.add_column("Type")
    table.add_column("Scope")
    table.add_column("Status")
    table.add_column("Target")

    for name in sorted(configs):
        scoped = configs[name]
        config = scoped.config
        target = getattr(config, "url", None) or getattr(config, "command", "")
        status = "disabled" if loader.is_server_disabled(name) else "enabled"
        table.add_row(name, config.type, scoped.scope.value, status, target)

    console.print(table)


@mcp_app.command(
    "add",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def mcp_add(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Server name."),
    target: str = typer.Argument(..., help="Command for stdio, or URL for sse/http."),
    extra: list[str] | None = typer.Argument(None, help="Extra stdio args."),
    transport: str = typer.Option("stdio", "--transport", help="stdio, sse, or http."),
    scope: str = typer.Option("project", "--scope", help="project or user."),
    env: list[str] | None = typer.Option(None, "--env", "-e", help="Environment variables for stdio servers, KEY=value."),
    header: list[str] | None = typer.Option(None, "--header", "-H", help="Headers for HTTP/SSE servers, 'Name: Value'."),
    client_id: str | None = typer.Option(None, "--client-id", help="OAuth client ID for HTTP/SSE servers."),
    callback_port: int | None = typer.Option(None, "--callback-port", help="Fixed OAuth callback port."),
    client_secret: str | None = typer.Option(None, "--client-secret", help="OAuth client secret for HTTP/SSE servers."),
) -> None:
    """Add an MCP server config."""
    from open_claude.services.mcp import ConfigScope, McpHTTPServerConfig, McpSSEServerConfig, McpStdioServerConfig, add_mcp_config
    from open_claude.services.mcp.auth import save_mcp_client_secret

    passthrough_args = list(extra or [])
    passthrough_args.extend(ctx.args)
    parsed_env = _parse_env_pairs(env or [])
    parsed_headers = _parse_header_pairs(header or [])
    oauth = _build_oauth_config(client_id, callback_port)

    if transport == "stdio":
        config = McpStdioServerConfig(command=target, args=passthrough_args, env=parsed_env or None)
    elif transport == "sse":
        config = McpSSEServerConfig(url=target, headers=parsed_headers or None, oauth=oauth)
    elif transport == "http":
        config = McpHTTPServerConfig(url=target, headers=parsed_headers or None, oauth=oauth)
    else:
        raise typer.BadParameter("transport must be one of: stdio, sse, http")

    add_mcp_config(name, config, scope=ConfigScope(scope))
    if client_secret and transport in {"sse", "http"}:
        save_mcp_client_secret(name, client_secret)
    Console().print(f"[green]Added MCP server '{name}' ({transport}, scope={scope}).[/green]")


@mcp_app.command("get")
def mcp_get(
    name: str = typer.Argument(..., help="Server name."),
) -> None:
    """Show one MCP server config in detail."""
    from open_claude.services.mcp import get_mcp_config
    from open_claude.services.mcp.auth import get_mcp_client_secret

    server = get_mcp_config(name)
    if server is None:
        raise typer.BadParameter(f"No MCP server found with name: {name}")

    config = server.config
    console = Console()
    console.print(f"[bold]{name}[/bold]")
    console.print(f"  Scope: {server.scope.value}")
    console.print(f"  Type: {config.type}")
    if hasattr(config, "url"):
        console.print(f"  URL: {config.url}")
    if hasattr(config, "command"):
        console.print(f"  Command: {config.command}")
    if getattr(config, "args", None):
        console.print(f"  Args: {' '.join(config.args)}")
    if getattr(config, "env", None):
        console.print("  Environment:")
        for key, value in config.env.items():
            console.print(f"    {key}={value}")
    if getattr(config, "headers", None):
        console.print("  Headers:")
        for key, value in config.headers.items():
            console.print(f"    {key}: {value}")
    if getattr(config, "oauth", None):
        oauth_parts: list[str] = []
        if config.oauth.client_id:
            oauth_parts.append("client_id configured")
        if config.oauth.callback_port:
            oauth_parts.append(f"callback_port {config.oauth.callback_port}")
        if get_mcp_client_secret(name):
            oauth_parts.append("client_secret configured")
        if oauth_parts:
            console.print(f"  OAuth: {', '.join(oauth_parts)}")


@mcp_app.command("add-json")
def mcp_add_json(
    name: str = typer.Argument(..., help="Server name."),
    raw_json: str = typer.Argument(..., help="JSON object describing the MCP server."),
    scope: str = typer.Option("project", "--scope", help="project or user."),
    client_secret: str | None = typer.Option(None, "--client-secret", help="OAuth client secret for HTTP/SSE servers."),
) -> None:
    """Add an MCP server from a raw JSON config."""
    from open_claude.services.mcp import ConfigScope, add_mcp_json_config
    from open_claude.services.mcp.auth import save_mcp_client_secret

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON: {exc}") from exc

    config = add_mcp_json_config(name, parsed, scope=ConfigScope(scope))
    if client_secret and config.type in {"sse", "http"}:
        save_mcp_client_secret(name, client_secret)
    Console().print(f"[green]Added MCP server '{name}' from JSON ({config.type}, scope={scope}).[/green]")


@mcp_app.command("remove")
def mcp_remove(
    name: str = typer.Argument(..., help="Server name."),
    scope: str = typer.Option("project", "--scope", help="project or user."),
) -> None:
    """Remove an MCP server config."""
    from open_claude.services.mcp import ConfigScope, remove_mcp_config

    remove_mcp_config(name, scope=ConfigScope(scope))
    Console().print(f"[green]Removed MCP server '{name}' from {scope} scope.[/green]")


@mcp_app.command("enable")
def mcp_enable(
    name: str = typer.Argument(..., help="Server name."),
) -> None:
    """Enable a previously disabled MCP server."""
    from open_claude.services.mcp import set_mcp_server_disabled

    from open_claude.services.mcp import McpConfigLoader

    if name == "all":
        for server_name in McpConfigLoader().get_all_configs(include_disabled=True):
            set_mcp_server_disabled(server_name, False)
        Console().print("[green]Enabled all MCP servers.[/green]")
        return

    set_mcp_server_disabled(name, False)
    Console().print(f"[green]Enabled MCP server '{name}'.[/green]")


@mcp_app.command("disable")
def mcp_disable(
    name: str = typer.Argument(..., help="Server name."),
) -> None:
    """Disable an MCP server."""
    from open_claude.services.mcp import set_mcp_server_disabled

    from open_claude.services.mcp import McpConfigLoader

    if name == "all":
        for server_name in McpConfigLoader().get_all_configs(include_disabled=True):
            set_mcp_server_disabled(server_name, True)
        Console().print("[yellow]Disabled all MCP servers.[/yellow]")
        return

    set_mcp_server_disabled(name, True)
    Console().print(f"[yellow]Disabled MCP server '{name}'.[/yellow]")


@mcp_app.command("reconnect")
def mcp_reconnect(
    name: str | None = typer.Argument(None, help="Optional server name."),
) -> None:
    """Reconnect MCP servers and print connection status."""
    from open_claude.services.mcp import disconnect_mcp_servers

    asyncio.run(disconnect_mcp_servers())
    if name:
        Console().print(f"[dim]Reconnecting '{name}' via full MCP reconnect.[/dim]")
    mcp_connect()


@mcp_app.command("reset-project-choices")
def mcp_reset_project_choices() -> None:
    """Reset stored project MCP approval/disable choices."""
    from open_claude.services.mcp import reset_project_mcp_choices

    reset_project_mcp_choices()
    Console().print("[green]Reset all project-scoped MCP approval and rejection choices.[/green]")


@mcp_app.command("add-from-claude-desktop")
def mcp_add_from_claude_desktop(
    scope: str = typer.Option("project", "--scope", help="project or user."),
) -> None:
    """Import MCP servers from Claude Desktop config."""
    from open_claude.services.mcp import ConfigScope
    from open_claude.utils.claude_desktop import find_claude_desktop_config_path, import_claude_desktop_mcp_servers

    config_path = find_claude_desktop_config_path()
    if config_path is None:
        Console().print("[yellow]Claude Desktop config not found.[/yellow]")
        return

    imported = import_claude_desktop_mcp_servers(ConfigScope(scope))
    if not imported:
        Console().print(f"[yellow]No valid MCP servers found in {config_path}.[/yellow]")
        return

    Console().print(f"[green]Imported {len(imported)} MCP server(s) from {config_path} into {scope} scope.[/green]")
    for name, config in sorted(imported.items()):
        target = getattr(config, "url", None) or getattr(config, "command", "")
        Console().print(f"  {name}: {config.type} {target}")


@mcp_app.command("connect")
def mcp_connect() -> None:
    """Connect to configured MCP servers and print connection status."""
    from open_claude.services.mcp import connect_mcp_servers, disconnect_mcp_servers, get_mcp_manager
    from open_claude.services.mcp.types import ConnectedMcpServer, FailedMcpServer, NeedsAuthMcpServer

    async def _probe_connections() -> list[str]:
        await connect_mcp_servers()
        try:
            lines: list[str] = []
            for name, connection in sorted(get_mcp_manager().connections.items()):
                if isinstance(connection, ConnectedMcpServer):
                    lines.append(f"[green]{name}: connected[/green]")
                elif isinstance(connection, NeedsAuthMcpServer):
                    lines.append(f"[yellow]{name}: needs-auth[/yellow]")
                elif isinstance(connection, FailedMcpServer):
                    lines.append(f"[red]{name}: failed - {connection.error}[/red]")
                else:
                    lines.append(f"{name}: {type(connection).__name__}")
            return lines
        finally:
            await disconnect_mcp_servers()

    console = Console()
    for line in asyncio.run(_probe_connections()):
        console.print(line)


@mcp_app.command("disconnect")
def mcp_disconnect() -> None:
    """Disconnect all MCP servers."""
    from open_claude.services.mcp import disconnect_mcp_servers

    asyncio.run(disconnect_mcp_servers())
    Console().print("[yellow]Disconnected all MCP servers.[/yellow]")


app.add_typer(mcp_app, name="mcp")
app.add_typer(memory_app, name="memory")


def _parse_env_pairs(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise typer.BadParameter(f"Invalid env entry: {item}. Expected KEY=value.")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter(f"Invalid env entry: {item}. Key cannot be empty.")
        result[key] = value
    return result


def _parse_header_pairs(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        if ":" not in item:
            raise typer.BadParameter(f"Invalid header entry: {item}. Expected 'Name: Value'.")
        key, value = item.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise typer.BadParameter(f"Invalid header entry: {item}. Header name cannot be empty.")
        result[key] = value
    return result


def _build_oauth_config(client_id: str | None, callback_port: int | None) -> dict[str, object] | None:
    if not client_id and callback_port is None:
        return None
    oauth: dict[str, object] = {}
    if client_id:
        oauth["client_id"] = client_id
    if callback_port is not None:
        oauth["callback_port"] = callback_port
    return oauth
