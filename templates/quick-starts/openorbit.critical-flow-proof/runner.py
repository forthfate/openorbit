"""Prove critical browser flows with an explicit recurring lifecycle.

The runner retries failed fixed cases before rotating to the next case. Every
iteration retains rendered browser evidence and a bounded state handoff for
supervisor review.
"""

import json

from orbit_sdk import graph, runner

NAMESPACE = "continuous_journey"

graph.connect("validate-critical-flow-runtime", "validate-critical-flow")
graph.connect("validate-critical-flow", "load-critical-flow-state")
graph.connect("load-critical-flow-state", "plan-critical-flow")
graph.connect("plan-critical-flow", "run-critical-flow", label="focused cases")
graph.connect("run-critical-flow", "review-critical-flow", kind="data", label="browser evidence")
graph.connect("review-critical-flow", "retain-critical-flow")
graph.connect("retain-critical-flow", "plan-critical-flow", kind="loop", label="next iteration")
graph.connect("retain-critical-flow", "finalize-critical-flow", kind="condition", label="completed")


def state(ctx):
    """Load state used to focus the next critical-flow visit.

    Args:
        ctx: The active Orbit runner context.

    Returns:
        Persisted critical-flow state, initialized on the first iteration.
    """
    return ctx.load_state(NAMESPACE, {"next_case_index": 0, "failed_case_ids": [], "history": []})


@graph.step(
    "validate-critical-flow-runtime",
    title="Validate critical flow runtime",
    phase="before_all",
    outputs=["browser_runtime"],
)
@runner.phase("before_all", step_id="validate-critical-flow-runtime")
def validate_runtime(ctx):
    """Validate the configured browser target."""
    if not ctx.build.get("browser_base_url"):
        raise ValueError("Set required build field(s): browser_base_url")
    ctx.log("Validated the browser runtime target")


@graph.step(
    "validate-critical-flow",
    title="Validate critical flow contract",
    phase="before_all",
    inputs=["browser_runtime"],
    outputs=["journey_contract"],
)
@runner.phase("before_all", step_id="validate-critical-flow")
def validate_contract(ctx):
    """Require a fixed critical-flow case set."""
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed journey case before running this runner")
    ctx.log("Validated the critical flow contract")


@graph.step(
    "load-critical-flow-state",
    title="Load critical flow state",
    phase="before_each",
    inputs=["journey_contract"],
    outputs=["journey_state"],
)
@runner.phase("before_each", step_id="load-critical-flow-state")
def load_state(ctx):
    """Ensure a state document exists before planning."""
    ctx.save_state(NAMESPACE, state(ctx))


@graph.step(
    "plan-critical-flow",
    title="Plan focused critical flow",
    phase="before_each",
    inputs=["journey_state"],
    outputs=["journey_plan"],
)
@runner.phase("before_each", step_id="plan-critical-flow")
def plan(ctx):
    """Retry failed flows before rotating through fixed flows."""
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
    "run-critical-flow",
    title="Run critical flow",
    phase="execute",
    inputs=["journey_plan"],
    outputs=["journey_evidence"],
)
@runner.phase("execute", step_id="run-critical-flow")
def execute(ctx):
    """Run focused critical-flow cases and save their evidence."""
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
        label="Critical flow iteration evidence",
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
    "review-critical-flow",
    title="Review critical flow evidence",
    phase="verify",
    inputs=["journey_evidence"],
    outputs=["journey_handoff"],
)
@runner.phase("verify", step_id="review-critical-flow")
def verify(ctx):
    """Publish the handoff used by the next iteration."""
    ctx.emit_result({NAMESPACE: {"next_iteration": state(ctx).get("handoff", {})}})
    ctx.log("Stored the journey summary and next-iteration handoff")


@graph.step(
    "retain-critical-flow",
    title="Retain critical flow result",
    phase="after_each",
    inputs=["journey_handoff"],
    outputs=["iteration_complete"],
)
@runner.phase("after_each", step_id="retain-critical-flow")
def after_each(ctx):
    """Close one bounded critical-flow iteration."""
    ctx.log("Closed this bounded critical flow")


@graph.step(
    "finalize-critical-flow",
    title="Finalize critical flow evaluation",
    phase="after_all",
    inputs=["iteration_complete"],
    outputs=["final_status"],
)
@runner.phase("after_all", step_id="finalize-critical-flow")
def after_all(ctx):
    """Finalize the critical-flow evaluation."""
    ctx.log("Finalized the critical flow evaluation")


if __name__ == "__main__":
    runner.main()
