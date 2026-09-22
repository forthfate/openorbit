"""SDK-owned stateful browser-journey operations used by shipped templates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ..decorators.visual import visual_node

_PERSONA_SCRIPT = r"""const { chromium } = require(process.argv[1]); const input = JSON.parse(process.argv[2]);
const blocked=/(logout|signout|delete|remove|destroy|payment|checkout|purchase|upgrade|unsubscribe)/i;(async()=>{const options={headless:true};if(input.executablePath)options.executablePath=input.executablePath;const browser=await chromium.launch(options);const page=await browser.newPage();try{await page.goto(input.url,{waitUntil:'domcontentloaded',timeout:30000});const before=page.url();const actions=await page.locator('a[href]').evaluateAll(items=>items.map((item,index)=>({id:`link-${index}`,href:item.href,label:(item.textContent||'').trim().replace(/\s+/g,' ').slice(0,140)})).filter(item=>item.href));const safe=actions.filter(item=>{try{const u=new URL(item.href),origin=new URL(before).origin;return u.origin===origin&&!blocked.test(u.pathname+' '+item.label)}catch{return false}}).slice(0,30);let acted=false;if(input.allowedHref){const candidate=safe.find(item=>item.href===input.allowedHref);if(!candidate)throw new Error('planned action is no longer an allowed visible link');await page.goto(candidate.href,{waitUntil:'domcontentloaded',timeout:30000});acted=true}const text=(await page.locator('body').innerText().catch(()=>'' )).replace(/\s+/g,' ').slice(0,1800);await page.screenshot({path:input.screenshot,fullPage:true});console.log('__ORBIT_PERSONA_RESULT__'+JSON.stringify({before_url:before,url:page.url(),title:await page.title(),visible_text:text,available_actions:safe,acted,screenshot:input.screenshot}))}finally{await browser.close()}})().catch(error=>{console.error(error);process.exit(1)});"""


def _persona_state(ctx: Any, namespace: str) -> dict[str, Any]:
    value = ctx.load_state(namespace, None)
    if isinstance(value, dict):
        return value
    case = ctx.test_cases[0]
    return {
        "persona": str(case.get("name") or "A careful product user"),
        "current_goal": str(case.get("prompt") or "Understand the product through safe visits."),
        "feeling": "curious",
        "next_intent": "Orient myself on the first visible page.",
        "learnings": [],
        "reported_issues": [],
        "history": [],
    }


def _save_persona_state(ctx: Any, namespace: str, state: dict[str, Any]) -> None:
    state["learnings"] = list(state.get("learnings", []))[-12:]
    state["reported_issues"] = list(state.get("reported_issues", []))[-8:]
    state["history"] = list(state.get("history", []))[-24:]
    ctx.save_state(namespace, state)


def _persona_browser(
    ctx: Any, *, url: str, screenshot: str, allowed_href: str | None = None
) -> dict[str, Any]:
    import orbit_sdk

    module = str(Path(orbit_sdk.__file__).resolve().parents[2] / "frontend" / "node_modules" / "playwright")
    artifacts = (
        ctx.app_data / "artifacts" / ctx.environment.get("ORBIT_RUN_ID", "manual") / f"loop-{ctx.loop_index}"
    )
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": url,
        "screenshot": str(artifacts / screenshot),
        "allowedHref": allowed_href,
        "executablePath": str(ctx.build.get("browser_executable_path") or "").strip(),
    }
    output = ctx.exec(
        ["node", "-e", _PERSONA_SCRIPT, module, json.dumps(payload)],
        timeout=120,
        target_log_source="browser-persona",
        target_log_exclude_prefixes=("__ORBIT_PERSONA_RESULT__",),
    )
    result = next(
        (
            line.removeprefix("__ORBIT_PERSONA_RESULT__")
            for line in reversed(output.splitlines())
            if line.startswith("__ORBIT_PERSONA_RESULT__")
        ),
        "",
    )
    if not result:
        raise RuntimeError("browser persona did not return structured evidence")
    value = json.loads(result)
    if not isinstance(value, dict):
        raise RuntimeError("browser persona did not return an object")
    return value


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
    kind="validate_browser_journey_contract",
    group_key="contracts",
    display_name="Validate browser journey contract",
    title_key="visual.nodes.validateBrowserRuntime.title",
    description_key="visual.nodes.validateBrowserRuntime.description",
    default_outputs=("journey_contract",),
)
def validate_browser_journey_contract(
    ctx: Any, _: Mapping[str, Any], __: Mapping[str, object]
) -> dict[str, object]:
    """Require the browser URL and fixed cases used by a recurring journey."""
    if not ctx.build.get("browser_base_url") or not ctx.test_cases:
        raise ValueError("A browser base URL and at least one journey case are required")
    ctx.log("Validated the continuous Playwright journey contract")
    return {"journey_contract": True}


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


@visual_node(
    kind="validate_persona_contract",
    group_key="journeys",
    display_name="Validate persona contract",
    title_key="visual.nodes.validatePersonaContract.title",
    description_key="visual.nodes.validatePersonaContract.description",
    default_outputs=("persona_contract",),
)
def validate_persona_contract(ctx: Any, _: Mapping[str, Any], __: Mapping[str, object]) -> dict[str, object]:
    """Require a browser target and one fixed persona contract."""
    if not ctx.build.get("browser_base_url"):
        raise ValueError("An autonomous persona needs a browser base URL")
    if not ctx.test_cases:
        raise ValueError("An autonomous persona needs one persona contract")
    ctx.log("Validated the autonomous persona contract and safe browser boundary")
    return {"persona_contract": True}


@visual_node(
    kind="observe_persona_page",
    group_key="journeys",
    display_name="Observe persona page",
    title_key="visual.nodes.observePersonaPage.title",
    description_key="visual.nodes.observePersonaPage.description",
    default_config={"namespace": "autonomous_persona"},
    default_outputs=("page_choices",),
    required_config=("namespace",),
)
def observe_persona_page(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Capture safe, rendered choices and retain the persona observation."""
    namespace = config["namespace"]
    state = _persona_state(ctx, namespace)
    observation = _persona_browser(
        ctx,
        url=str(state.get("last_url") or ctx.build["browser_base_url"]),
        screenshot=f"persona-observation-{ctx.loop_index}.png",
    )
    state["observation"] = observation
    _save_persona_state(ctx, namespace, state)
    summary = {
        key: state[key]
        for key in ("persona", "current_goal", "feeling", "next_intent", "learnings", "reported_issues")
    }
    ctx.emit_result({"persona": {"iteration": ctx.loop_index, "state": summary, "observation": observation}})
    ctx.log(f"Observed {len(observation['available_actions'])} safe visible action(s)")
    return {"page_choices": observation}


