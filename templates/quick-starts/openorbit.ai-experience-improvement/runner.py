"""Run the configured external AI evaluator through explicit runner phases.

The evaluator receives fixed test cases through ``ORBIT_CYCLE_INPUT`` and must
return one JSON object per action. Orbit retains that structured evidence for
supervision; this runner never infers an evaluation result itself.
"""

from orbit_sdk import graph, runner


def invoke(ctx, action):
    """Run one external evaluator action through the SDK command contract."""
    return ctx.run_json_action(
        command_env="ORBIT_AGENT_COMMAND",
        action=action,
        input_env="ORBIT_CYCLE_INPUT",
        input_data={"iteration": ctx.loop_index, "build": ctx.build, "test_cases": ctx.test_cases},
        timeout=3600,
        log_source="agent-cycle",
    )


graph.connect("validate-agent-cycle-contract", "preflight-agent-cycle")
graph.connect("preflight-agent-cycle", "prepare-agent-cycle", label="prepared inputs")
graph.connect("prepare-agent-cycle", "run-agent-cycle", kind="data", label="action result")
graph.connect("run-agent-cycle", "collect-agent-cycle")
graph.connect("collect-agent-cycle", "close-agent-cycle")
graph.connect("close-agent-cycle", "prepare-agent-cycle", kind="loop", label="next cycle")
graph.connect("close-agent-cycle", "finalize-agent-cycle", kind="condition", label="completed")


@graph.step(
    "validate-agent-cycle-contract",
    title="Validate external agent contract",
    phase="before_all",
    outputs=["contract"],
)
@runner.phase("before_all", step_id="validate-agent-cycle-contract")
def validate_contract(ctx):
    """Require at least one fixed AI experience test case."""
    ctx.require_test_cases()


@graph.step(
    "preflight-agent-cycle",
    title="Check external agent readiness",
    phase="before_all",
    inputs=["contract"],
    outputs=["preflight"],
)
@runner.phase("before_all", step_id="preflight-agent-cycle")
def preflight(ctx):
    """Capture the external evaluator's readiness."""
    ctx.emit_result({"agent_cycle": {"preflight": invoke(ctx, "status")}})


@graph.step(
    "prepare-agent-cycle",
    title="Prepare external agent",
    phase="before_each",
    inputs=["preflight"],
    outputs=["prepared"],
)
@runner.phase("before_each", step_id="prepare-agent-cycle")
def prepare(ctx):
    """Prepare the evaluator for the current iteration."""
    ctx.emit_result({"agent_cycle": {"iteration": ctx.loop_index, "prepared": invoke(ctx, "prepare")}})


@graph.step(
    "run-agent-cycle", title="Run external agent", phase="execute", inputs=["prepared"], outputs=["result"]
)
@runner.phase("execute", step_id="run-agent-cycle")
def execute(ctx):
    """Run the external AI experience evaluation once."""
    ctx.emit_result({"agent_cycle": {"iteration": ctx.loop_index, "result": invoke(ctx, "run-once")}})


@graph.step(
    "collect-agent-cycle",
    title="Collect external agent evidence",
    phase="verify",
    inputs=["result"],
    outputs=["evidence"],
)
@runner.phase("verify", step_id="collect-agent-cycle")
def verify(ctx):
    """Collect structured evidence for supervision."""
    ctx.emit_result(
        {"agent_cycle": {"iteration": ctx.loop_index, "evidence": invoke(ctx, "collect-evidence")}}
    )


@graph.step(
    "close-agent-cycle",
    title="Close external agent cycle",
    phase="after_each",
    inputs=["evidence"],
    outputs=["complete"],
)
@runner.phase("after_each", step_id="close-agent-cycle")
def after_each(ctx):
    """Close one bounded AI experience iteration."""
    ctx.log("Completed one bounded external agent cycle")


@graph.step(
    "finalize-agent-cycle",
    title="Finalize external agent",
    phase="after_all",
    inputs=["complete"],
    outputs=["final"],
)
@runner.phase("after_all", step_id="finalize-agent-cycle")
def after_all(ctx):
    """Finalize the external evaluator run."""
    ctx.log("Finalized the external agent")


if __name__ == "__main__":
    runner.main()
