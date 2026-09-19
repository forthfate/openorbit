"""Shared local coding-agent command and prompt conventions."""

from __future__ import annotations

import os
import platform
import shlex
from datetime import datetime
from pathlib import Path

CODING_AGENT_PROVIDERS = ("kiro", "claude-code", "codex")


def build_coding_agent_command(provider: str, *, options: str = "", prompt: str) -> list[str]:
    """Build the established CLI invocation for a locally installed coding agent."""
    commands = {
        # ``--approve-for-me`` already selects Codex's workspace-write sandbox.
        "codex": (["codex", "exec", "--approve-for-me"], []),
        "claude-code": (["claude"], ["-p"]),
        "kiro": (["kiro-cli", "chat"], []),
    }
    if provider not in commands:
        raise ValueError("AI agent provider must be codex, claude-code, or kiro")
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ValueError("AI agent prompt must not be empty")
    try:
        extra_arguments = shlex.split(options)
    except ValueError as error:
        raise ValueError("AI agent options must be a valid command argument string") from error
    executable, prompt_arguments = commands[provider]
    return [*executable, *extra_arguments, *prompt_arguments, normalized_prompt]


def execution_environment_context(working_directory: str | Path | None = None) -> str:
    """Describe the host context in which a coding task will run."""
    shell_path = os.environ.get("COMSPEC") if os.name == "nt" else os.environ.get("SHELL")
    shell_path = shell_path or ("cmd.exe" if os.name == "nt" else "/bin/sh")
    shell_name = os.path.basename(shell_path) or shell_path
    directory = Path(working_directory).expanduser().resolve() if working_directory else Path.cwd()
    current_time = datetime.now().astimezone().isoformat(timespec="seconds")
    return (
        "Execution environment:\n"
        f"- OS: {platform.system()} {platform.release()}\n"
        f"- Default shell: {shell_name} ({shell_path})\n"
        f"- Current working directory: {directory}\n"
        f"- Current local time: {current_time}\n"
    )


def build_coding_agent_prompt(task: str, working_directory: str | Path) -> str:
    """Wrap an Assistant task in the shared system context understood by all CLIs."""
    return (
        "You are the coding agent used by Orbit Assistant.\n"
        "Work only in the current working directory. Inspect and validate changes where appropriate.\n"
        + execution_environment_context(working_directory)
        + "\nUser task:\n"
        + task.strip()
    )
