"""Minimal Quick Start runner using independently executable graph nodes."""

from orbit_sdk import graph, runner

graph.connect("validate-example", "run-example")
graph.connect("run-example", "finalize-example")


@graph.step("validate-example", title="Validate example", phase="before_all", outputs=["contract"])
@runner.phase("before_all", step_id="validate-example")
def validate_example(ctx):
    if not ctx.test_cases:
        raise ValueError("The example Quick Start requires one fixed test case")


@graph.step("run-example", title="Run example", phase="execute", inputs=["contract"], outputs=["evidence"])
@runner.phase("execute", step_id="run-example")
def run_example(ctx):
    ctx.emit_result(
        {
            "example_quick_start": {
                "iteration": ctx.loop_index,
                "case_ids": [str(case.get("id")) for case in ctx.test_cases],
                "status": "completed",
            }
        }
    )


@graph.step(
    "finalize-example",
    title="Finalize example",
    phase="after_all",
    inputs=["evidence"],
    outputs=["completed"],
)
@runner.phase("after_all", step_id="finalize-example")
def finalize_example(ctx):
    ctx.log("Finalized the example Quick Start")


if __name__ == "__main__":
    runner.main()
