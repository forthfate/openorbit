"""Request-scoped bridge between Assistant tools and one browser UI session."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class PendingUiCommand:
    event: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None


@dataclass
class UiSession:
    send: Callable[[str, dict[str, Any]], None]
    pending: dict[str, PendingUiCommand] = field(default_factory=dict)


class AssistantUiBroker:
    """Route synchronous model tool calls through the active chat stream."""

    def __init__(self) -> None:
        self._sessions: dict[str, UiSession] = {}
        self._lock = threading.Lock()

    def open(self, session_id: str, send: Callable[[str, dict[str, Any]], None]) -> None:
        with self._lock:
            self._sessions[session_id] = UiSession(send=send)

    def close(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                for pending in session.pending.values():
                    pending.result = {"ok": False, "error": "UI session closed."}
                    pending.event.set()

    def request(self, session_id: str, command: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        command_id = uuid.uuid4().hex
        pending = PendingUiCommand()
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                logger.info("assistant UI command rejected: unavailable session=%s", session_id)
                return {"ok": False, "error": "The browser UI session is unavailable."}
            session.pending[command_id] = pending
            logger.info(
                "assistant UI command sent: session=%s id=%s type=%s",
                session_id,
                command_id,
                command.get("type"),
            )
            session.send(command_id, command)
        if not pending.event.wait(timeout):
            with self._lock:
                session = self._sessions.get(session_id)
                if session:
                    session.pending.pop(command_id, None)
            return {"ok": False, "error": "The browser UI did not respond in time."}
        return pending.result or {"ok": False, "error": "The browser UI returned no result."}

    def resolve(self, session_id: str, command_id: str, result: dict[str, Any]) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            pending = session.pending.pop(command_id, None) if session else None
        if not pending:
            logger.info("assistant UI result ignored: session=%s id=%s", session_id, command_id)
            return False
        pending.result = result
        logger.info(
            "assistant UI result received: session=%s id=%s ok=%s components=%s diagnostics=%s",
            session_id,
            command_id,
            result.get("ok"),
            len(result.get("components", [])) if isinstance(result.get("components"), list) else "n/a",
            result.get("diagnostics"),
        )
        pending.event.set()
        return True


class AssistantUiToolExecutor:
    """Expose semantic, browser-owned UI capabilities to the Assistant."""

    def __init__(
        self, broker: AssistantUiBroker, session_id: str, *, context_enabled: bool, interaction_enabled: bool
    ):
        self.broker = broker
        self.session_id = session_id
        self.context_enabled = context_enabled
        self.interaction_enabled = interaction_enabled and context_enabled

    def definitions(self) -> list[dict[str, Any]]:
        definitions = []
        if self.context_enabled:
            definitions.append(
                {
                    "name": "ui_get_context",
                    "description": "Read the current browser page, visible Assistant-enabled components, controls, and actions. Read this before interacting with the UI.",
                    "parameters": {
                        "type": "object",
                        "properties": {"component_id": {"type": "string"}},
                        "additionalProperties": False,
                    },
                }
            )
        if self.interaction_enabled:
            definitions.append(
                {
                    "name": "ui_interact",
                    "description": "Set one visible Assistant-enabled UI control or invoke one listed UI action. Use the revision returned by ui_get_context. High-impact actions only open the normal user confirmation dialog.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "component_id": {"type": "string", "minLength": 1},
                            "revision": {"type": "integer", "minimum": 1},
                            "operation": {"type": "string", "enum": ["set_control_value", "invoke_action"]},
                            "target_id": {"type": "string", "minLength": 1},
                            "value": {},
                        },
                        "required": ["component_id", "revision", "operation", "target_id"],
                        "additionalProperties": False,
                    },
                }
            )
        return definitions

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "ui_get_context" and self.context_enabled:
            result = self.broker.request(
                self.session_id,
                {"type": "get_context", "component_id": arguments.get("component_id")},
            )
        elif name == "ui_interact" and self.interaction_enabled:
            result = self.broker.request(
                self.session_id,
                {"type": "interact", **arguments},
            )
        else:
            result = {"ok": False, "error": "Unknown browser UI tool."}
        return json.dumps(result, ensure_ascii=False)
