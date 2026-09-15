"""Run a portable, bounded external agent cycle.

Set ORBIT_AGENT_COMMAND to a JSON argument array or a shell-like command
prefix. The external tool receives one action at a time: ``status`` or
``run-once``. It must write one JSON object to stdout and must never start a
daemon or scheduler; OpenOrbit owns repetition, timing, and supervision.
"""

import json
import os
import shlex

from orbit_sdk import graph, runner

graph.connect("check-agent", "record-inputs")
graph.connect("record-inputs", "run-agent", label="bounded input")
graph.connect("run-agent", "confirm-agent-state", kind="data", label="agent result")
graph.connect("confirm-agent-state", "close-cycle")
graph.connect("close-cycle", "record-inputs", kind="loop", label="next cycle")
graph.connect("close-cycle", "finalize-agent", kind="condition", label="completed")


def agent_command():
    """Read an explicit command prefix without depending on target source files."""
    configured = os.environ.get("ORBIT_AGENT_COMMAND", "").strip()
    if not configured:
        raise ValueError("Set ORBIT_AGENT_COMMAND to the external agent command")
    if configured.startswith("["):
        value = json.loads(configured)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("ORBIT_AGENT_COMMAND JSON must be an array of strings")
        return value
    return shlex.split(configured)


def cycle_input(ctx, action):
    """Expose non-secret evaluation context through one documented JSON contract."""
    return json.dumps(
        {
            "action": action,
            "iteration": ctx.loop_index,
            "build": ctx.build,
            "test_cases": ctx.test_cases,
        },
        ensure_ascii=False,
    )


def invoke(ctx, action):
    """Run one bounded action and require structured evidence from the agent."""
    output = ctx.exec(
        [*agent_command(), action],
        cwd=ctx.project_root,
        timeout=3600,
        env={"ORBIT_CYCLE_INPUT": cycle_input(ctx, action)},
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"External agent action {action!r} did not return JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"External agent action {action!r} must return a JSON object")
    return result


@graph.step("check-agent", title="Check agent readiness", phase="before_all", outputs=["agent_status"])
@runner.phase("before_all")
def before_all(ctx):
    # Check availability once; later phases must not start an independent loop.
    status = invoke(ctx, "status")
    ctx.emit_result({"agent_cycle": {"status": status}})


@graph.step(
    "record-inputs",
    title="Record cycle inputs",
    phase="before_each",
    inputs=["agent_status"],
    outputs=["cycle_input"],
)
@runner.phase("before_each")
def before_each(ctx):
    # Record the fixed inputs so every external action is auditable.
    ctx.emit_result(
        {
            "agent_cycle": {
                "iteration": ctx.loop_index,
                "test_case_ids": [str(case.get("id", "")) for case in ctx.test_cases],
            }
        }
    )


@graph.step(
    "run-agent",
    title="Run bounded agent cycle",
    phase="execute",
    inputs=["cycle_input"],
    outputs=["agent_result"],
)
@runner.phase("execute")
def execute(ctx):
    # Exactly one unit of agent work; OpenOrbit schedules a future iteration.
    result = invoke(ctx, "run-once")
    ctx.emit_result({"agent_cycle": {"iteration": ctx.loop_index, "result": result}})


@graph.step(
    "confirm-agent-state",
    title="Confirm agent state",
    phase="verify",
    inputs=["agent_result"],
    outputs=["verified_status"],
)
@runner.phase("verify")
def verify(ctx):
    # Re-read status rather than assuming the prior action completed correctly.
    status = invoke(ctx, "status")
    ctx.emit_result({"agent_cycle": {"iteration": ctx.loop_index, "status": status}})


@graph.step(
    "close-cycle",
    title="Close cycle",
    phase="after_each",
    inputs=["verified_status"],
    outputs=["cycle_complete"],
)
@runner.phase("after_each")
def after_each(ctx):
    # The external process has already returned; no daemon cleanup is required.
    ctx.log("Completed one bounded external agent cycle")


@graph.step(
    "finalize-agent",
    title="Finalize agent evaluation",
    phase="after_all",
    inputs=["cycle_complete"],
    outputs=["final_status"],
)
@runner.phase("after_all")
def after_all(ctx):
    ctx.log("Finalized the external agent evaluation")


if __name__ == "__main__":
    runner.main()
