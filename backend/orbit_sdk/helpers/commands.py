"""Pure command-configuration helpers shared by runner operations."""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping


def command_from_environment(environment: Mapping[str, str], command_env: str) -> list[str]:
    """Parse a non-empty command from one runner environment variable."""
    configured = environment.get(command_env, "").strip()
    if not configured:
        raise ValueError(f"Set {command_env} to an external tool command")
    try:
        command = json.loads(configured) if configured.startswith("[") else shlex.split(configured)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{command_env} must be a JSON string array or command") from error
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) for item in command)
        or not command[0].strip()
    ):
        raise ValueError(f"{command_env} must be a non-empty JSON string array or command")
    return command
