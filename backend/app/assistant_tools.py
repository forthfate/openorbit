"""Bounded local tools exposed to the Orbit chat assistant."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

MAX_RESULT_BYTES = 16 * 1024
MAX_FILE_LINES = 120
MAX_SEARCH_RESULTS = 12
BLOCKED_NAMES = {".env", ".git", ".ssh", "id_rsa", "id_ed25519"}


def defaults() -> dict[str, Any]:
    return {
        "workspace_root": str(Path(__file__).resolve().parents[2]),
        "file_read_enabled": True,
        "file_search_enabled": True,
        "run_process_enabled": True,
        "terminal_enabled": True,
        "terminal_visible": True,
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
        "terminal_enabled",
        "terminal_visible",
    ):
        result[key] = bool(value.get(key, result[key]))
    return result


class AssistantToolExecutor:
    def __init__(self, settings: dict[str, Any]):
        self.settings = normalize_settings(settings)
        root = self.settings["workspace_root"]
        self.root = Path(root).expanduser().resolve() if root else None

    def definitions(self) -> list[dict[str, Any]]:
        if not self.root or not self.root.is_dir():
            return []
        definitions = []
        if self.settings["file_read_enabled"]:
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
        if self.settings["file_search_enabled"]:
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
        if self.settings["run_process_enabled"]:
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
        return definitions

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "file_read" and self.settings["file_read_enabled"]:
                return self._file_read(arguments)
            if name == "file_search" and self.settings["file_search_enabled"]:
                return self._file_search(arguments)
            if name == "run_process" and self.settings["run_process_enabled"]:
                return self._run_process(arguments)
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
