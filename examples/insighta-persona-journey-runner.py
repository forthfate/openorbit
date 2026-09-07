"""Orbit adapter for one bounded Insighta user-simulator cycle.

Orbit owns repetition and supervision. The original simulator owns persona
planning, Selenium interactions, source-backed evidence, and persona memory.
This adapter invokes ``run-once`` only; it never starts the simulator daemon.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from orbit_sdk import runner

SIMULATOR_ROOT = Path(
    os.environ.get("INSIGHTA_SIMULATOR_ROOT", "/home/forth/projects/insighta-user-simulator")
).expanduser()


def simulator_command() -> list[str]:
    command = SIMULATOR_ROOT / ".venv" / "bin" / "insighta-sim"
    if not command.is_file():
        raise RuntimeError(
            "Insighta user simulator is unavailable. Set INSIGHTA_SIMULATOR_ROOT to its project directory."
        )
    return [str(command)]


def invoke(*arguments: str) -> Any:
    completed = subprocess.run(
        [*simulator_command(), *arguments],
        cwd=SIMULATOR_ROOT,
        capture_output=True,
        text=True,
        timeout=3_600,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise RuntimeError(f"Insighta simulator {' '.join(arguments)} failed: {detail[-4_000:]}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Insighta simulator returned non-JSON output") from error


def event_evidence(path: str) -> dict[str, Any]:
    """Load the simulator's normalized, redacted session record for supervision."""
    event_path = Path(path)
    if not event_path.is_file():
        raise RuntimeError(f"Simulator reported a missing event record: {event_path}")
    lines = [line for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"Simulator event record is empty: {event_path}")
    event = json.loads(lines[-1])
    browser = event.get("browser", {})
    return {
        "persona": event.get("persona_id"),
        "timestamp": event.get("timestamp"),
        "intent": event.get("intent"),
        "actions": event.get("actions", []),
        "executed": browser.get("executed", []),
        "browser_errors": browser.get("browser_errors", []),
        "console_errors": browser.get("console_errors", []),
        "observation": browser.get("page", {}).get("observation", {}),
        "bugs": event.get("bugs", []),
        "usefulness_assessment": event.get("usefulness_assessment", {}),
        "investment_decision": event.get("investment_decision", {}),
        "recorded_changes": event.get("recorded_changes", []),
        "event_path": str(event_path),
    }


def status_summary(status: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep operational context useful without copying prior screen transcripts."""
    return [
        {
            "persona": item.get("persona"),
            "active": item.get("active"),
            "local_day": item.get("local_day"),
            "last_action_at": item.get("state", {}).get("last_action_at"),
            "memory_day": item.get("state", {}).get("memory_day"),
            "memory_summary": str(item.get("state", {}).get("memory", ""))[-1_000:],
        }
        for item in status
    ]


@runner.phase("init")
def init(ctx):
    # Validate the external simulator once before Orbit starts its iteration loop.
    status = invoke("status")
    ctx.emit_result(
        {"persona_cycle": {"simulator_root": str(SIMULATOR_ROOT), "personas": status_summary(status)}}
    )
    ctx.log("Validated the original Insighta user simulator; Orbit will invoke bounded run-once cycles.")


@runner.phase("setup")
def setup(ctx):
    # Keep the ownership boundary explicit: Orbit schedules; the simulator does not.
    ctx.log("Orbit scheduler is ready; the simulator daemon remains stopped.")


@runner.phase("run")
def run(ctx):
    # Request one bounded simulator cycle and normalize its evidence for review.
    sessions = invoke("run-once")
    evidence = [event_evidence(item["event"]) for item in sessions]
    ctx.emit_result(
        {
            "persona_cycle": {
                "simulator_root": str(SIMULATOR_ROOT),
                "processed_personas": evidence,
                "processed_count": len(evidence),
            }
        }
    )
    ctx.log(json.dumps({"processed_personas": evidence}, ensure_ascii=False))


@runner.phase("eval")
def evaluate(ctx):
    # Publish the post-cycle persona state without replaying the completed work.
    status = invoke("status")
    summary = status_summary(status)
    ctx.emit_result({"persona_cycle": {"persona_status": summary}})
    ctx.log(json.dumps({"persona_status": summary}, ensure_ascii=False))


@runner.phase("teardown")
def teardown(ctx):
    # Per-iteration cleanup is limited to reporting because no daemon was started.
    ctx.log("Completed one original Insighta simulator cycle without starting its daemon.")


@runner.phase("finalize")
def finalize(ctx):
    # Leave the external simulator untouched when the Orbit-managed process exits.
    ctx.log("Finalized the Orbit-managed Insighta persona evaluation.")


if __name__ == "__main__":
    runner.main()
