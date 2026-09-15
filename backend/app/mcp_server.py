"""MCP surface for the stable OpenOrbit v1 API.

The tools deliberately call the same store operations as the HTTP handlers.
This keeps MCP local-first and avoids making the server call itself over HTTP.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .docker import preflight_docker
from .store import ConsoleStore


def _json(value: Any) -> Any:
    """Convert Pydantic response models without changing ordinary JSON values."""
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def create_mcp_server(
    get_store: Callable[[], ConsoleStore], openapi: Callable[[], dict[str, Any]]
) -> FastMCP:
    """Create the streamable-HTTP MCP server mounted by the FastAPI app."""
    mcp = FastMCP(
        "OpenOrbit",
        instructions=(
            "Operate the local OpenOrbit control plane. Read state before starting, approving, "
            "rejecting, cancelling, or stopping pipelines. The OpenAPI resource is the complete "
            "contract for the corresponding HTTP API."
        ),
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        ),
    )

    @mcp.resource("openorbit://openapi")
    def openapi_schema() -> str:
        """The generated OpenAPI 3 contract for OpenOrbit's versioned HTTP API."""
        import json

        return json.dumps(openapi(), ensure_ascii=False)

    @mcp.tool(
        description="Get local service health, dashboard totals, active pipelines, and Docker readiness.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    def get_status() -> dict[str, Any]:
        store = get_store()
        return {
            "health": {"status": "ok"},
            "dashboard": _json(store.dashboard()),
            "active_pipelines": _json(store.active_evaluations()),
            "docker": preflight_docker(),
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
    def list_projects() -> list[dict[str, Any]]:
        """List all configured projects (the v1 API calls builds projects)."""
        return [_json(project) for project in get_store().builds()]

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
    def get_project(project_id: str) -> dict[str, Any]:
        """Get one project and its complete evaluation configuration."""
        return _json(get_store().build(project_id))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
    def list_pipelines(project_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        """List retained pipeline runs, optionally filtered by project or status."""
        pipelines = get_store().runs()
        if project_id:
            pipelines = [pipeline for pipeline in pipelines if pipeline.build_id == project_id]
        if status:
            pipelines = [pipeline for pipeline in pipelines if pipeline.status == status]
        return [_json(pipeline) for pipeline in pipelines]

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
    def get_pipeline(pipeline_id: str) -> dict[str, Any]:
        """Get a pipeline's current state, phases, evidence, and supervisor results."""
        return _json(get_store().run(pipeline_id))

    @mcp.tool(
        description="Start a project pipeline. Use test mode for a one-off safe validation run.",
        annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    def start_pipeline(project_id: str, execution_mode: Literal["run", "test"] = "run") -> dict[str, Any]:
        """Start a retained run or transient test pipeline for a project."""
        return _json(get_store().invoke_remote_build(project_id, execution_mode, None))

    @mcp.tool(
        description="Approve, reject, or cancel a pipeline that is awaiting an operator action.",
        annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False, openWorldHint=False),
    )
    def act_on_pipeline(pipeline_id: str, action: Literal["approve", "reject", "cancel"]) -> dict[str, Any]:
        """Perform an approval-gated pipeline action."""
        actions = {
            "approve": get_store().approve,
            "reject": get_store().reject,
            "cancel": get_store().cancel,
        }
        return _json(actions[action](pipeline_id))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
    def list_improvements(build_id: str | None = None) -> list[dict[str, Any]]:
        """List supervisor proposals and their decision lifecycle, optionally for one project."""
        return _json(get_store().proposal_lifecycles(build_id))

    @mcp.tool(
        description="Cancel every active local pipeline. Use only after confirming the affected work.",
        annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False, openWorldHint=False),
    )
    def emergency_stop_pipelines() -> dict[str, Any]:
        """Cancel all active pipelines immediately."""
        return _json(get_store().emergency_stop())

    return mcp
