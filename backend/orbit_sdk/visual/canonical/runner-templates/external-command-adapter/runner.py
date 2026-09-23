"""Run an external command adapter through explicit runner phases.

The adapter may return ordinary text rather than JSON. Its lifecycle output is
retained under ``external_adapter`` so a supervisor can assess evidence without
the runner imposing product-specific semantics.
"""

from orbit_sdk import graph, runner


def invoke(ctx, action):
    """Run one external command action through the SDK command contract."""
    return ctx.run_command_action(
        command_env="ORBIT_ADAPTER_COMMAND", action=action, timeout=3600, log_source="external-adapter"
    )


graph.connect("validate-adapter-contract", "check-adapter")
graph.connect("check-adapter", "prepare-adapter", label="prepared target")
graph.connect("prepare-adapter", "run-adapter", kind="data", label="adapter output")
graph.connect("run-adapter", "collect-adapter-evidence")
graph.connect("collect-adapter-evidence", "close-adapter-cycle")
graph.connect("close-adapter-cycle", "prepare-adapter", kind="loop", label="next cycle")
graph.connect("close-adapter-cycle", "finalize-adapter", kind="condition", label="completed")


@graph.step(
    "validate-adapter-contract",
    title="Validate adapter command",
    phase="before_all",
    outputs=["adapter_contract"],
)
@runner.phase("before_all", step_id="validate-adapter-contract")
def validate_contract(ctx):
    """Validate the adapter command before invoking it."""
    ctx.command_from_env("ORBIT_ADAPTER_COMMAND")


@graph.step(
    "check-adapter",
    title="Check adapter readiness",
    phase="before_all",
    inputs=["adapter_contract"],
    outputs=["adapter_status"],
)
@runner.phase("before_all", step_id="check-adapter")
def check_adapter(ctx):
    """Record adapter readiness once for the run."""
    ctx.emit_result({"external_adapter": {"status": invoke(ctx, "status"), "iteration": ctx.loop_index}})


@graph.step(
    "prepare-adapter",
    title="Prepare adapter cycle",
    phase="before_each",
    inputs=["adapter_status"],
    outputs=["prepared_target"],
)
@runner.phase("before_each", step_id="prepare-adapter")
def prepare(ctx):
    """Prepare the external adapter for this iteration."""
    ctx.emit_result({"external_adapter": {"prepared": invoke(ctx, "prepare"), "iteration": ctx.loop_index}})


@graph.step(
    "run-adapter",
    title="Run bounded adapter task",
    phase="execute",
    inputs=["prepared_target"],
    outputs=["adapter_result"],
)
@runner.phase("execute", step_id="run-adapter")
def execute(ctx):
    """Execute the adapter's bounded unit of work."""
    ctx.emit_result({"external_adapter": {"result": invoke(ctx, "run-once"), "iteration": ctx.loop_index}})


@graph.step(
    "collect-adapter-evidence",
    title="Collect adapter evidence",
    phase="verify",
    inputs=["adapter_result"],
    outputs=["adapter_evidence"],
)
@runner.phase("verify", step_id="collect-adapter-evidence")
def verify(ctx):
    """Collect adapter evidence for supervisor review."""
    ctx.emit_result(
        {"external_adapter": {"evidence": invoke(ctx, "collect-evidence"), "iteration": ctx.loop_index}}
    )


@graph.step(
    "close-adapter-cycle",
    title="Close adapter cycle",
    phase="after_each",
    inputs=["adapter_evidence"],
    outputs=["cycle_complete"],
)
@runner.phase("after_each", step_id="close-adapter-cycle")
def after_each(ctx):
    """Close one adapter lifecycle iteration."""
    ctx.log("Completed one bounded external adapter cycle")


@graph.step(
    "finalize-adapter",
    title="Finalize external automation",
    phase="after_all",
    inputs=["cycle_complete"],
    outputs=["final_status"],
)
@runner.phase("after_all", step_id="finalize-adapter")
def after_all(ctx):
    """Finalize the external automation evaluation."""
    ctx.log("Finalized the external automation evaluation")


if __name__ == "__main__":
    runner.main()
