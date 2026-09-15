"""Run a portable evidence-gated probe matrix through an external tool.

Set ORBIT_PROBE_COMMAND to a JSON argument array or a shell-like command
prefix. The tool must support ``preflight``, ``prepare``, ``run-probes``, and
``collect-evidence`` actions. Every action receives ORBIT_CYCLE_INPUT and
returns one JSON object. The tool may create disposable workspaces, but it
must not schedule itself or commit changes to the target repository.
"""

import json
import os
import shlex

from orbit_sdk import graph, runner

graph.connect("preflight-probes", "prepare-probes")
graph.connect("prepare-probes", "run-probe-matrix", label="prepared inputs")
graph.connect("run-probe-matrix", "collect-probe-evidence", kind="data", label="probe report")
graph.connect("collect-probe-evidence", "close-probe-cycle")
graph.connect("close-probe-cycle", "prepare-probes", kind="loop", label="next cycle")
graph.connect("close-probe-cycle", "finalize-probe-monitor", kind="condition", label="completed")


def probe_command():
    """Read the explicit probe command prefix configured by the operator."""
    configured = os.environ.get("ORBIT_PROBE_COMMAND", "").strip()
    if not configured:
        raise ValueError("Set ORBIT_PROBE_COMMAND to the evidence-gate command")
    if configured.startswith("["):
        value = json.loads(configured)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("ORBIT_PROBE_COMMAND JSON must be an array of strings")
        return value
    return shlex.split(configured)


def cycle_input(ctx, action):
    """Pass selected probes and non-secret evaluation context to the tool."""
    return json.dumps(
        {
            "action": action,
            "iteration": ctx.loop_index,
            "build": ctx.build,
            "probes": ctx.test_cases,
        },
        ensure_ascii=False,
    )


def invoke(ctx, action):
    """Run one gate action and reject unstructured evidence early."""
    output = ctx.exec(
        [*probe_command(), action],
        cwd=ctx.project_root,
        timeout=3600,
        env={"ORBIT_CYCLE_INPUT": cycle_input(ctx, action)},
        target_log_source="evidence-probe",
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Probe action {action!r} did not return JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"Probe action {action!r} must return a JSON object")
    return result


@graph.step(
    "preflight-probes", title="Preflight probe matrix", phase="before_all", outputs=["probe_contract"]
)
@runner.phase("before_all")
def before_all(ctx):
    # A fixed probe set keeps the gate repeatable and its evidence comparable.
    if not ctx.test_cases:
        raise ValueError("Select a fixed test case set before running an evidence gate")
    preflight = invoke(ctx, "preflight")
    ctx.emit_result({"probe_gate": {"preflight": preflight}})


@graph.step(
    "prepare-probes",
    title="Prepare probes",
    phase="before_each",
    inputs=["probe_contract"],
    outputs=["prepared_probes"],
)
@runner.phase("before_each")
def before_each(ctx):
    # Prepare disposable inputs without mutating the target repository.
    prepared = invoke(ctx, "prepare")
    ctx.emit_result({"probe_gate": {"iteration": ctx.loop_index, "prepared": prepared}})


@graph.step(
    "run-probe-matrix",
    title="Run probe matrix",
    phase="execute",
    inputs=["prepared_probes"],
    outputs=["probe_report"],
)
@runner.phase("execute")
def execute(ctx):
    # Run the complete fixed matrix once and retain the tool's structured report.
    report = invoke(ctx, "run-probes")
    ctx.emit_result({"probe_gate": {"iteration": ctx.loop_index, "report": report}})


@graph.step(
    "collect-probe-evidence",
    title="Collect probe evidence",
    phase="verify",
    inputs=["probe_report"],
    outputs=["evidence_gate"],
)
@runner.phase("verify")
def verify(ctx):
    # Collect final evidence separately so a supervisor can make an independent decision.
    evidence = invoke(ctx, "collect-evidence")
    ctx.emit_result({"probe_gate": {"iteration": ctx.loop_index, "evidence": evidence}})


@graph.step(
    "close-probe-cycle",
    title="Close probe cycle",
    phase="after_each",
    inputs=["evidence_gate"],
    outputs=["cycle_complete"],
)
@runner.phase("after_each")
def after_each(ctx):
    ctx.log("Completed one evidence-gated probe matrix")


@graph.step(
    "finalize-probe-monitor",
    title="Finalize drift monitor",
    phase="after_all",
    inputs=["cycle_complete"],
    outputs=["final_status"],
)
@runner.phase("after_all")
def after_all(ctx):
    ctx.log("Finalized the evidence-gated probe evaluation")


if __name__ == "__main__":
    runner.main()
