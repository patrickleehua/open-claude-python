"""Environment variable expansion in MCP server configurations.

Supports ``${VAR}`` and ``${VAR:-default}`` syntax in config values
(command, args, env, url, headers).
"""

from __future__ import annotations

import os
import re
from typing import Any

# Matches ${VAR} or ${VAR:-default}
_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def expand_env_vars(value: str) -> tuple[str, list[str]]:
    """Expand environment variables in a string value.

    Returns:
        A tuple of (expanded_string, list_of_missing_var_names).
    """
    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        content = match.group(1)
        # Split on first :-  for default value syntax
        var_name, _, default = content.partition(":-")
        env_value = os.environ.get(var_name)
        if env_value is not None:
            return env_value
        if default:
            return default
        missing.append(var_name)
        return match.group(0)  # keep original if not found and no default

    expanded = _ENV_VAR_RE.sub(_replace, value)
    return expanded, missing


def expand_config_env(config: dict[str, Any]) -> dict[str, Any]:
    """Expand environment variables in an MCP server config dict.

    Expands values in: ``command``, ``args``, ``env``, ``url``, ``headers``.
    Returns a new dict with expanded values.
    """
    result = dict(config)

    # Expand command (stdio)
    if "command" in result and isinstance(result["command"], str):
        result["command"], _ = expand_env_vars(result["command"])

    # Expand args (stdio)
    if "args" in result and isinstance(result["args"], list):
        result["args"] = [
            expand_env_vars(a)[0] if isinstance(a, str) else a for a in result["args"]
        ]

    # Expand env values (stdio)
    if "env" in result and isinstance(result["env"], dict):
        expanded_env: dict[str, str] = {}
        for k, v in result["env"].items():
            if isinstance(v, str):
                expanded_env[k], _ = expand_env_vars(v)
            else:
                expanded_env[k] = v
        result["env"] = expanded_env

    # Expand url (sse/http)
    if "url" in result and isinstance(result["url"], str):
        result["url"], _ = expand_env_vars(result["url"])

    # Expand header values (sse/http)
    if "headers" in result and isinstance(result["headers"], dict):
        expanded_headers: dict[str, str] = {}
        for k, v in result["headers"].items():
            if isinstance(v, str):
                expanded_headers[k], _ = expand_env_vars(v)
            else:
                expanded_headers[k] = v
        result["headers"] = expanded_headers

    return result
