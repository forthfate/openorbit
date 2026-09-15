# Requirements
# - The target application is running at the build's browser base URL.
# - The build selects at least one fixed test case.
# - Playwright Chromium and its operating-system libraries are available.
# No external runner script, adapter repository, or background program is required.

import json
import re

from orbit_sdk import graph, runner

graph.connect("validate-journey", "plan-journey")
graph.connect("plan-journey", "run-journey", label="focused cases")
graph.connect("run-journey", "review-journey", kind="data", label="browser evidence")
graph.connect("review-journey", "retain-journey")
graph.connect("retain-journey", "plan-journey", kind="loop", label="next iteration")
graph.connect("retain-journey", "finalize-journey", kind="condition", label="completed")


# Validate only configuration that the runner cannot safely infer. This runs
# once when an evaluation process starts, before its iteration loop.
def validate(ctx):
    build = ctx.build
    if not build.get("browser_base_url"):
        raise ValueError("Set a browser base URL on the build")
    if not ctx.test_cases:
        raise ValueError("Select a fixed test case set before running a user journey")


def state_path(ctx):
    # Keep state in OpenOrbit AppData, keyed by build, so a later iteration can
    # resume its focused journey without writing into the target repository.
    build_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(ctx.build.get("id") or "manual"))
    directory = ctx.app_data / "user-journey-state"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{build_id}.json"


def load_state(ctx):
    # A build's first iteration begins with an empty rotation and no failures.
    path = state_path(ctx)
    if not path.exists():
        return {"next_case_index": 0, "failed_case_ids": [], "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(ctx, state):
    # Retain a bounded history so a long-running evaluation does not grow
    # indefinitely while still preserving useful handoffs.
    state["history"] = state.get("history", [])[-24:]
    state_path(ctx).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def plan(ctx, state):
    # Supervisor feedback from the completed prior iteration is an input to
    # planning, not a replacement for browser-observable evidence.
    feedback = ctx.previous_supervisor_feedback
    failed = set(state.get("failed_case_ids", []))
    cases = ctx.test_cases
    # Failed cases take precedence; otherwise rotate through fixed cases one at
    # a time to keep each scheduled iteration bounded and explainable.
    focused = [case for case in cases if case.get("id") in failed]
    if not focused:
        index = int(state.get("next_case_index", 0)) % len(cases)
        focused = [cases[index]]
    rules = [
        "Preserve observable evidence for every browser action.",
        "Do not infer a result that the page did not expose.",
    ]
    if failed:
        rules.insert(0, "Revisit previously failed journeys before exploring a new route.")
    if feedback.get("reported_issues"):
        rules.insert(0, "Prioritize the supervisor's previously reported issues.")
    reason = (
        "Previously failed journeys require confirmation."
        if failed
        else "Rotate one fixed journey to retain broad, bounded coverage."
    )
    return {
        "case_ids": [str(case.get("id")) for case in focused],
        "rules": rules,
        "reason": reason,
        "supervisor_feedback": feedback,
    }


@graph.step(
    "validate-journey", title="Validate journey contract", phase="before_all", outputs=["journey_contract"]
)
@runner.phase("before_all")
def before_all(ctx):
    # Process-level preparation: run once before OpenOrbit starts repeating.
    validate(ctx)
    ctx.log("Validated the bounded user-journey contract")


@graph.step(
    "plan-journey",
    title="Plan focused journey",
    phase="before_each",
    inputs=["journey_contract"],
    outputs=["journey_plan"],
)
@runner.phase("before_each")
def before_each(ctx):
    # Iteration-level preparation: persist a plan that the execute phase consumes.
    state = load_state(ctx)
    journey_plan = plan(ctx, state)
    state["plan"] = journey_plan
    save_state(ctx, state)
    ctx.emit_result(
        {
            "user_journey": {
                "iteration": ctx.loop_index,
                "case_count": len(ctx.test_cases),
                "plan": journey_plan,
            }
        }
    )
    ctx.log(f"Planned {len(journey_plan['case_ids'])} focused journey case(s): {journey_plan['reason']}")


@graph.step(
    "run-journey",
    title="Run browser journey",
    phase="execute",
    inputs=["journey_plan"],
    outputs=["journey_evidence"],
)
@runner.phase("execute")
def execute(ctx):
    # Execute only the focused fixed cases; Playwright returns screenshots and
    # page evidence that can be inspected by both users and the supervisor.
    state = load_state(ctx)
    journey_plan = state.get("plan") or plan(ctx, state)
    case_ids = set(journey_plan["case_ids"])
    focused_cases = [case for case in ctx.test_cases if str(case.get("id")) in case_ids]
    evidence = ctx.playwright_journey(focused_cases)
    results = evidence["results"]
    passed = len([item for item in results if item["passed"]])
    failed = [str(item.get("id")) for item in results if not item["passed"]]
    state["failed_case_ids"] = failed
    state["next_case_index"] = (int(state.get("next_case_index", 0)) + 1) % len(ctx.test_cases)
    # This compact handoff is the explicit input to the next scheduled cycle.
    state["handoff"] = {
        "iteration": ctx.loop_index,
        "reason": journey_plan["reason"],
        "rules": journey_plan["rules"],
        "passed": passed,
        "failed": len(results) - passed,
        "failed_case_ids": failed,
    }
    state.setdefault("history", []).append(state["handoff"])
    save_state(ctx, state)
    ctx.emit_result(
        {
            "user_journey": {
                "iteration": ctx.loop_index,
                "plan": journey_plan,
                "passed": passed,
                "failed": len(results) - passed,
                "results": results,
                "evidence": evidence,
                "handoff": state["handoff"],
            }
        }
    )


@graph.step(
    "review-journey",
    title="Review journey evidence",
    phase="verify",
    inputs=["journey_evidence"],
    outputs=["journey_handoff"],
)
@runner.phase("verify")
def verify(ctx):
    # Expose the persisted handoff as structured run output for supervision.
    state = load_state(ctx)
    ctx.emit_result(
        {"user_journey": {"next_iteration": state.get("handoff", {}), "state_path": str(state_path(ctx))}}
    )
    ctx.log("Stored the journey summary, reasons, and behavior rules for the next iteration")


@graph.step(
    "retain-journey",
    title="Retain journey result",
    phase="after_each",
    inputs=["journey_handoff"],
    outputs=["iteration_complete"],
)
@runner.phase("after_each")
def after_each(ctx):
    ctx.log("Closed this bounded browser journey")


@graph.step(
    "finalize-journey",
    title="Finalize journey evaluation",
    phase="after_all",
    inputs=["iteration_complete"],
    outputs=["final_status"],
)
@runner.phase("after_all")
def after_all(ctx):
    ctx.log("Finalized the user-journey evaluation")


if __name__ == "__main__":
    runner.main()
