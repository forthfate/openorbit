"""A reference runner for recurring, evidence-led browser journeys."""

import json
import re

from orbit_sdk import graph, runner

graph.connect("validate", "plan")
graph.connect("plan", "exercise", kind="data", label="focused journey")
graph.connect("exercise", "retain")
graph.connect("retain", "plan", kind="loop", label="next iteration")


def state_path(ctx):
    """Keep durable journey state in OpenOrbit AppData, never in the target repo."""
    build_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(ctx.build.get("id") or "journey"))
    directory = ctx.app_data / "continuous-journeys"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{build_id}.json"


def load_state(ctx):
    path = state_path(ctx)
    return (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"next_case": 0, "failed": [], "history": []}
    )


def save_state(ctx, state):
    state["history"] = state.get("history", [])[-24:]
    state_path(ctx).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


@graph.step(
    "validate", title="Validate recurring browser journey", phase="before_all", outputs=["journey_contract"]
)
@runner.phase("before_all")
def before_all(ctx):
    # The SDK owns browser execution; callers supply only a URL and fixed cases.
    if not ctx.build.get("browser_base_url") or not ctx.test_cases:
        raise ValueError("A browser base URL and at least one journey case are required")
    ctx.log("Validated the continuous Playwright journey contract")


@graph.step(
    "plan",
    title="Choose next user journey",
    phase="before_each",
    inputs=["journey_contract"],
    outputs=["journey_plan"],
)
@runner.phase("before_each")
def before_each(ctx):
    state = load_state(ctx)
    # Failed paths are retried first; otherwise rotate to retain broad coverage.
    focused = [case for case in ctx.test_cases if str(case.get("id")) in set(state["failed"])]
    if not focused:
        focused = [ctx.test_cases[int(state["next_case"]) % len(ctx.test_cases)]]
    state["plan"] = {
        "case_ids": [str(case.get("id")) for case in focused],
        "prior_feedback": ctx.previous_supervisor_feedback,
    }
    save_state(ctx, state)
    ctx.emit_result({"continuous_journey": {"iteration": ctx.loop_index, "plan": state["plan"]}})
    ctx.log(f"Planned journey case(s): {', '.join(state['plan']['case_ids'])}")


@graph.step(
    "exercise",
    title="Exercise rendered journey",
    phase="execute",
    inputs=["journey_plan"],
    outputs=["browser_evidence"],
)
@runner.phase("execute")
def execute(ctx):
    state = load_state(ctx)
    chosen = set(state["plan"]["case_ids"])
    evidence = ctx.playwright_journey([case for case in ctx.test_cases if str(case.get("id")) in chosen])
    state["failed"] = [str(item.get("id")) for item in evidence["results"] if not item["passed"]]
    state["next_case"] = int(state["next_case"]) + 1
    state["history"].append(
        {"iteration": ctx.loop_index, "case_ids": state["plan"]["case_ids"], "failed": state["failed"]}
    )
    save_state(ctx, state)
    ctx.emit_result(
        {
            "continuous_journey": {
                "iteration": ctx.loop_index,
                "evidence": evidence,
                "handoff": state["history"][-1],
            }
        }
    )
    # Preserve a small, downloadable iteration summary alongside the richer
    # Playwright evidence retained by the SDK.
    ctx.save_data_file(
        f"continuous-journey/iteration-{ctx.loop_index}.json",
        json.dumps(state["history"][-1], ensure_ascii=False, indent=2),
        label="Continuous journey handoff",
        content_type="application/json",
    )
    ctx.log(f"Executed {len(evidence['results'])} browser case(s); failed: {len(state['failed'])}")


@graph.step(
    "retain",
    title="Retain journey handoff",
    phase="verify",
    inputs=["browser_evidence"],
    outputs=["next_iteration"],
)
@runner.phase("verify")
def verify(ctx):
    state = load_state(ctx)
    ctx.emit_result(
        {"continuous_journey": {"next_iteration": state["history"][-1], "state_path": str(state_path(ctx))}}
    )
    ctx.log("Retained browser evidence and the next-iteration handoff")


@runner.phase("after_each")
def after_each(ctx):
    ctx.log("Completed one bounded continuous browser journey")


@runner.phase("after_all")
def after_all(ctx):
    ctx.log("Finalized the continuous browser journey")


if __name__ == "__main__":
    runner.main()
