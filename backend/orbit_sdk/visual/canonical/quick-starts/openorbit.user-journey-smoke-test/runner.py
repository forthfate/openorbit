"""Run fixed browser smoke tests through explicit lifecycle phases.

The runner validates the declared browser target and journey cases, retains the
rendered evidence, and fails the run if any declared journey does not pass.
"""

from orbit_sdk import graph, runner

graph.connect("validate-browser-runtime", "validate-browser-journey")
graph.connect("validate-browser-journey", "run-browser-journey")
graph.connect("run-browser-journey", "verify-browser-evidence", kind="data", label="journey evidence")
graph.connect("verify-browser-evidence", "finalize-browser-evaluation")


@graph.step(
    "validate-browser-runtime",
    title="Validate browser runtime",
    phase="before_all",
    outputs=["browser_target"],
)
@runner.phase("before_all", step_id="validate-browser-runtime")
def validate_runtime(ctx):
    """Validate the browser target before running the smoke test."""
    if not ctx.build.get("browser_base_url"):
        raise ValueError("Set required build field(s): browser_base_url")


@graph.step(
    "validate-browser-journey",
    title="Validate browser journey contract",
    phase="before_all",
    inputs=["browser_target"],
    outputs=["journey_contract"],
)
@runner.phase("before_all", step_id="validate-browser-journey")
def validate_contract(ctx):
    """Require fixed browser journey cases."""
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed journey case before running this runner")


@graph.step(
    "run-browser-journey",
    title="Run browser journey",
    phase="execute",
    inputs=["journey_contract"],
    outputs=["journey_evidence"],
)
@runner.phase("execute", step_id="run-browser-journey")
def execute(ctx):
    """Run the declared journeys and fail when any journey does not pass."""
    evidence = ctx.playwright_journey()
    ctx.emit_result({"browser_smoke": {"iteration": ctx.loop_index, "evidence": evidence}})
    if not all(item.get("passed") for item in evidence.get("results", [])):
        raise SystemExit("A browser journey failed")


@graph.step(
    "verify-browser-evidence",
    title="Verify journey evidence",
    phase="verify",
    inputs=["journey_evidence"],
    outputs=["journey_verdict"],
)
@runner.phase("verify", step_id="verify-browser-evidence")
def verify(ctx):
    """Publish the retained browser evidence for review."""
    ctx.log("Quick start browser evaluation completed")


@graph.step(
    "finalize-browser-evaluation",
    title="Finalize browser evaluation",
    phase="after_all",
    inputs=["journey_verdict"],
    outputs=["completed_evaluation"],
)
@runner.phase("after_all", step_id="finalize-browser-evaluation")
def after_all(ctx):
    """Record completion of the one-shot smoke evaluation."""
    ctx.log("Finalized the one-shot browser evaluation")


if __name__ == "__main__":
    runner.main()
