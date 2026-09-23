"""Run a safe, stateful persona journey with one browser action per iteration.

The persona model chooses only from rendered, same-origin, non-destructive
actions. Persistent state records the observed evidence and next intent without
changing the evaluated product.
"""

import json
import re
from pathlib import Path

import orbit_sdk
from orbit_sdk import graph, runner

BLOCKED = re.compile(
    r"logout|signout|delete|remove|destroy|payment|checkout|purchase|upgrade|unsubscribe", re.I
)
MAX_HISTORY, MAX_LEARNINGS, MAX_ISSUES = 24, 12, 8

graph.connect("validate-browser-runtime", "validate")
graph.connect("validate", "observe")
graph.connect("observe", "decide", kind="data", label="rendered choices")
graph.connect("decide", "act", kind="data", label="one safe action")
graph.connect("act", "reflect", kind="data", label="action evidence")
graph.connect("reflect", "observe", kind="loop", label="next visit")
graph.connect("reflect", "finalize", kind="condition", label="completed")


def state_path(ctx):
    """Return the build-scoped path for persistent persona state.

    Args:
        ctx: The active Orbit runner context.

    Returns:
        A path outside the evaluated repository.
    """
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(ctx.build.get("id") or "persona"))
    directory = ctx.app_data / "autonomous-personas"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{slug}.json"


def load_state(ctx):
    """Load persisted persona state or initialize it from the first case."""
    if state_path(ctx).exists():
        return json.loads(state_path(ctx).read_text(encoding="utf-8"))
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


def save_state(ctx, state):
    """Persist only bounded persona history to keep recurring runs compact."""
    state["learnings"] = list(state.get("learnings", []))[-MAX_LEARNINGS:]
    state["reported_issues"] = list(state.get("reported_issues", []))[-MAX_ISSUES:]
    state["history"] = list(state.get("history", []))[-MAX_HISTORY:]
    state_path(ctx).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def model_json(ctx, prompt):
    """Request one JSON decision through the SDK's model response contract."""
    return ctx.complete_model_json(prompt, description="persona model response")


