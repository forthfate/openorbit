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


def _text(value: object, limit: int = 500) -> str:
    """Keep MCP summaries bounded without losing a useful error description."""
    return str(value or "")[:limit]


def _pipeline_summary(value: Any) -> dict[str, Any]:
    run = _json(value)
    steps = run.get("step_results", []) if isinstance(run, dict) else []
    supervisor = run.get("supervisor_results", []) if isinstance(run, dict) else []
    files = [
        file
        for step in steps
        if isinstance(step, dict)
        for file in step.get("data_files", [])
        if isinstance(file, dict)
    ]
    return {
        key: run.get(key)
        for key in (
            "id",
            "build_id",
            "build_name",
            "workflow_id",
            "workflow_name",
            "status",
            "current_phase",
            "current_step",
            "execution_mode",
            "execution_type",
            "created_at",
            "updated_at",
            "finished_at",
            "loop_limit",
            "approval_score",
            "supervisor_status",
            "supervisor_error",
        )
    } | {
        "step_count": len(steps),
        "supervisor_result_count": len(supervisor),
        "evidence_file_count": len(files),
    }


def _pipeline_detail(value: Any, detail: str, max_items: int) -> dict[str, Any]:
    run = _json(value)
    result = _pipeline_summary(run)
    if detail == "summary":
        return result
    limit = max(1, min(max_items, 50))
    if detail == "steps":
        result["steps"] = [
            {
                key: _text(step.get(key))
                if key in {"id", "phase", "name", "status", "error"}
                else step.get(key)
                for key in (
                    "id",
                    "phase",
                    "name",
                    "loop_index",
                    "status",
                    "started_at",
                    "ended_at",
                    "exit_code",
                    "error",
                )
            }
            for step in run.get("step_results", [])[:limit]
            if isinstance(step, dict)
        ]
    elif detail == "supervision":
        records = run.get("supervisor_results", []) or []
        result["supervision"] = [
            {
                "iteration": record.get("iteration"),
                "stage": record.get("stage"),
                "status": record.get("status"),
                "recorded_at": record.get("recorded_at"),
                "error": _text(record.get("error")),
                "score": (record.get("response") or {}).get("evaluation", {}).get("score")
                if isinstance(record.get("response"), dict)
                else None,
                "approval": (record.get("response") or {}).get("evaluation", {}).get("approval")
                if isinstance(record.get("response"), dict)
                else None,
            }
            for record in records[:limit]
            if isinstance(record, dict)
        ]
    elif detail == "evidence":
        files = [
            file
            for step in run.get("step_results", [])
            if isinstance(step, dict)
            for file in step.get("data_files", [])
            if isinstance(file, dict)
        ]
        result["evidence"] = [
            {key: file.get(key) for key in ("label", "filename", "relative_path", "size", "content_type")}
            for file in files[:limit]
        ]
        result["evidence_truncated"] = len(files) > limit
    return result


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
        dashboard = store.dashboard()
        return {
            "health": {"status": "ok"},
            "dashboard": {
                "metrics": dashboard["metrics"],
                "active_build_count": len(dashboard["active_builds"]),
            },
            "active_pipelines": [_pipeline_summary(run) for run in store.active_evaluations()[:20]],
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
    def list_pipelines(
        project_id: str | None = None, status: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """List compact pipeline summaries; use get_pipeline for a bounded detail section."""
        pipelines = get_store().runs()
        if project_id:
            pipelines = [pipeline for pipeline in pipelines if pipeline.build_id == project_id]
        if status:
            pipelines = [pipeline for pipeline in pipelines if pipeline.status == status]
        return [_pipeline_summary(pipeline) for pipeline in pipelines[: max(1, min(limit, 50))]]

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False))
    def get_pipeline(
        pipeline_id: str,
        detail: Literal["summary", "steps", "supervision", "evidence"] = "summary",
        max_items: int = 20,
    ) -> dict[str, Any]:
        """Get one bounded pipeline section; summary is the default and never returns raw logs or HTML."""
        return _pipeline_detail(get_store().run(pipeline_id), detail, max_items)

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
