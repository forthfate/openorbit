"""Run the configured external AI evaluator through explicit runner phases.

The evaluator receives fixed test cases through ``ORBIT_CYCLE_INPUT`` and must
return one JSON object per action. Orbit retains that structured evidence for
supervision; this runner never infers an evaluation result itself.
"""

import json
import os
import shlex

from orbit_sdk import graph, runner


def invoke(ctx, action):
    """Run one external evaluator action and parse its JSON response.

    Args:
        ctx: The active Orbit runner context.
        action: The action passed to the external evaluator.

    Returns:
        The evaluator's JSON object.

    Raises:
        ValueError: If the evaluator command configuration is invalid.
        RuntimeError: If the evaluator output is not one JSON object.
    """
    raw = os.environ.get("ORBIT_AGENT_COMMAND", "").strip()
    if not raw:
        raise ValueError("Set ORBIT_AGENT_COMMAND to an external tool command")
    command = json.loads(raw) if raw.startswith("[") else shlex.split(raw)
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("ORBIT_AGENT_COMMAND must be a JSON string array or command")
    output = ctx.exec(
        [*command, action],
        cwd=ctx.project_root,
        timeout=3600,
        env={
            "ORBIT_CYCLE_INPUT": json.dumps(
                {
                    "action": action,
                    "iteration": ctx.loop_index,
                    "build": ctx.build,
                    "test_cases": ctx.test_cases,
                },
                ensure_ascii=False,
            )
        },
        target_log_source="agent-cycle",
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Action {action!r} did not return JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"Action {action!r} must return a JSON object")
    return result


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
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed test case")


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