def browser(ctx, *, url, screenshot, allowed_href=None):
    """Capture rendered browser evidence for one pre-approved safe action."""
    """Observe or follow exactly one pre-approved same-origin, non-destructive link."""
    module = str(Path(orbit_sdk.__file__).resolve().parents[2] / "frontend" / "node_modules" / "playwright")
    artifacts = (
        ctx.app_data / "artifacts" / ctx.environment.get("ORBIT_RUN_ID", "manual") / f"loop-{ctx.loop_index}"
    )
    artifacts.mkdir(parents=True, exist_ok=True)
    executable = str(ctx.build.get("browser_executable_path") or "").strip()
    payload = {
        "url": url,
        "screenshot": str(artifacts / screenshot),
        "allowedHref": allowed_href,
        "executablePath": executable,
    }
    script = r"""const { chromium } = require(process.argv[1]); const input = JSON.parse(process.argv[2]);
const blocked = /(logout|signout|delete|remove|destroy|payment|checkout|purchase|upgrade|unsubscribe)/i;
(async()=>{const options={headless:true};if(input.executablePath)options.executablePath=input.executablePath;const browser=await chromium.launch(options);const page=await browser.newPage();try{
 await page.goto(input.url,{waitUntil:'domcontentloaded',timeout:30000}); const before=page.url();
 const actions=await page.locator('a[href]').evaluateAll(items=>items.map((item,index)=>({id:`link-${index}`,href:item.href,label:(item.textContent||'').trim().replace(/\s+/g,' ').slice(0,140)})).filter(item=>item.href));
 const safe=actions.filter(item=>{try{const u=new URL(item.href), origin=new URL(before).origin;return u.origin===origin&&!blocked.test(u.pathname+' '+item.label)}catch{return false}}).slice(0,30);
 let acted=false;if(input.allowedHref){const candidate=safe.find(item=>item.href===input.allowedHref);if(!candidate)throw new Error('planned action is no longer an allowed visible link');await page.goto(candidate.href,{waitUntil:'domcontentloaded',timeout:30000});acted=true;}
 const text=(await page.locator('body').innerText().catch(()=>'' )).replace(/\s+/g,' ').slice(0,1800);await page.screenshot({path:input.screenshot,fullPage:true});
 console.log(`browser navigation completed: ${before} -> ${page.url()}`);console.log('__ORBIT_PERSONA_RESULT__'+JSON.stringify({before_url:before,url:page.url(),title:await page.title(),visible_text:text,available_actions:safe,acted,screenshot:input.screenshot}));
 }finally{await browser.close()}})().catch(error=>{console.error(error);process.exit(1)});"""
    output = ctx.exec(
        ["node", "-e", script, module, json.dumps(payload)],
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
    return json.loads(result)


@graph.step(
    "validate-browser-runtime",
    title="Validate persona browser runtime",
    phase="before_all",
    outputs=["browser_target"],
)
@runner.phase("before_all", step_id="validate-browser-runtime")
def validate_browser_runtime(ctx):
    """Validate the browser base URL before the persona journey starts."""
    if not ctx.build.get("browser_base_url"):
        raise ValueError("An autonomous persona needs a browser base URL")


@graph.step(
    "validate",
    title="Validate autonomous persona contract",
    phase="before_all",
    inputs=["browser_target"],
    outputs=["persona_contract"],
)
@runner.phase("before_all", step_id="validate")
def before_all(ctx):
    """Require one fixed persona journey case."""
    if not ctx.test_cases:
        raise ValueError("An autonomous persona needs one persona contract")
    ctx.log("Validated the autonomous persona contract and safe browser boundary")


@graph.step(
    "observe",
    title="Observe current page",
    phase="before_each",
    inputs=["persona_contract"],
    outputs=["page_choices"],
)
@runner.phase("before_each", step_id="observe")
def before_each(ctx):
    """Observe the current page and persist its safe action choices."""
    state = load_state(ctx)
    url = str(state.get("last_url") or ctx.build["browser_base_url"])
    observation = browser(ctx, url=url, screenshot=f"persona-observation-{ctx.loop_index}.png")
    state["observation"] = observation
    save_state(ctx, state)
    ctx.emit_result(
        {
            "persona": {
                "iteration": ctx.loop_index,
                "state": {
                    key: state[key]
                    for key in (
                        "persona",
                        "current_goal",
                        "feeling",
                        "next_intent",
                        "learnings",
                        "reported_issues",
                    )
                },
                "observation": observation,
            }
        }
    )
    ctx.log(f"Observed {len(observation['available_actions'])} safe visible action(s)")


@graph.step(
    "decide",
    title="Plan next persona action",
    phase="execute",
    inputs=["page_choices"],
    outputs=["persona_plan"],
)
@runner.phase("execute", step_id="decide")
def execute(ctx):
    """Ask the persona model to choose one bounded next action."""
    state = load_state(ctx)
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
    plan = model_json(ctx, prompt)
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
    save_state(ctx, state)
    ctx.emit_result({"persona": {"iteration": ctx.loop_index, "plan": state["plan"]}})
    ctx.log("Planned one persona action from rendered, safe choices")


@graph.step(
    "act",
    title="Take one safe persona action",
    phase="verify",
    inputs=["persona_plan"],
    outputs=["action_evidence"],
)
@runner.phase("verify", step_id="act")
def verify(ctx):
    """Execute the selected safe action and retain rendered evidence."""
    state = load_state(ctx)
    action = state["plan"].get("action")
    evidence = browser(
        ctx,
        url=state["observation"]["before_url"],
        allowed_href=action["href"] if action else None,
        screenshot=f"persona-action-{ctx.loop_index}.png",
    )
    state["evidence"] = evidence
    save_state(ctx, state)
    ctx.emit_result({"persona": {"iteration": ctx.loop_index, "action_evidence": evidence}})
    ctx.log("Completed one bounded persona action with rendered evidence")


@graph.step(
    "reflect",
    title="Reflect persona session",
    phase="after_each",
    inputs=["action_evidence"],
    outputs=["persona_handoff"],
)
@runner.phase("after_each", step_id="reflect")
def after_each(ctx):
    """Reflect on the action and persist the persona's next intent."""
    state = load_state(ctx)
    prompt = """You are reflecting as a persistent product user after one safe browser action. Return JSON only:
{"feeling":"brief feeling","learning":"specific observation","issue":{"title":"short or empty","evidence":"observable evidence","severity":"low|medium|high"},"next_intent":"one concrete next action to investigate"}.
Do not repeat a reported issue title unless the new evidence materially differs.

Current state:\n""" + json.dumps(state, ensure_ascii=False)
    reflection = model_json(ctx, prompt)
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
    save_state(ctx, state)
    summary = {key: state[key] for key in ("feeling", "next_intent", "learnings", "reported_issues")}
    ctx.emit_result(
        {"persona": {"iteration": ctx.loop_index, "reflection": reflection, "next_state": summary}}
    )
    ctx.save_data_file(
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


@graph.step(
    "finalize",
    title="Finalize autonomous persona",
    phase="after_all",
    inputs=["persona_handoff"],
    outputs=["final_status"],
)
@runner.phase("after_all", step_id="finalize")
def after_all(ctx):
    """Finalize the autonomous persona journey."""
    ctx.log("Finalized the autonomous persona journey")


if __name__ == "__main__":
    runner.main()
