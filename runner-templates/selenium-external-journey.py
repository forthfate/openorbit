"""Reference adapter runner for teams that already operate Selenium journeys."""

import json
import os
import shlex

from orbit_sdk import graph, runner

graph.connect("ready", "prepare")
graph.connect("prepare", "run", kind="data", label="one Selenium cycle")
graph.connect("run", "collect")


def command():
    """Read an explicit adapter command without embedding target credentials."""
    configured = os.environ.get("ORBIT_SELENIUM_COMMAND", "").strip()
    if not configured:
        raise ValueError(
            "Set ORBIT_SELENIUM_COMMAND to an adapter supporting status, prepare, run-once, and collect-evidence"
        )
    value = json.loads(configured) if configured.startswith("[") else shlex.split(configured)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ValueError("ORBIT_SELENIUM_COMMAND must resolve to a non-empty string command list")
    return value


def invoke(ctx, action):
    # One bounded call per phase: the adapter must never start its own daemon.
    return ctx.exec([*command(), action], cwd=ctx.project_root, timeout=3600)


def evidence(value):
    """Bound adapter output before it becomes retained OpenOrbit evidence."""
    text = str(value).strip()
    return text[:4000] if text else "(adapter returned no output)"


@graph.step("ready", title="Check Selenium adapter", phase="before_all", outputs=["adapter_status"])
@runner.phase("before_all")
def before_all(ctx):
    status = evidence(invoke(ctx, "status"))
    ctx.emit_result({"selenium_journey": {"status": status}})
    ctx.log("Validated the Selenium adapter contract")


@graph.step(
    "prepare",
    title="Prepare Selenium cycle",
    phase="before_each",
    inputs=["adapter_status"],
    outputs=["prepared_cycle"],
)
@runner.phase("before_each")
def before_each(ctx):
    prepared = evidence(invoke(ctx, "prepare"))
    ctx.emit_result({"selenium_journey": {"iteration": ctx.loop_index, "prepared": prepared}})
    ctx.log("Prepared one Selenium adapter cycle")


@graph.step(
    "run",
    title="Run Selenium journey",
    phase="execute",
    inputs=["prepared_cycle"],
    outputs=["journey_result"],
)
@runner.phase("execute")
def execute(ctx):
    result = evidence(invoke(ctx, "run-once"))
    ctx.emit_result({"selenium_journey": {"iteration": ctx.loop_index, "result": result}})
    ctx.target_log("Selenium adapter completed one bounded journey", level="info", source="selenium-adapter")


@graph.step(
    "collect",
    title="Collect Selenium evidence",
    phase="verify",
    inputs=["journey_result"],
    outputs=["journey_evidence"],
)
@runner.phase("verify")
def verify(ctx):
    collected = evidence(invoke(ctx, "collect-evidence"))
    ctx.emit_result({"selenium_journey": {"iteration": ctx.loop_index, "evidence": collected}})
    ctx.save_data_file(
        f"selenium-journey/iteration-{ctx.loop_index}.txt",
        collected,
        label="Selenium adapter evidence",
        content_type="text/plain",
    )


@runner.phase("after_each")
def after_each(ctx):
    ctx.log("Completed one bounded Selenium adapter cycle")


@runner.phase("after_all")
def after_all(ctx):
    ctx.log("Finalized the Selenium adapter evaluation")


if __name__ == "__main__":
    runner.main()
