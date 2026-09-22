"""Connect a one-shot external automation command to OpenOrbit.

Set ORBIT_ADAPTER_COMMAND to either a shell-like command string or a JSON
array. The external tool must accept the actions used below and return after
each action; OpenOrbit remains responsible for scheduling and supervision.
"""

from __future__ import annotations

from orbit_sdk import runner


def invoke(ctx, action):
    """Run exactly one adapter action and preserve its output as run evidence."""
    output = ctx.run_command_action(
        command_env="ORBIT_ADAPTER_COMMAND",
        action=action,
        timeout=3_600,
        log_source="external-adapter",
    )
    artifact = ctx.write_artifact(
        f"external-command/{action}.log", output, content_type="text/plain; charset=utf-8"
    )
    return {"action": action, "output": output[-4_000:], "artifact": artifact}


@runner.phase("before_all")
def before_all(ctx):
    result = invoke(ctx, "status")
    ctx.emit_result({"external_command": {"readiness": result}})


@runner.phase("before_each")
def before_each(ctx):
    result = invoke(ctx, "prepare")
    ctx.emit_result({"external_command": {"preparation": result}})


@runner.phase("execute")
def execute(ctx):
    result = invoke(ctx, "run-once")
    ctx.emit_result({"external_command": {"execution": result}})


@runner.phase("verify")
def verify(ctx):
    result = invoke(ctx, "collect-evidence")
    ctx.emit_result({"external_command": {"evidence": result}})


@runner.phase("after_each")
def after_each(ctx):
    ctx.log("Completed the bounded external command")


@runner.phase("after_all")
def after_all(ctx):
    ctx.log("Finalized the external command evaluation")


if __name__ == "__main__":
    runner.main()
