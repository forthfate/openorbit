"""Run one bounded browser journey per OpenOrbit iteration.

Copy this file into Assets > Runners when a build has a browser
base URL and one or more fixed test cases. OpenOrbit owns scheduling; this
runner only chooses and executes one focused journey for each iteration.
"""

from __future__ import annotations

import json
import re

from orbit_sdk import runner


def state_path(ctx):
    """Keep runner state outside the evaluated repository and keyed by build."""
    build_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(ctx.build.get("id") or "manual"))
    directory = ctx.app_data / "sample-user-journey-state"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{build_id}.json"


def load_state(ctx):
    path = state_path(ctx)
    if not path.exists():
        return {"next_case_index": 0, "failed_case_ids": [], "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(ctx, state):
    """Bound history so a recurring evaluation does not grow without limit."""
    state["history"] = state.get("history", [])[-24:]
    state_path(ctx).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def focused_cases(ctx, state):
    """Retest failures first; otherwise rotate a single fixed case."""
    failures = set(state.get("failed_case_ids", []))
    failed_cases = [case for case in ctx.test_cases if str(case.get("id")) in failures]
    if failed_cases:
        return failed_cases, "Rechecking a previously failed journey."
    index = int(state.get("next_case_index", 0)) % len(ctx.test_cases)
    return [ctx.test_cases[index]], "Rotating through fixed journeys."


@runner.phase("before_all")
def before_all(ctx):
    if not ctx.build.get("browser_base_url"):
        raise ValueError("Set a browser base URL on the build")
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed test case")
    ctx.log("Validated the browser journey configuration")


@runner.phase("before_each")
def before_each(ctx):
    state = load_state(ctx)
    cases, reason = focused_cases(ctx, state)
    state["plan"] = {"case_ids": [str(case.get("id")) for case in cases], "reason": reason}
    save_state(ctx, state)
    ctx.emit_result({"user_journey": {"iteration": ctx.loop_index, "plan": state["plan"]}})
    ctx.log(reason)


@runner.phase("execute")
def execute(ctx):
    state = load_state(ctx)
    planned_ids = set((state.get("plan") or {}).get("case_ids", []))
    cases = [case for case in ctx.test_cases if str(case.get("id")) in planned_ids]
    evidence = ctx.playwright_journey(cases)
    results = evidence["results"]
    failed_ids = [str(item.get("id")) for item in results if not item["passed"]]
    state["failed_case_ids"] = failed_ids
    state["next_case_index"] = (int(state.get("next_case_index", 0)) + 1) % len(ctx.test_cases)
    handoff = {
        "iteration": ctx.loop_index,
        "passed": len(results) - len(failed_ids),
        "failed": len(failed_ids),
        "failed_case_ids": failed_ids,
    }
    state.setdefault("history", []).append(handoff)
    save_state(ctx, state)
    ctx.emit_result({"user_journey": {"evidence": evidence, "handoff": handoff}})


@runner.phase("verify")
def verify(ctx):
    state = load_state(ctx)
    ctx.emit_result({"user_journey": {"next_iteration": state.get("history", [])[-1:]}})
    ctx.log("Published browser evidence and the next-iteration handoff")


@runner.phase("after_each")
def after_each(ctx):
    ctx.log("Completed one bounded browser journey")


@runner.phase("after_all")
def after_all(ctx):
    ctx.log("Finalized the user-journey evaluation")


if __name__ == "__main__":
    runner.main()
