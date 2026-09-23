"""Run a recurring browser journey with phases declared in this runner.

The runner retries failed fixed cases before rotating through the journey set.
It persists only bounded state and rendered evidence, so the supervisor can
review what happened without relying on hidden lifecycle helpers.
"""

import json

from orbit_sdk import graph, runner

NAMESPACE = "user_journey"

graph.connect("validate-user-journey-runtime", "validate-user-journey")
graph.connect("validate-user-journey", "load-user-journey-state")
graph.connect("load-user-journey-state", "plan-user-journey")
graph.connect("plan-user-journey", "run-user-journey", label="focused cases")
graph.connect("run-user-journey", "review-user-journey", kind="data", label="browser evidence")
graph.connect("review-user-journey", "retain-user-journey")
graph.connect("retain-user-journey", "plan-user-journey", kind="loop", label="next iteration")
graph.connect("retain-user-journey", "finalize-user-journey", kind="condition", label="completed")


def state(ctx):
    """Load the bounded state used to choose the next browser journey.

    Args:
        ctx: The active Orbit runner context.

    Returns:
        Persisted journey state, initialized for a new build when absent.
    """
    return ctx.load_state(NAMESPACE, {"next_case_index": 0, "failed_case_ids": [], "history": []})


@graph.step(
    "validate-user-journey-runtime",
    title="Validate user journey runtime",
    phase="before_all",
    outputs=["browser_runtime"],
)
@runner.phase("before_all", step_id="validate-user-journey-runtime")
def validate_runtime(ctx):
    """Validate the browser base URL before the recurring journey starts."""
    if not ctx.build.get("browser_base_url"):
        raise ValueError("Set required build field(s): browser_base_url")
    ctx.log("Validated the browser runtime target")


@graph.step(
    "validate-user-journey",
    title="Validate user journey contract",
    phase="before_all",
    inputs=["browser_runtime"],
    outputs=["journey_contract"],
)
@runner.phase("before_all", step_id="validate-user-journey")
def validate_contract(ctx):
    """Require fixed journey cases for reproducible coverage."""
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed journey case before running this runner")
    ctx.log("Validated the user journey contract")


@graph.step(
    "load-user-journey-state",
    title="Load user journey state",
    phase="before_each",
    inputs=["journey_contract"],
    outputs=["journey_state"],
)
@runner.phase("before_each", step_id="load-user-journey-state")
def load_state(ctx):
    """Persist an initialized state document for this iteration."""
    ctx.save_state(NAMESPACE, state(ctx))


@graph.step(
    "plan-user-journey",
    title="Plan focused user journey",
    phase="before_each",
    inputs=["journey_state"],
    outputs=["journey_plan"],
)
@runner.phase("before_each", step_id="plan-user-journey")
def plan(ctx):
    """Choose failed cases first, then rotate through the fixed case set."""
    current = state(ctx)
    failed = bool(current.get("failed_case_ids"))
    failed_ids = {str(case_id) for case_id in current.get("failed_case_ids", [])}
    cases = [case for case in ctx.test_cases if str(case.get("id")) in failed_ids]
    if not cases:
        cases = [ctx.test_cases[int(current.get("next_case_index", 0)) % len(ctx.test_cases)]]
    rules = [
        "Preserve observable evidence for every browser action.",
        "Do not infer a result that the page did not expose.",
    ]
    if failed:
        rules.insert(0, "Revisit previously failed journeys before exploring a new route.")
    if ctx.previous_supervisor_feedback.get("reported_issues"):
        rules.insert(0, "Prioritize the supervisor's previously reported issues.")
    plan_data = {
        "case_ids": [str(case.get("id")) for case in cases],
        "reason": "Revisit previously failed journeys."
        if failed
        else "Rotate one fixed journey to retain bounded coverage.",
        "rules": rules,
        "supervisor_feedback": ctx.previous_supervisor_feedback,
    }
    current["plan"] = plan_data
    ctx.save_state(NAMESPACE, current)
    ctx.emit_result(
        {NAMESPACE: {"iteration": ctx.loop_index, "case_count": len(ctx.test_cases), "plan": plan_data}}
    )


@graph.step(
    "run-user-journey",
    title="Run user journey",
    phase="execute",
    inputs=["journey_plan"],
    outputs=["journey_evidence"],
)
@runner.phase("execute", step_id="run-user-journey")
def execute(ctx):
    """Run the focused browser cases and retain evidence plus next state."""
    current = state(ctx)
    ids = set(current["plan"]["case_ids"])
    evidence = ctx.playwright_journey([case for case in ctx.test_cases if str(case.get("id")) in ids])
    results = list(evidence.get("results", []))
    current["failed_case_ids"] = [str(item.get("id")) for item in results if not item.get("passed")]
    current["next_case_index"] = (int(current.get("next_case_index", 0)) + 1) % len(ctx.test_cases)
    handoff = {
        "iteration": ctx.loop_index,
        "reason": current["plan"]["reason"],
        "rules": current["plan"]["rules"],
        "passed": len(results) - len(current["failed_case_ids"]),
        "failed": len(current["failed_case_ids"]),
        "failed_case_ids": current["failed_case_ids"],
    }
    current["history"] = [*current.get("history", []), handoff][-24:]
    current["handoff"] = handoff
    ctx.save_state(NAMESPACE, current)
    artifact = ctx.save_data_file(
        f"{NAMESPACE}/iteration-{ctx.loop_index}.json",
        json.dumps(
            {"plan": current["plan"], "evidence": evidence, "handoff": handoff}, ensure_ascii=False, indent=2
        ),
        label="User journey iteration evidence",
        content_type="application/json",
    )
    ctx.emit_result(
        {
            NAMESPACE: {
                "iteration": ctx.loop_index,
                "plan": current["plan"],
                "results": results,
                "evidence": evidence,
                "handoff": handoff,
                "artifact": artifact,
            }
        }
    )


@graph.step(
    "review-user-journey",
    title="Review user journey evidence",
    phase="verify",
    inputs=["journey_evidence"],
    outputs=["journey_handoff"],
)
@runner.phase("verify", step_id="review-user-journey")
def verify(ctx):
    """Expose the next-iteration handoff to the supervisor."""
    ctx.emit_result({NAMESPACE: {"next_iteration": state(ctx).get("handoff", {})}})
    ctx.log("Stored the journey summary and next-iteration handoff")


@graph.step(
    "retain-user-journey",
    title="Retain user journey result",
    phase="after_each",
    inputs=["journey_handoff"],
    outputs=["iteration_complete"],
)
@runner.phase("after_each", step_id="retain-user-journey")
def after_each(ctx):
    """Close the current bounded journey iteration."""
    ctx.log("Closed this bounded user journey")


@graph.step(
    "finalize-user-journey",
    title="Finalize user journey evaluation",
    phase="after_all",
    inputs=["iteration_complete"],
    outputs=["final_status"],
)
@runner.phase("after_all", step_id="finalize-user-journey")
def after_all(ctx):
    """Finalize the recurring journey after its last iteration."""
    ctx.log("Finalized the user journey evaluation")


if __name__ == "__main__":
    runner.main()
