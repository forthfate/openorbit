"""Run the configured AI SLO evaluator through explicit runner phases.

The external evaluator owns probe execution. This runner passes the fixed probe
matrix, validates its JSON action responses, and retains evidence for Orbit's
supervisor to assess quality, safety, latency, or cost drift.
"""

from orbit_sdk import graph, runner

COMMAND_ENV = "ORBIT_PROBE_COMMAND"
NAMESPACE = "probe_gate"


def invoke(ctx, action):
    """Run one evaluator action through the SDK command contract."""
    return ctx.run_json_action(
        command_env=COMMAND_ENV,
        action=action,
        input_env="ORBIT_CYCLE_INPUT",
        input_data={"iteration": ctx.loop_index, "build": ctx.build, "probes": ctx.test_cases},
        timeout=3600,
        log_source="probe-gate",
    )


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
    """Require at least one fixed SLO probe."""
    ctx.require_test_cases(label="fixed probe case")


@graph.step(
    "preflight-probe-gate",
    title="Check probe matrix readiness",
    phase="before_all",
    inputs=["contract"],
    outputs=["preflight"],
)
@runner.phase("before_all", step_id="preflight-probe-gate")
def preflight(ctx):
    """Capture evaluator readiness before iterative probes begin."""
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
    """Prepare the evaluator for this SLO iteration."""
    ctx.emit_result({NAMESPACE: {"iteration": ctx.loop_index, "prepared": invoke(ctx, "prepare")}})


@graph.step(
    "run-probe-gate", title="Run probe matrix", phase="execute", inputs=["prepared"], outputs=["result"]
)
@runner.phase("execute", step_id="run-probe-gate")
def execute(ctx):
    """Run the fixed SLO probe matrix."""
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
    """Collect evidence for supervisor assessment."""
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
    """Close one bounded SLO monitoring iteration."""
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
    """Finalize the SLO monitoring run."""
    ctx.log("Finalized the probe matrix")


if __name__ == "__main__":
    runner.main()
