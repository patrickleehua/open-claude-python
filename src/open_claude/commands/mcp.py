"""/mcp command — manage MCP servers from the chat session."""

from __future__ import annotations

import json
import shlex

from open_claude.commands.base import CommandResult, CommandResultType, LocalCommand
from open_claude.services.mcp import (
    ConfigScope,
    McpConfigLoader,
    McpHTTPServerConfig,
    McpSSEServerConfig,
    McpStdioServerConfig,
    add_mcp_config,
    add_mcp_json_config,
    connect_mcp_servers,
    get_mcp_config,
    disconnect_mcp_servers,
    get_mcp_manager,
    reset_project_mcp_choices,
    remove_mcp_config,
    set_mcp_server_disabled,
)
from open_claude.services.mcp.auth import get_mcp_client_secret, save_mcp_client_secret
from open_claude.services.mcp.types import ConnectedMcpServer, FailedMcpServer, NeedsAuthMcpServer
from open_claude.utils.claude_desktop import find_claude_desktop_config_path, import_claude_desktop_mcp_servers


class McpCommand(LocalCommand):
    name = "mcp"
    description = "Manage MCP servers and refresh MCP tools"
    argument_hint = "[list|get|add|add-json|enable|disable|reconnect|remove|connect|disconnect|status]"

    async def execute(self, args: str, context) -> CommandResult:  # type: ignore[override]
        argv = shlex.split(args)
        action = argv[0] if argv else "status"
        rest = argv[1:] if argv else []

        if action in {"status", "list"}:
            return await self._list_servers()
        if action == "connect":
            await connect_mcp_servers()
            await context.refresh_tools()
            return await self._list_servers(prefix="[green]MCP servers connected.[/green]")
        if action == "disconnect":
            await disconnect_mcp_servers()
            await context.refresh_tools()
            return CommandResult(
                type=CommandResultType.TEXT,
                value="[yellow]Disconnected all MCP servers and removed MCP tools from the active tool pool.[/yellow]",
            )
        if action == "reconnect":
            await disconnect_mcp_servers()
            await connect_mcp_servers()
            await context.refresh_tools()
            target = rest[0] if rest else None
            prefix = "[green]MCP servers reconnected.[/green]"
            if target:
                prefix = f"[green]Reconnected '{target}' via full MCP reconnect.[/green]"
            return await self._list_servers(prefix=prefix)
        if action == "enable":
            return await self._set_enabled(rest, context, enabled=True)
        if action == "disable":
            return await self._set_enabled(rest, context, enabled=False)
        if action == "reset-project-choices":
            reset_project_mcp_choices()
            await disconnect_mcp_servers()
            await context.refresh_tools()
            return CommandResult(
                type=CommandResultType.TEXT,
                value="[green]Reset all project-scoped MCP approval and rejection choices.[/green]",
            )
        if action == "get":
            return self._get_server(rest)
        if action == "add":
            return await self._add_server(rest, context)
        if action == "add-json":
            return await self._add_json_server(rest, context)
        if action == "add-from-claude-desktop":
            return await self._add_from_claude_desktop(rest, context)
        if action in {"remove", "rm", "delete"}:
            return await self._remove_server(rest, context)

        return CommandResult(
            type=CommandResultType.TEXT,
            value=self._usage(f"Unknown subcommand: {action}"),
        )

    async def _list_servers(self, prefix: str | None = None) -> CommandResult:
        loader = McpConfigLoader()
        configs = loader.get_all_configs(include_disabled=True)
        manager = get_mcp_manager()
        connections = manager.connections

        lines: list[str] = []
        if prefix:
            lines.append(prefix)
            lines.append("")
        lines.append("[bold]MCP servers:[/bold]")

        if not configs:
            lines.append("  [dim]No MCP servers configured.[/dim]")
            lines.append("")
            lines.append(self._usage())
            return CommandResult(type=CommandResultType.TEXT, value="\n".join(lines))

        discovered_tools = await manager.discover_all_tools() if getattr(manager, "_connected", False) else []
        tool_counts: dict[str, int] = {}
        for tool in discovered_tools:
            server_name = tool.get("server_name")
            if isinstance(server_name, str):
                tool_counts[server_name] = tool_counts.get(server_name, 0) + 1

        for name in sorted(configs):
            scoped = configs[name]
            config = scoped.config
            connection = connections.get(name)
            status = "disabled" if loader.is_server_disabled(name) else "configured"
            if isinstance(connection, ConnectedMcpServer):
                status = "connected"
            elif isinstance(connection, NeedsAuthMcpServer):
                status = "needs-auth"
            elif isinstance(connection, FailedMcpServer):
                status = f"failed: {connection.error}"

            location = getattr(config, "url", None) or getattr(config, "command", "")
            tool_info = ""
            if tool_counts.get(name):
                tool_info = f" tools={tool_counts[name]}"
            lines.append(
                f"  [cyan]{name}[/cyan]  type={config.type}  scope={scoped.scope.value}  status={status}{tool_info}"
            )
            if location:
                lines.append(f"    {location}")

        lines.append("")
        lines.append(self._usage())
        return CommandResult(type=CommandResultType.TEXT, value="\n".join(lines))

    async def _set_enabled(self, argv: list[str], context, enabled: bool) -> CommandResult:
        if not argv:
            verb = "enable" if enabled else "disable"
            return CommandResult(type=CommandResultType.TEXT, value=self._usage(f"Usage error: /mcp {verb} requires a server name"))

        name = argv[0]
        if name == "all":
            for server_name in McpConfigLoader().get_all_configs(include_disabled=True):
                set_mcp_server_disabled(server_name, not enabled)
        else:
            set_mcp_server_disabled(name, not enabled)
        await disconnect_mcp_servers()
        await connect_mcp_servers()
        await context.refresh_tools()
        color = "green" if enabled else "yellow"
        action = "Enabled" if enabled else "Disabled"
        subject = "all MCP servers" if name == "all" else f"MCP server '{name}'"
        return await self._list_servers(prefix=f"[{color}]{action} {subject}.[/{color}]")

    def _get_server(self, argv: list[str]) -> CommandResult:
        if not argv:
            return CommandResult(type=CommandResultType.TEXT, value=self._usage("Usage error: /mcp get requires a server name"))

        name = argv[0]
        scoped = get_mcp_config(name)
        if scoped is None:
            return CommandResult(
                type=CommandResultType.TEXT,
                value=f"[yellow]No MCP server found with name: {name}[/yellow]",
            )

        config = scoped.config
        lines = [
            f"[bold]{name}[/bold]",
            f"  Scope: {scoped.scope.value}",
            f"  Type: {config.type}",
        ]
        if hasattr(config, "url"):
            lines.append(f"  URL: {config.url}")
        if hasattr(config, "command"):
            lines.append(f"  Command: {config.command}")
        if getattr(config, "args", None):
            lines.append(f"  Args: {' '.join(config.args)}")
        if getattr(config, "env", None):
            lines.append("  Environment:")
            for key, value in config.env.items():
                lines.append(f"    {key}={value}")
        if getattr(config, "headers", None):
            lines.append("  Headers:")
            for key, value in config.headers.items():
                lines.append(f"    {key}: {value}")
        if getattr(config, "oauth", None):
            oauth_parts: list[str] = []
            if config.oauth.client_id:
                oauth_parts.append("client_id configured")
            if config.oauth.callback_port:
                oauth_parts.append(f"callback_port {config.oauth.callback_port}")
            if get_mcp_client_secret(name):
                oauth_parts.append("client_secret configured")
            if oauth_parts:
                lines.append(f"  OAuth: {', '.join(oauth_parts)}")
        return CommandResult(type=CommandResultType.TEXT, value="\n".join(lines))

    async def _add_server(self, argv: list[str], context) -> CommandResult:
        scope, transport, remaining = self._parse_common_flags(argv)
        if len(remaining) < 2:
            return CommandResult(type=CommandResultType.TEXT, value=self._usage("Usage error: /mcp add requires a name and target"))

        name = remaining[0]
        target = remaining[1]
        extra = remaining[2:]
        try:
            env = self._parse_env_pairs(self._take_repeated_flag(argv, "--env"))
            headers = self._parse_header_pairs(self._take_repeated_flag(argv, "--header"))
            client_id = self._take_single_flag(argv, "--client-id")
            callback_port_raw = self._take_single_flag(argv, "--callback-port")
            client_secret = self._take_single_flag(argv, "--client-secret")
            callback_port = int(callback_port_raw) if callback_port_raw else None
            oauth = self._build_oauth_config(client_id, callback_port)
        except ValueError as exc:
            return CommandResult(type=CommandResultType.TEXT, value=f"[yellow]{exc}[/yellow]")

        if transport == "stdio":
            config = McpStdioServerConfig(command=target, args=extra, env=env or None)
        elif transport == "sse":
            config = McpSSEServerConfig(url=target, headers=headers or None, oauth=oauth)
        elif transport == "http":
            config = McpHTTPServerConfig(url=target, headers=headers or None, oauth=oauth)
        else:
            return CommandResult(type=CommandResultType.TEXT, value=self._usage(f"Unsupported transport: {transport}"))

        add_mcp_config(name, config, scope=scope)
        if client_secret and transport in {"sse", "http"}:
            save_mcp_client_secret(name, client_secret)
        await disconnect_mcp_servers()
        await connect_mcp_servers()
        await context.refresh_tools()
        return await self._list_servers(prefix=f"[green]Added MCP server '{name}'.[/green]")

    async def _add_json_server(self, argv: list[str], context) -> CommandResult:
        scope = ConfigScope.PROJECT
        client_secret = None
        filtered: list[str] = []
        i = 0
        while i < len(argv):
            token = argv[i]
            if token == "--scope" and i + 1 < len(argv):
                scope = ConfigScope(argv[i + 1])
                i += 2
                continue
            if token == "--client-secret" and i + 1 < len(argv):
                client_secret = argv[i + 1]
                i += 2
                continue
            filtered.append(token)
            i += 1

        if len(filtered) < 2:
            return CommandResult(type=CommandResultType.TEXT, value=self._usage("Usage error: /mcp add-json requires a name and JSON payload"))

        name = filtered[0]
        raw_json = " ".join(filtered[1:])
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            return CommandResult(
                type=CommandResultType.TEXT,
                value=f"[yellow]Invalid JSON: {exc}[/yellow]",
            )

        config = add_mcp_json_config(name, parsed, scope=scope)
        if client_secret and config.type in {"sse", "http"}:
            save_mcp_client_secret(name, client_secret)
        await disconnect_mcp_servers()
        await connect_mcp_servers()
        await context.refresh_tools()
        return await self._list_servers(prefix=f"[green]Added MCP server '{name}' from JSON.[/green]")

    async def _add_from_claude_desktop(self, argv: list[str], context) -> CommandResult:
        scope = ConfigScope.PROJECT
        if argv[:2] and argv[0] == "--scope":
            scope = ConfigScope(argv[1])

        config_path = find_claude_desktop_config_path()
        if config_path is None:
            return CommandResult(
                type=CommandResultType.TEXT,
                value="[yellow]Claude Desktop config not found.[/yellow]",
            )

        imported = import_claude_desktop_mcp_servers(scope)
        if not imported:
            return CommandResult(
                type=CommandResultType.TEXT,
                value=f"[yellow]No valid MCP servers found in {config_path}.[/yellow]",
            )

        await disconnect_mcp_servers()
        await connect_mcp_servers()
        await context.refresh_tools()
        return await self._list_servers(
            prefix=f"[green]Imported {len(imported)} MCP server(s) from Claude Desktop.[/green]"
        )

    async def _remove_server(self, argv: list[str], context) -> CommandResult:
        scope, _, remaining = self._parse_common_flags(argv)
        if not remaining:
            return CommandResult(type=CommandResultType.TEXT, value=self._usage("Usage error: /mcp remove requires a server name"))

        name = remaining[0]
        remove_mcp_config(name, scope=scope)
        await disconnect_mcp_servers()
        await connect_mcp_servers()
        await context.refresh_tools()
        return await self._list_servers(prefix=f"[green]Removed MCP server '{name}' from {scope.value} scope.[/green]")

    def _parse_common_flags(self, argv: list[str]) -> tuple[ConfigScope, str, list[str]]:
        scope = ConfigScope.PROJECT
        transport = "stdio"
        remaining: list[str] = []
        i = 0
        while i < len(argv):
            token = argv[i]
            if token == "--scope" and i + 1 < len(argv):
                scope = ConfigScope(argv[i + 1])
                i += 2
                continue
            if token == "--transport" and i + 1 < len(argv):
                transport = argv[i + 1]
                i += 2
                continue
            if token in {"--env", "--header", "--client-id", "--callback-port", "--client-secret"} and i + 1 < len(argv):
                i += 2
                continue
            remaining.append(token)
            i += 1
        return scope, transport, remaining

    def _usage(self, error: str | None = None) -> str:
        lines: list[str] = []
        if error:
            lines.append(f"[yellow]{error}[/yellow]")
            lines.append("")
        lines.extend(
            [
                "[dim]Examples:[/dim]",
                "  /mcp list",
                "  /mcp get context7",
                "  /mcp connect",
                "  /mcp reconnect",
                "  /mcp reconnect context7",
                "  /mcp disable context7",
                "  /mcp disable all",
                "  /mcp enable context7",
                "  /mcp enable all",
                "  /mcp add filesystem npx -y @modelcontextprotocol/server-filesystem .",
                "  /mcp add --transport http --header 'Authorization: Bearer token' context7 https://mcp.context7.com/mcp",
                "  /mcp add-json context7 '{\"type\":\"http\",\"url\":\"https://mcp.context7.com/mcp\"}'",
                "  /mcp add-from-claude-desktop",
                "  /mcp add --transport sse docs https://example.com/sse",
                "  /mcp remove filesystem",
            ]
        )
        return "\n".join(lines)

    def _take_repeated_flag(self, argv: list[str], flag: str) -> list[str]:
        result: list[str] = []
        i = 0
        while i < len(argv):
            if argv[i] == flag and i + 1 < len(argv):
                result.append(argv[i + 1])
                i += 2
                continue
            i += 1
        return result

    def _take_single_flag(self, argv: list[str], flag: str) -> str | None:
        values = self._take_repeated_flag(argv, flag)
        return values[-1] if values else None

    def _parse_env_pairs(self, values: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in values:
            if "=" not in item:
                raise ValueError(f"Invalid env entry: {item}")
            key, value = item.split("=", 1)
            key = key.strip()
            if not key:
                raise ValueError(f"Invalid env entry: {item}")
            result[key] = value
        return result

    def _parse_header_pairs(self, values: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in values:
            if ":" not in item:
                raise ValueError(f"Invalid header entry: {item}")
            key, value = item.split(":", 1)
            key = key.strip()
            if not key:
                raise ValueError(f"Invalid header entry: {item}")
            result[key] = value.strip()
        return result

    def _build_oauth_config(self, client_id: str | None, callback_port: int | None) -> dict[str, object] | None:
        if not client_id and callback_port is None:
            return None
        oauth: dict[str, object] = {}
        if client_id:
            oauth["client_id"] = client_id
        if callback_port is not None:
            oauth["callback_port"] = callback_port
        return oauth
