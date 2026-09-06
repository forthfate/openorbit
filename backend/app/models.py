from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Step(BaseModel):
    id: str
    phase: Literal["init", "setup", "run", "eval", "teardown", "finalize"]
    name: str
    command: list[str]
    working_directory: str
    timeout_seconds: int = Field(default=300, ge=1, le=86_400)
    approval: Literal["not_required", "required"] = "not_required"
    on_failure: Literal["stop", "continue"] = "stop"
    minimum_interval_seconds: int = Field(default=0, ge=0, le=86_400)


class Workflow(BaseModel):
    id: str
    behavior_bundle: str | None = None
    name: str
    description: str
    kind: Literal["simulation", "improvement"]
    enabled: bool = False
    risk: Literal["low", "medium", "high"]
    tags: list[str] = []
    runner_id: str | None = None
    steps: list[Step]
    test_steps: list[Step] | None = None

    def steps_for(self, execution_mode: Literal["run", "test"]) -> list[Step]:
        if execution_mode == "test" and self.test_steps is not None:
            return self.test_steps
        return self.steps

    def lifecycle_is_complete(self, execution_mode: Literal["run", "test"] = "run") -> bool:
        phases = [step.phase for step in self.steps_for(execution_mode)]
        return phases in (
            ["init", "setup", "run", "eval", "teardown"],
            ["init", "setup", "run", "eval", "teardown", "finalize"],
        )


class Run(BaseModel):
    id: str
    workflow_id: str
    workflow_name: str
    evaluation_build_id: str | None = None
    evaluation_build_name: str | None = None
    repository: str | None = None
    supervisor_profile_name: str | None = None
    prompt_source: str | None = None
    prompt_snapshot: str | None = None
    execution_mode: Literal["run", "test"] = "run"
    execution_type: Literal["pipeline", "invoke"] = "pipeline"
    loop_limit: int = 1
    repeat_interval_minutes: int = 0
    approval_score: int | None = None
    status: Literal["queued", "awaiting_approval", "running", "succeeded", "failed", "cancelled"]
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    current_step: str | None = None
    current_phase: str | None = None
    pid: int | None = None
    last_pid: int | None = None
    telemetry_trace_id: str | None = None
    supervisor_status: Literal["pending", "completed", "not_configured", "invalid_response", "failed"] = (
        "pending"
    )
    supervisor_response: dict[str, Any] | None = None
    supervisor_error: str | None = None
    supervisor_results: list[dict[str, Any]] = Field(default_factory=list)
    runner_output: str = ""
    step_results: list[dict] = []
    approval_reason: str | None = None
