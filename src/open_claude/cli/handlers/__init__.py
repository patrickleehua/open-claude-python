from .config_handler import show_config


def start_chat(**kwargs):
    """Launch the Textual TUI chat app."""
    from open_claude.components.ui import ChatApp

    ChatApp(**kwargs).run()


__all__ = ["start_chat", "show_config"]
