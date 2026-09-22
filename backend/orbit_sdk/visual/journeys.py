"""SDK-owned stateful browser-journey operations used by shipped templates."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ..decorators.visual import visual_node


def _journey_state(ctx: Any, namespace: str) -> dict[str, Any]:
    value = ctx.load_state(namespace, {"next_case_index": 0, "failed_case_ids": [], "history": []})
    return value if isinstance(value, dict) else {"next_case_index": 0, "failed_case_ids": [], "history": []}


@visual_node(
    kind="validate_browser_runtime",
    group_key="journeys",
    display_name="Validate browser runtime",
    title_key="visual.nodes.validateBrowserRuntime.title",
    description_key="visual.nodes.validateBrowserRuntime.description",
    default_config={"field": "browser_base_url"},
    default_outputs=("browser_runtime",),
)
def validate_browser_runtime(
    ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]
) -> dict[str, object]:
    """Require the browser target required by user-journey templates."""
    field = str(config.get("field", "browser_base_url"))
    if not ctx.build.get(field):
        raise ValueError(f"Set required build field(s): {field}")
    return {"browser_runtime": True}


@visual_node(
    kind="initialize_user_journey_state",
    group_key="journeys",
    display_name="Initialize user journey state",
    title_key="visual.nodes.initializeUserJourneyState.title",
    description_key="visual.nodes.initializeUserJourneyState.description",
    default_config={"namespace": "user_journey"},
    default_outputs=("journey_state",),
    required_config=("namespace",),
)
def initialize_user_journey_state(
    ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]
) -> dict[str, object]:
    """Persist a bounded initial state before planning a journey iteration."""
    state = _journey_state(ctx, config["namespace"])
    ctx.save_state(config["namespace"], state)
    return {"journey_state": state}


@visual_node(
    kind="plan_user_journey",
    group_key="journeys",
    display_name="Plan user journey",
    title_key="visual.nodes.planUserJourney.title",
    description_key="visual.nodes.planUserJourney.description",
    default_config={"namespace": "user_journey"},
    default_outputs=("journey_plan",),
    required_config=("namespace",),
)
def plan_user_journey(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Retry failed cases first, otherwise rotate one fixed browser journey."""
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed journey case before running this runner")
    namespace = config["namespace"]
    current = _journey_state(ctx, namespace)
    failed_ids = {str(case_id) for case_id in current.get("failed_case_ids", [])}
    cases = [case for case in ctx.test_cases if str(case.get("id")) in failed_ids]
    failed = bool(cases)
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
    plan = {
        "case_ids": [str(case.get("id")) for case in cases],
        "reason": "Revisit previously failed journeys."
        if failed
        else "Rotate one fixed journey to retain bounded coverage.",
        "rules": rules,
        "supervisor_feedback": ctx.previous_supervisor_feedback,
    }
    current["plan"] = plan
    ctx.save_state(namespace, current)
    ctx.emit_result(
        {namespace: {"iteration": ctx.loop_index, "case_count": len(ctx.test_cases), "plan": plan}}
    )
    return {"journey_plan": plan}


@visual_node(
    kind="run_user_journey",
    group_key="journeys",
    display_name="Run user journey",
    title_key="visual.nodes.runUserJourney.title",
    description_key="visual.nodes.runUserJourney.description",
    default_config={"namespace": "user_journey", "history_limit": 24},
    default_outputs=("journey_evidence",),
    required_config=("namespace",),
)
def run_user_journey(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Run selected browser cases and retain bounded next-iteration state."""
    namespace = config["namespace"]
    current = _journey_state(ctx, namespace)
    plan = current.get("plan") if isinstance(current.get("plan"), dict) else {}
    selected = {str(value) for value in plan.get("case_ids", [])}
    evidence = ctx.playwright_journey([case for case in ctx.test_cases if str(case.get("id")) in selected])
    results = list(evidence.get("results", [])) if isinstance(evidence, dict) else []
    failed_ids = [
        str(item.get("id")) for item in results if isinstance(item, dict) and not item.get("passed")
    ]
    current["failed_case_ids"] = failed_ids
    current["next_case_index"] = (int(current.get("next_case_index", 0)) + 1) % len(ctx.test_cases)
    handoff = {
        "iteration": ctx.loop_index,
        "reason": plan.get("reason", ""),
        "rules": plan.get("rules", []),
        "passed": len(results) - len(failed_ids),
        "failed": len(failed_ids),
        "failed_case_ids": failed_ids,
    }
    limit = int(config.get("history_limit", 24))
    current["history"] = [*current.get("history", []), handoff][-max(1, limit) :]
    current["handoff"] = handoff
    ctx.save_state(namespace, current)
    artifact = ctx.save_data_file(
        f"{namespace}/iteration-{ctx.loop_index}.json",
        json.dumps({"plan": plan, "evidence": evidence, "handoff": handoff}, ensure_ascii=False, indent=2),
        label="User journey iteration evidence",
        content_type="application/json",
    )
    value = {
        "iteration": ctx.loop_index,
        "plan": plan,
        "results": results,
        "evidence": evidence,
        "handoff": handoff,
        "artifact": artifact,
    }
    ctx.emit_result({namespace: value})
    return {"journey_evidence": value}


@visual_node(
    kind="publish_user_journey_handoff",
    group_key="journeys",
    display_name="Publish user journey handoff",
    title_key="visual.nodes.publishUserJourneyHandoff.title",
    description_key="visual.nodes.publishUserJourneyHandoff.description",
    default_config={"namespace": "user_journey"},
    default_outputs=("journey_handoff",),
    required_config=("namespace",),
)
def publish_user_journey_handoff(
    ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]
) -> dict[str, object]:
    """Expose retained handoff evidence to the supervisor."""
    namespace = config["namespace"]
    handoff = _journey_state(ctx, namespace).get("handoff", {})
    ctx.emit_result({namespace: {"next_iteration": handoff}})
    return {"journey_handoff": handoff}
