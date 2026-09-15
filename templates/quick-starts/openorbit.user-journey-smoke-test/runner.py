from orbit_sdk import graph, runner

graph.connect("validate-browser", "run-browser-journey")
graph.connect("run-browser-journey", "verify-browser-evidence", kind="data", label="journey evidence")
graph.connect("verify-browser-evidence", "finalize-browser-evaluation")


@graph.step(
    "validate-browser", title="Validate browser target", phase="before_all", outputs=["browser_target"]
)
@runner.phase("before_all")
def before_all(ctx):
    if not ctx.build.get("browser_base_url"):
        raise ValueError("Quick start browser evaluation requires a browser base URL")


@graph.step(
    "run-browser-journey",
    title="Run browser journey",
    phase="execute",
    inputs=["browser_target"],
    outputs=["journey_evidence"],
)
@runner.phase("execute")
def execute(ctx):
    evidence = ctx.playwright_journey()
    if not all(item["passed"] for item in evidence["results"]):
        raise SystemExit("A browser journey failed")


@graph.step(
    "verify-browser-evidence",
    title="Verify journey evidence",
    phase="verify",
    inputs=["journey_evidence"],
    outputs=["journey_verdict"],
)
@runner.phase("verify")
def verify(ctx):
    ctx.log("Quick start browser evaluation completed")


@graph.step(
    "finalize-browser-evaluation",
    title="Finalize browser evaluation",
    phase="after_all",
    inputs=["journey_verdict"],
    outputs=["completed_evaluation"],
)
@runner.phase("after_all")
def after_all(ctx):
    ctx.log("Finalized the one-shot browser evaluation")


if __name__ == "__main__":
    runner.main()
