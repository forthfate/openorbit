"""Bounded local tools exposed to the Orbit chat assistant."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from coding_agents import CODING_AGENT_PROVIDERS, build_coding_agent_command, build_coding_agent_prompt

MAX_RESULT_BYTES = 16 * 1024
MAX_FILE_LINES = 120
MAX_SEARCH_RESULTS = 12
BLOCKED_NAMES = {".env", ".git", ".ssh", "id_rsa", "id_ed25519"}
DEFAULT_MCP_URL = "http://127.0.0.1:3000/mcp/"


def _terminal_visible() -> bool:
    """Deployment flag; terminal visibility is not an operator UI setting."""
    value = os.environ.get("ORBIT_ASSISTANT_TERMINAL_VISIBLE", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def defaults() -> dict[str, Any]:
    return {
        "workspace_root": str(Path(__file__).resolve().parents[2]),
        "file_read_enabled": True,
        "file_search_enabled": True,
        "run_process_enabled": True,
        "coding_agent_enabled": True,
        "ui_context_enabled": True,
        "ui_interaction_enabled": True,
        "terminal_enabled": True,
        "terminal_visible": _terminal_visible(),
        "mcp_server_url": DEFAULT_MCP_URL,
    }


def normalize_settings(value: object) -> dict[str, Any]:
    result = defaults()
    if not isinstance(value, dict):
        return result
    root = str(value.get("workspace_root", result["workspace_root"])).strip() or result["workspace_root"]
    result["workspace_root"] = root
    for key in (
        "file_read_enabled",
        "file_search_enabled",
        "run_process_enabled",
        "coding_agent_enabled",
        "ui_context_enabled",
        "ui_interaction_enabled",
        "terminal_enabled",
    ):
        result[key] = bool(value.get(key, result[key]))
    result["terminal_visible"] = _terminal_visible()
    result["mcp_server_url"] = (
        str(value.get("mcp_server_url", result["mcp_server_url"])).strip() or result["mcp_server_url"]
    )
    return result


class AssistantToolExecutor:
    def __init__(self, settings: dict[str, Any], coding_agent_provider: str = "none"):
        self.settings = normalize_settings(settings)
        root = self.settings["workspace_root"]
        self.root = Path(root).expanduser().resolve() if root else None
        self.coding_agent_provider = (
            coding_agent_provider if coding_agent_provider in CODING_AGENT_PROVIDERS else "none"
        )

    def definitions(self) -> list[dict[str, Any]]:
        definitions = []
        workspace_ready = bool(self.root and self.root.is_dir())
        if workspace_ready and self.settings["file_read_enabled"]:
            definitions.append(
                {
                    "name": "file_read",
                    "description": "Read a one-based inclusive line range from a file in the configured workspace. The range is limited to 120 lines and 16 KiB.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "start_line": {"type": "integer", "minimum": 1},
                            "end_line": {"type": "integer", "minimum": 1},
                        },
                        "required": ["path", "start_line", "end_line"],
                        "additionalProperties": False,
                    },
                }
            )
        if workspace_ready and self.settings["file_search_enabled"]:
            definitions.append(
                {
                    "name": "file_search",
                    "description": "Search filenames or text in the configured workspace without reading whole files. Returns at most 12 matching paths and lines.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "minLength": 1},
                            "path": {"type": "string"},
                            "regex": {"type": "boolean"},
                            "scope": {"type": "string", "enum": ["content", "filename"]},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 12},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                }
            )
        if workspace_ready and self.settings["run_process_enabled"]:
            definitions.append(
                {
                    "name": "run_process",
                    "description": "Run one non-interactive OS command in the configured workspace. executable and arguments are passed directly without a shell. Output is limited to 16 KiB.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "executable": {"type": "string", "minLength": 1},
                            "arguments": {"type": "array", "items": {"type": "string"}},
                            "working_directory": {"type": "string"},
                            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300},
                        },
                        "required": ["executable", "arguments"],
                        "additionalProperties": False,
                    },
                }
            )
        if self.settings["coding_agent_enabled"]:
            definitions.append(
                {
                    "name": "coding_agent",
                    "description": "Ask the configured local coding agent to inspect, modify, or validate the configured workspace. If no coding agent is selected, returns instructions for configuring one in Settings.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string", "minLength": 1},
                            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1800},
                        },
                        "required": ["task"],
                        "additionalProperties": False,
                    },
                }
            )
        return definitions

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "file_read" and self.settings["file_read_enabled"]:
                return self._file_read(arguments)
            if name == "file_search" and self.settings["file_search_enabled"]:
                return self._file_search(arguments)
            if name == "run_process" and self.settings["run_process_enabled"]:
                return self._run_process(arguments)
            if name == "coding_agent" and self.settings["coding_agent_enabled"]:
                return self._coding_agent(arguments)
            return self._result(error="Tool is disabled or unavailable.")
        except (OSError, UnicodeError, ValueError, re.error, subprocess.SubprocessError) as error:
            return self._result(error=str(error))

    def _resolve(self, path: object = "") -> Path:
        if not self.root:
            raise ValueError("No assistant workspace is configured.")
        candidate = (self.root / str(path or "")).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Path must remain inside the configured workspace.")
        if any(
            part.lower() in BLOCKED_NAMES or part.lower().endswith((".pem", ".key"))
            for part in candidate.parts
        ):
            raise ValueError("This path is not available to the assistant.")
        return candidate

    @staticmethod
    def _result(**value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _file_read(self, arguments: dict[str, Any]) -> str:
        start, end = int(arguments["start_line"]), int(arguments["end_line"])
        if start < 1 or end < start or end - start + 1 > MAX_FILE_LINES:
            raise ValueError("Line range must be between 1 and 120 lines.")
        path = self._resolve(arguments.get("path"))
        if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("File is unavailable or too large.")
        lines = path.read_text(encoding="utf-8").splitlines()
        content = "\n".join(lines[start - 1 : end])
        encoded = content.encode("utf-8")[:MAX_RESULT_BYTES]
        return self._result(
            path=str(path.relative_to(self.root)),
            start_line=start,
            end_line=min(end, len(lines)),
            total_lines=len(lines),
            content=encoded.decode("utf-8", errors="ignore"),
            truncated=len(content.encode("utf-8")) > MAX_RESULT_BYTES,
        )

    def _file_search(self, arguments: dict[str, Any]) -> str:
        query = str(arguments["query"])
        scope = str(arguments.get("scope") or "content")
        if scope not in {"content", "filename"}:
            raise ValueError("scope must be content or filename.")
        limit = min(max(int(arguments.get("limit", 8)), 1), MAX_SEARCH_RESULTS)
        expression = re.compile(query) if arguments.get("regex") else None
        target = self._resolve(arguments.get("path"))
        files = [target] if target.is_file() else target.rglob("*")
        matches: list[dict[str, Any]] = []
        for file in files:
            if (
                not file.is_file()
                or any(part.lower() in BLOCKED_NAMES for part in file.parts)
                or file.stat().st_size > 10 * 1024 * 1024
            ):
                continue
            relative = str(file.relative_to(self.root))
            if scope == "filename":
                found = bool(expression.search(file.name)) if expression else query in file.name
                if found:
                    matches.append({"path": relative, "match_kind": "filename"})
            else:
                try:
                    for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                        found = bool(expression.search(line)) if expression else query in line
                        if found:
                            matches.append(
                                {
                                    "path": relative,
                                    "line": number,
                                    "content": line[:1500],
                                    "match_kind": "content",
                                }
                            )
                            break
                except UnicodeDecodeError:
                    continue
            if len(matches) >= limit:
                break
        return self._result(query=query, matches=matches, truncated=len(matches) >= limit)

    def _run_process(self, arguments: dict[str, Any]) -> str:
        executable = str(arguments["executable"])
        if executable.lower() in {"sh", "bash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "pwsh"}:
            raise ValueError(
                "Shell executables are not available; pass a command and argument array directly."
            )
        command = [executable, *[str(item) for item in arguments["arguments"]]]
        cwd = self._resolve(arguments.get("working_directory"))
        if not cwd.is_dir():
            raise ValueError("working_directory must be a workspace directory.")
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=min(max(int(arguments.get("timeout_seconds", 60)), 1), 300),
            env={"PATH": os.environ.get("PATH", "")},
        )
        output = (
            (result.stdout + result.stderr)
            .encode("utf-8")[:MAX_RESULT_BYTES]
            .decode("utf-8", errors="ignore")
        )
        return self._result(
            command=command,
            working_directory=str(cwd.relative_to(self.root)),
            exit_code=result.returncode,
            output=output,
            truncated=len((result.stdout + result.stderr).encode("utf-8")) > MAX_RESULT_BYTES,
        )

    def _coding_agent(self, arguments: dict[str, Any]) -> str:
        if self.coding_agent_provider == "none":
            return self._result(
                error="No Coding Agent is selected. Select Kiro, Claude Code, or Codex in Settings.",
                error_code="coding_agent_not_configured",
                settings_page="settings",
            )
        if not self.root or not self.root.is_dir():
            return self._result(
                error="The Assistant workspace is missing. Configure a valid workspace in the Assistant tool settings.",
                error_code="assistant_workspace_unavailable",
            )
        prompt = build_coding_agent_prompt(str(arguments["task"]), self.root)
        command = build_coding_agent_command(self.coding_agent_provider, prompt=prompt)
        if not shutil.which(command[0]):
            return self._result(
                error=f"The selected Coding Agent ({self.coding_agent_provider}) is not installed or is unavailable on PATH.",
                error_code="coding_agent_not_installed",
                provider=self.coding_agent_provider,
            )
        result = subprocess.run(
            command,
            cwd=self.root,
            shell=False,
            capture_output=True,
            text=True,
            timeout=min(max(int(arguments.get("timeout_seconds", 600)), 1), 1800),
            env=os.environ.copy(),
        )
        combined_output = result.stdout + result.stderr
        output = combined_output.encode("utf-8")[:MAX_RESULT_BYTES].decode("utf-8", errors="ignore")
        return self._result(
            provider=self.coding_agent_provider,
            command=command[:-1],
            working_directory=str(self.root),
            exit_code=result.returncode,
            output=output,
            truncated=len(combined_output.encode("utf-8")) > MAX_RESULT_BYTES,
        )
