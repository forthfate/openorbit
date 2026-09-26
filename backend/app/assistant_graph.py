"""LangGraph orchestration for the local Orbit assistant."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, TypedDict

from coding_agents import execution_environment_context
from httpx import TransportError
from langgraph.graph import END, START, StateGraph
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .assistant_tools import DEFAULT_MCP_URL, AssistantToolExecutor
from .assistant_ui import AssistantUiToolExecutor
from .providers import AzureOpenAIProvider, BedrockProvider, ModelSettings

logger = logging.getLogger(__name__)


class AssistantState(TypedDict, total=False):
    prompt: str
    response: str


@dataclass
class McpConnectionStatus:
    """One Assistant turn's bounded MCP connection state."""

    state: Literal["idle", "connecting", "ready", "retrying", "failed"] = "idle"
    attempts: int = 0
    last_error: str = ""


class LocalMcpTools:
    """Expose the mounted OpenOrbit MCP server as native model function tools."""

    def __init__(self, url: str = DEFAULT_MCP_URL, *, retry_delays: tuple[float, ...] = (0.25, 0.5, 1.0)):
        self.url = url
        self.retry_delays = retry_delays
        self.connection = McpConnectionStatus()
        self._definitions: list[dict[str, Any]] | None = None

    @staticmethod
    def _retryable(error: Exception) -> bool:
        """Retry startup and transport failures, never protocol/configuration failures."""
        return isinstance(error, (OSError, TimeoutError, TransportError))

    async def _retry_read(
        self, operation: Callable[[], Awaitable[list[dict[str, Any]]]]
    ) -> list[dict[str, Any]]:
        attempts = len(self.retry_delays) + 1
        for attempt in range(1, attempts + 1):
            self.connection.state = "connecting" if attempt == 1 else "retrying"
            self.connection.attempts = attempt
            try:
                value = await operation()
                self.connection.state, self.connection.last_error = "ready", ""
                return value
            except Exception as error:
                self.connection.last_error = str(error)
                if not self._retryable(error) or attempt == attempts:
                    self.connection.state = "failed"
                    raise
                delay = self.retry_delays[attempt - 1]
                logger.info("MCP initialization failed; retrying in %.2fs: %s", delay, error)
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable MCP retry state")

    async def _list_tools_once(self) -> list[dict[str, Any]]:
        async with streamablehttp_client(self.url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    {
                        "name": tool.name,
                        "description": tool.description or "OpenOrbit MCP tool.",
                        "parameters": tool.inputSchema,
                    }
                    for tool in result.tools
                ]

    async def _list_tools(self) -> list[dict[str, Any]]:
        return await self._retry_read(self._list_tools_once)

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        # Do not retry calls: an action might already have reached the target
        # before a connection drops.  Retrying it could duplicate a mutation.
        self.connection.state = "connecting"
        self.connection.attempts += 1
        async with streamablehttp_client(self.url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self.connection.state, self.connection.last_error = "ready", ""
                result = await session.call_tool(name, arguments)
                if result.isError:
                    return json.dumps({"error": "MCP tool failed", "content": result.content}, default=str)
                return json.dumps({"content": result.content}, default=str, ensure_ascii=False)

    @staticmethod
    def _run(coro: Any) -> Any:
        return asyncio.run(coro)

    def definitions(self) -> list[dict[str, Any]]:
        if self._definitions is not None:
            return self._definitions
        try:
            self._definitions = self._run(self._list_tools())
            return self._definitions
        except Exception as error:
            self.connection.state, self.connection.last_error = "failed", str(error)
            logger.info("MCP tools unavailable: %s", error)
            # The assistant remains usable while the local server is starting.
            return []

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            return self._run(self._call_tool(name, arguments))
        except Exception as error:
            self.connection.state, self.connection.last_error = "failed", str(error)
            return json.dumps({"error": f"MCP unavailable: {error}"})


class OrbitAssistantGraph:
    """A small, explicit LangGraph for one bounded assistant turn.

    The model node can use both the local bounded workspace tools and the
    mounted MCP control-room tools. Provider adapters retain the native tool
    call protocol, while LangGraph owns the turn state and final response.
    """

    def __init__(
        self,
        provider: AzureOpenAIProvider | BedrockProvider,
        settings: ModelSettings,
        local_tools: AssistantToolExecutor,
        mcp_tools: LocalMcpTools | None = None,
        ui_tools: AssistantUiToolExecutor | None = None,
        on_activity: Callable[[str, str | None], None] | None = None,
    ):
        self.provider = provider
        self.settings = settings
        self.local_tools = local_tools
        self.mcp_tools = mcp_tools or LocalMcpTools(local_tools.settings["mcp_server_url"])
        self.ui_tools = ui_tools
        self.on_activity = on_activity
        graph = StateGraph(AssistantState)
        graph.add_node("model", self._model)
        graph.add_edge(START, "model")
        graph.add_edge("model", END)
        self.graph = graph.compile()

    def _model(self, state: AssistantState) -> AssistantState:
        self._activity("thinking")
        local_definitions = self.local_tools.definitions()
        mcp_definitions = self.mcp_tools.definitions()
        ui_definitions = self.ui_tools.definitions() if self.ui_tools else []
        definitions = [*mcp_definitions, *local_definitions, *ui_definitions]

        def execute(name: str, arguments: dict[str, Any]) -> str:
            self._activity("working", name)
            if any(tool["name"] == name for tool in mcp_definitions):
                result = self.mcp_tools.execute(name, arguments)
            elif self.ui_tools and any(tool["name"] == name for tool in ui_definitions):
                result = self.ui_tools.execute(name, arguments)
            else:
                result = self.local_tools.execute(name, arguments)
            self._activity("thinking")
            return result

        response = (
            self.provider.complete_with_tools(self.settings, state["prompt"], definitions, execute)
            if definitions
            else self.provider.complete(self.settings, state["prompt"])
        )
        return {"response": response}

    def _activity(self, phase: str, tool: str | None = None) -> None:
        if self.on_activity:
            self.on_activity(phase, tool)

    def invoke(self, prompt: str) -> str:
        result = self.graph.invoke({"prompt": prompt})
        return str(result["response"])


def build_assistant_prompt(
    content: str, history: list[tuple[str, str]], locale: str | None, ui_enabled: bool = False
) -> str:
    prompt = (
        "You are Orbit, a concise assistant for the local OpenOrbit control room.\n"
        "Use the OpenOrbit MCP tools as the source of truth for local control-room state. "
        "Read state before suggesting or taking any state-changing action.\n"
        + execution_environment_context()
    )
    if ui_enabled:
        prompt += (
            "Browser UI tools are available for this turn. For any question about the current Orbit "
            "screen, visible component, selected item, open panel, dialog, form value, or any request "
            "to change the Orbit UI, first call ui_get_context. Use ui_interact only after reading the "
            "current UI context. Do not use file tools to infer browser UI state. File tools remain for "
            "workspace files and coding tasks only.\n"
        )
    if locale:
        prompt += f"Respond in BCP 47 locale '{locale}'.\n"
    if history:
        prompt += (
            "Conversation so far:\n"
            + "\n".join(f"{role.title()}: {message}" for role, message in history)
            + "\n\n"
        )
    return prompt + f"User: {content}\nAssistant:"
