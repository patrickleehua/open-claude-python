"""Configuration display handler."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from open_claude.constants import APP_NAME, APP_VERSION, DEFAULT_MODEL, DEFAULT_MAX_TOKENS
from open_claude.services.settings import load_settings


def show_config() -> None:
    """Display current configuration."""
    console = Console()
    settings = load_settings()

    table = Table(title=f"{APP_NAME} Configuration", show_header=True, header_style="bold cyan")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Version", APP_VERSION)
    table.add_row("Default Model", DEFAULT_MODEL)
    table.add_row("Active Model", settings.model or DEFAULT_MODEL)
    table.add_row("Max Tokens", str(DEFAULT_MAX_TOKENS))
    table.add_row("API Key Set", "Yes" if settings.api_key else "No")
    table.add_row("Base URL", settings.base_url or "https://api.anthropic.com")

    console.print(table)
