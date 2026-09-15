"""Run a bounded external automation through its explicit action contract."""

import json
import os
import shlex

from orbit_sdk import ORBIT_PROJECT_PATH, graph, runner

graph.connect("check-adapter", "prepare-adapter")
graph.connect("prepare-adapter", "run-adapter", label="prepared target")
graph.connect("run-adapter", "collect-adapter-evidence", kind="data", label="adapter output")
graph.connect("collect-adapter-evidence", "close-adapter-cycle")
graph.connect("close-adapter-cycle", "prepare-adapter", kind="loop", label="next cycle")
graph.connect("close-adapter-cycle", "finalize-adapter", kind="condition", label="completed")


def adapter_command():
    configured = os.environ.get("ORBIT_ADAPTER_COMMAND", "").strip()
    if not configured:
        raise ValueError("Set ORBIT_ADAPTER_COMMAND to an external tool command")
    if configured.startswith("["):
        value = json.loads(configured)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("ORBIT_ADAPTER_COMMAND JSON must be an array of strings")
        return value
    return shlex.split(configured)


def invoke(ctx, action):
    return ctx.exec(
        [*adapter_command(), action],
        cwd=ORBIT_PROJECT_PATH(),
        timeout=3600,
        target_log_source="external-adapter",
    )


@graph.step("check-adapter", title="Check adapter readiness", phase="before_all", outputs=["adapter_status"])
@runner.phase("before_all")
def before_all(ctx):
    ctx.emit_result({"external_adapter": {"status": invoke(ctx, "status")}})


@graph.step(
    "prepare-adapter",
    title="Prepare adapter cycle",
    phase="before_each",
    inputs=["adapter_status"],
    outputs=["prepared_target"],
)
@runner.phase("before_each")
def before_each(ctx):
    ctx.emit_result({"external_adapter": {"iteration": ctx.loop_index, "prepared": invoke(ctx, "prepare")}})


@graph.step(
    "run-adapter",
    title="Run bounded adapter task",
    phase="execute",
    inputs=["prepared_target"],
    outputs=["adapter_result"],
)
@runner.phase("execute")
def execute(ctx):
    ctx.emit_result({"external_adapter": {"iteration": ctx.loop_index, "result": invoke(ctx, "run-once")}})


@graph.step(
    "collect-adapter-evidence",
    title="Collect adapter evidence",
    phase="verify",
    inputs=["adapter_result"],
    outputs=["adapter_evidence"],
)
@runner.phase("verify")
def verify(ctx):
    ctx.emit_result(
        {"external_adapter": {"iteration": ctx.loop_index, "evidence": invoke(ctx, "collect-evidence")}}
    )


@graph.step(
    "close-adapter-cycle",
    title="Close adapter cycle",
    phase="after_each",
    inputs=["adapter_evidence"],
    outputs=["cycle_complete"],
)
@runner.phase("after_each")
def after_each(ctx):
    ctx.log("Completed one bounded external adapter cycle")


@graph.step(
    "finalize-adapter",
    title="Finalize external automation",
    phase="after_all",
    inputs=["cycle_complete"],
    outputs=["final_status"],
)
@runner.phase("after_all")
def after_all(ctx):
    ctx.log("Finalized the external automation evaluation")


if __name__ == "__main__":
    runner.main()
