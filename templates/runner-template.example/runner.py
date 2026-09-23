from orbit_sdk import graph, runner

graph.connect("validate-example", "run-example")
graph.connect("run-example", "finalize-example")


@graph.step(
    "validate-example",
    title="Validate example contract",
    phase="before_all",
    outputs=["example_contract"],
)
@runner.phase("before_all", step_id="validate-example")
def validate_example(ctx):
    ctx.log("Validated the example runner contract")


@graph.step(
    "run-example",
    title="Run example task",
    phase="execute",
    inputs=["example_contract"],
    outputs=["example_result"],
)
@runner.phase("execute", step_id="run-example")
def execute(ctx):
    ctx.emit_result({"example_runner": {"iteration": ctx.loop_index, "status": "completed"}})
    ctx.log("Example runner executed")


@graph.step(
    "finalize-example",
    title="Finalize example task",
    phase="after_all",
    inputs=["example_result"],
    outputs=["example_complete"],
)
@runner.phase("after_all", step_id="finalize-example")
def finalize_example(ctx):
    ctx.log("Finalized the example runner")


if __name__ == "__main__":
    runner.main()
