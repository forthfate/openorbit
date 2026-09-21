"""Run an external structured evaluator through explicit runner phases.

The command receives a fixed probe matrix in ``ORBIT_CYCLE_INPUT`` and returns
one JSON object for each action. This template validates and retains evidence;
the supervisor, not the runner, interprets the result.
"""

import json
import os
import shlex

from orbit_sdk import graph, runner

COMMAND_ENV = "ORBIT_PROBE_COMMAND"
NAMESPACE = "probe_gate"


def invoke(ctx, action):
    """Run one structured evaluator action and validate its JSON response.

    Args:
        ctx: The active Orbit runner context.
        action: The evaluator action requested for this lifecycle phase.

    Returns:
        The evaluator's JSON object.

    Raises:
        ValueError: If the command configuration is invalid.
        RuntimeError: If the evaluator does not emit a JSON object.
    """
    configured = os.environ.get(COMMAND_ENV, "").strip()
    if not configured:
        raise ValueError(f"Set {COMMAND_ENV} to an external tool command")
    command = json.loads(configured) if configured.startswith("[") else shlex.split(configured)
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError(f"{COMMAND_ENV} must be a JSON string array or command")
    payload = json.dumps(
        {"action": action, "iteration": ctx.loop_index, "build": ctx.build, "probes": ctx.test_cases},
        ensure_ascii=False,
    )
    output = ctx.exec(
        [*command, action],
        cwd=ctx.project_root,
        timeout=3600,
        env={"ORBIT_CYCLE_INPUT": payload},
        target_log_source="probe-gate",
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Action {action!r} did not return JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"Action {action!r} must return a JSON object")
    return result


graph.connect("validate-probe-gate-contract", "preflight-probe-gate")
graph.connect("preflight-probe-gate", "prepare-probe-gate", label="prepared inputs")
graph.connect("prepare-probe-gate", "run-probe-gate", kind="data", label="action result")
graph.connect("run-probe-gate", "collect-probe-gate")
graph.connect("collect-probe-gate", "close-probe-gate")
graph.connect("close-probe-gate", "prepare-probe-gate", kind="loop", label="next cycle")
graph.connect("close-probe-gate", "finalize-probe-gate", kind="condition", label="completed")


@graph.step(
    "validate-probe-gate-contract",
    title="Validate probe matrix contract",
    phase="before_all",
    outputs=["contract"],
)
@runner.phase("before_all", step_id="validate-probe-gate-contract")
def validate_contract(ctx):
    """Require a fixed probe matrix before any external command runs."""
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed probe case")


@graph.step(
    "preflight-probe-gate",
    title="Check probe matrix readiness",
    phase="before_all",
    inputs=["contract"],
    outputs=["preflight"],
)
@runner.phase("before_all", step_id="preflight-probe-gate")
def preflight(ctx):
    """Record evaluator readiness once for the complete run."""
    ctx.emit_result({NAMESPACE: {"preflight": invoke(ctx, "preflight")}})


@graph.step(
    "prepare-probe-gate",
    title="Prepare probe matrix",
    phase="before_each",
    inputs=["preflight"],
    outputs=["prepared"],
)
@runner.phase("before_each", step_id="prepare-probe-gate")
def prepare(ctx):
    """Ask the evaluator to prepare inputs for this iteration."""
    ctx.emit_result({NAMESPACE: {"iteration": ctx.loop_index, "prepared": invoke(ctx, "prepare")}})


@graph.step(
    "run-probe-gate", title="Run probe matrix", phase="execute", inputs=["prepared"], outputs=["result"]
)
@runner.phase("execute", step_id="run-probe-gate")
def execute(ctx):
    """Run the probe matrix and retain its structured result."""
    ctx.emit_result({NAMESPACE: {"iteration": ctx.loop_index, "result": invoke(ctx, "run-probes")}})


@graph.step(
    "collect-probe-gate",
    title="Collect probe matrix evidence",
    phase="verify",
    inputs=["result"],
    outputs=["evidence"],
)
@runner.phase("verify", step_id="collect-probe-gate")
def verify(ctx):
    """Collect evidence that the supervisor can assess."""
    ctx.emit_result({NAMESPACE: {"iteration": ctx.loop_index, "evidence": invoke(ctx, "collect-evidence")}})


@graph.step(
    "close-probe-gate",
    title="Close probe matrix cycle",
    phase="after_each",
    inputs=["evidence"],
    outputs=["complete"],
)
@runner.phase("after_each", step_id="close-probe-gate")
def after_each(ctx):
    """Mark the bounded probe iteration as complete."""
    ctx.log("Completed one bounded probe matrix cycle")


@graph.step(
    "finalize-probe-gate",
    title="Finalize probe matrix",
    phase="after_all",
    inputs=["complete"],
    outputs=["final"],
)
@runner.phase("after_all", step_id="finalize-probe-gate")
def after_all(ctx):
    """Record completion after the final probe iteration."""
    ctx.log("Finalized the probe matrix")


if __name__ == "__main__":
    runner.main()
