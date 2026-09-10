"""Connect a one-shot external automation command to OpenOrbit.

Set ORBIT_ADAPTER_COMMAND to either a shell-like command string or a JSON
array. The external tool must accept the actions used below and return after
each action; OpenOrbit remains responsible for scheduling and supervision.
"""

from __future__ import annotations

import json
import os
import shlex

from orbit_sdk import runner


def adapter_command():
    """Read explicit command configuration without coupling to a repository path."""
    configured = os.environ.get("ORBIT_ADAPTER_COMMAND", "").strip()
    if not configured:
        raise ValueError("Set ORBIT_ADAPTER_COMMAND to an external tool command")
    if configured.startswith("["):
        command = json.loads(configured)
        if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
            raise ValueError("ORBIT_ADAPTER_COMMAND JSON must be an array of strings")
        return command
    return shlex.split(configured)


def invoke(ctx, action):
    """Run exactly one adapter action and preserve its output as run evidence."""
    output = ctx.exec([*adapter_command(), action], cwd=ctx.project_root, timeout=3_600)
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