@visual_node(
    kind="plan_persona_action",
    group_key="journeys",
    display_name="Plan persona action",
    title_key="visual.nodes.planPersonaAction.title",
    description_key="visual.nodes.planPersonaAction.description",
    default_config={"namespace": "autonomous_persona"},
    default_outputs=("persona_plan",),
    required_config=("namespace",),
)
def plan_persona_action(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Let a persona select exactly one action from rendered safe choices."""
    namespace = config["namespace"]
    state = _persona_state(ctx, namespace)
    actions = state["observation"]["available_actions"]
    prompt = (
        """You are a persistent product user. Decide one next action, not a test verdict. Return JSON only:
{"intent":"short first-person purpose","action_id":"one listed id or empty","rationale":"observable reason","expected_signal":"what would change my understanding"}.
You may choose an empty action_id to observe again. Never choose actions outside listed IDs. Avoid repeating a reported issue unless new evidence exists.

Persona state:\n"""
        + json.dumps(
            {
                key: state[key]
                for key in (
                    "persona",
                    "current_goal",
                    "feeling",
                    "next_intent",
                    "learnings",
                    "reported_issues",
                    "history",
                )
            },
            ensure_ascii=False,
        )
        + "\nVisible safe actions:\n"
        + json.dumps(actions, ensure_ascii=False)
    )
    plan = ctx.complete_model_json(prompt, description="persona model response")
    action_id = str(plan.get("action_id") or "")
    selected = next((item for item in actions if item["id"] == action_id), None)
    if action_id and selected is None:
        raise ValueError("persona selected an action outside the visible safe action list")
    state["plan"] = {
        "intent": str(plan.get("intent") or state["next_intent"]),
        "rationale": str(plan.get("rationale") or ""),
        "expected_signal": str(plan.get("expected_signal") or ""),
        "action": selected,
    }
    _save_persona_state(ctx, namespace, state)
    ctx.emit_result({"persona": {"iteration": ctx.loop_index, "plan": state["plan"]}})
    ctx.log("Planned one persona action from rendered, safe choices")
    return {"persona_plan": state["plan"]}


@visual_node(
    kind="run_persona_action",
    group_key="journeys",
    display_name="Run persona action",
    title_key="visual.nodes.runPersonaAction.title",
    description_key="visual.nodes.runPersonaAction.description",
    default_config={"namespace": "autonomous_persona"},
    default_outputs=("action_evidence",),
    required_config=("namespace",),
)
def run_persona_action(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Follow the selected safe link and retain the resulting rendered page."""
    namespace = config["namespace"]
    state = _persona_state(ctx, namespace)
    action = state["plan"].get("action")
    evidence = _persona_browser(
        ctx,
        url=state["observation"]["before_url"],
        allowed_href=action["href"] if action else None,
        screenshot=f"persona-action-{ctx.loop_index}.png",
    )
    state["evidence"] = evidence
    _save_persona_state(ctx, namespace, state)
    ctx.emit_result({"persona": {"iteration": ctx.loop_index, "action_evidence": evidence}})
    ctx.log("Completed one bounded persona action with rendered evidence")
    return {"action_evidence": evidence}


@visual_node(
    kind="reflect_persona_session",
    group_key="journeys",
    display_name="Reflect persona session",
    title_key="visual.nodes.reflectPersonaSession.title",
    description_key="visual.nodes.reflectPersonaSession.description",
    default_config={"namespace": "autonomous_persona"},
    default_outputs=("persona_handoff",),
    required_config=("namespace",),
)
def reflect_persona_session(
    ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]
) -> dict[str, object]:
    """Persist feelings, learnings, unique issues, and the next safe intent."""
    namespace = config["namespace"]
    state = _persona_state(ctx, namespace)
    prompt = """You are reflecting as a persistent product user after one safe browser action. Return JSON only:
{"feeling":"brief feeling","learning":"specific observation","issue":{"title":"short or empty","evidence":"observable evidence","severity":"low|medium|high"},"next_intent":"one concrete next action to investigate"}.
Do not repeat a reported issue title unless the new evidence materially differs.

Current state:\n""" + json.dumps(state, ensure_ascii=False)
    reflection = ctx.complete_model_json(prompt, description="persona model response")
    issue = reflection.get("issue") if isinstance(reflection.get("issue"), dict) else {}
    title = str(issue.get("title") or "").strip()
    known = {str(item.get("title", "")).casefold() for item in state["reported_issues"]}
    if title and title.casefold() not in known:
        state["reported_issues"].append(
            {
                "title": title,
                "evidence": str(issue.get("evidence") or ""),
                "severity": str(issue.get("severity") or "low"),
                "iteration": ctx.loop_index,
            }
        )
    learning = str(reflection.get("learning") or "").strip()
    if learning and learning not in state["learnings"]:
        state["learnings"].append(learning)
    state["feeling"] = str(reflection.get("feeling") or state["feeling"])
    state["next_intent"] = str(reflection.get("next_intent") or state["plan"]["intent"])
    state["last_url"] = state["evidence"]["url"]
    state["history"].append(
        {
            "iteration": ctx.loop_index,
            "intent": state["plan"]["intent"],
            "action": state["plan"].get("action"),
            "feeling": state["feeling"],
            "learning": learning,
            "next_intent": state["next_intent"],
        }
    )
    _save_persona_state(ctx, namespace, state)
    summary = {key: state[key] for key in ("feeling", "next_intent", "learnings", "reported_issues")}
    ctx.emit_result(
        {"persona": {"iteration": ctx.loop_index, "reflection": reflection, "next_state": summary}}
    )
    artifact = ctx.save_data_file(
        f"autonomous-persona/iteration-{ctx.loop_index}.json",
        json.dumps(
            {
                "plan": state["plan"],
                "evidence": state["evidence"],
                "reflection": reflection,
                "next_state": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        label="Autonomous persona handoff",
        content_type="application/json",
    )
    ctx.log("Retained persona feeling, learning, deduplicated issues, and next intent")
    return {"persona_handoff": {"reflection": reflection, "next_state": summary, "artifact": artifact}}
