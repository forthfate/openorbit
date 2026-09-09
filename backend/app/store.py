from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
import yaml

from orbit import load_bundle

from .assistant_tools import normalize_settings as normalize_assistant_tools
from .models import Run, Step, Workflow
from .observability import configure_telemetry
from .providers import AzureOpenAIProvider, BedrockProvider, ModelSettings
from .remote import RemoteInvocation

ROOT = Path(__file__).resolve().parents[2]


def _application_data_pointer() -> Path:
    """Keep an operator-selected data location outside the data it points to."""
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Orbit"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Preferences" / "Orbit"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "orbit"
    return root / "app-data-path"


def _application_data_dir() -> Path:
    """Return Orbit's writable per-user state directory on every platform."""
    override = os.environ.get("ORBIT_APP_DATA")
    if override:
        return Path(override).expanduser()
    pointer = _application_data_pointer()
    try:
        selected = pointer.read_text(encoding="utf-8").strip()
    except OSError:
        selected = ""
    if selected:
        return Path(selected).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Orbit"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Orbit"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "orbit"


APP_DATA = _application_data_dir()
CONFIG = APP_DATA / "config"
TARGET_TEST_CASE_SETS = CONFIG / "target-ai-test-case-sets.yaml"
EXECUTION_ENVIRONMENTS = CONFIG / "execution-environments.yaml"
TARGET_ENVIRONMENTS = CONFIG / "target-environments.yaml"
CYCLE_INTERVENTIONS = CONFIG / "cycle-interventions.yaml"
DEFAULT_OPERATIONAL_MANAGER_PROMPT = """You are an approval-first operations manager for recurring AI evaluations.
Preserve the task safety boundary, collect observable evidence, and never
claim success without stated acceptance evidence. Escalate required approvals
and stop immediately when an emergency stop is requested.

__ORBIT_MANAGER_AI_PROMPT__

__ORBIT_MANAGER_OUTPUT_LANGUAGE__

Your final response must be exactly one JSON object:
{
  \"evaluation\": {\"score\":\"number from 0 to 10\",\"approval\":\"approved|rejected|pending\",\"summary\":\"string\",\"behavior_trace\": {\"purpose\":\"string\",\"rationale\":\"string\",\"observation\":\"string\",\"decision\":\"string\",\"next_action\":\"string\"}, \"behavior_summary\":\"legacy string, only when the evaluated target is an AI\"},
  \"improvements\": [{\"title\":\"string\",\"status\":\"proposed|adopted|rejected\",\"rationale\":\"string\",\"acceptanceEvidence\":\"string\"}],
  \"reported_issues\": [{\"title\":\"string\",\"severity\":\"low|medium|high|critical\",\"evidence\":\"string\",\"reproduction\":\"string\",\"status\":\"open|acknowledged|resolved\"}]
}
For an evaluated AI, include behavior_trace and fill every field. It is an evidence-backed activity record for a person reviewing the run: purpose explains why this check or action matters now; rationale names only the observable evidence or declared plan behind it; observation records the material change or finding in this iteration; decision records what the target AI did or deliberately did not do; next_action states the specific next check or hypothesis. Compare with the immediately previous iteration when that evidence is supplied. Do not narrate repeated mechanics (navigation, waits, screenshots, or generic control inspection). When there is no material change, say so briefly and make next_action explain how the next check will differ or escalate. Do not reveal hidden reasoning or evaluator chain-of-thought. Do not include behavior_trace for non-AI targets. behavior_summary is optional legacy compatibility only; prefer behavior_trace. Always include both array keys, using empty arrays when there are no items."""
LEGACY_OPERATIONAL_MANAGER_PROMPT = """You are an approval-first operations manager for recurring AI evaluations.
Preserve the task safety boundary, collect observable evidence, and never
claim success without stated acceptance evidence. Escalate required approvals
and stop immediately when an emergency stop is requested.

__ORBIT_MANAGER_AI_PROMPT__

Your final response must be exactly one JSON object:
{
  \"evaluation\": {\"score\":\"number from 0 to 10\",\"approval\":\"approved|rejected|pending\",\"summary\":\"string\",\"behavior_summary\":\"string, only when the evaluated target is an AI\"},
  \"improvements\": [{\"title\":\"string\",\"status\":\"proposed|adopted|rejected\",\"rationale\":\"string\",\"acceptanceEvidence\":\"string\"}],
  \"reported_issues\": [{\"title\":\"string\",\"severity\":\"low|medium|high|critical\",\"evidence\":\"string\",\"reproduction\":\"string\",\"status\":\"open|acknowledged|resolved\"}]
}
Include behavior_summary only when the evaluated target is an AI. It must describe the AI's observed responses, decisions, tool use, refusals, or other behavior in plain language; do not describe pass/fail outcomes, metrics, baselines, or the evaluator's actions. Omit behavior_summary for non-AI targets. Always include both array keys, using empty arrays when there are no items."""
PROPOSAL_DECISION_POLICY = """# Improvement decision policy
Decide each improvement status independently from the evaluation approval score.
Use `adopted` for a prompt-only change when it is low-risk, additive, reversible through the retained prompt version, directly supported by the observed evidence, and has measurable acceptance evidence. Prefer `adopted` for such changes; do not defer it merely to wait for another iteration or a repeated candidate fingerprint.
Use `proposed` when the change needs code, infrastructure, product, security, or human-policy approval, or when the evidence is insufficient. Use `rejected` for unsafe, duplicate, or unsupported changes."""
MANAGER_PROMPT_SLOT = "__ORBIT_MANAGER_AI_PROMPT__"
MANAGER_OUTPUT_LANGUAGE_SLOT = "__ORBIT_MANAGER_OUTPUT_LANGUAGE__"
NATIVE_IMPROVEMENT_CYCLE_TEMPLATE = r"""# Requirements
# - PROJECT_ROOT is a Git repository.
# - The evaluation build selects fixed target-AI prompts and a configured model
#   profile, plus a readable managed_prompt_path on its Target Environment.
# - Only supervisor feedback explicitly marked adopted is applied to the prompt.
# This runner never commits target changes; ctx.update_file keeps rollback versions.

import hashlib
import json
import re

from orbit_sdk import runner

REQUIRED_SUFFICIENT_EVALUATIONS = 3
# Marker comments make replacement idempotent and preserve the surrounding
# target prompt content that OpenOrbit does not own.
PROMPT_BLOCK_START = "<!-- OPENORBIT_ACCEPTED_PROPOSALS_START -->"
PROMPT_BLOCK_END = "<!-- OPENORBIT_ACCEPTED_PROPOSALS_END -->"


def state_path(ctx):
    '''Return the per-build state file outside the target repository.'''
    build_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(ctx.evaluation_build.get("id") or "manual"))
    directory = ctx.app_data / "improvement-cycles"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{build_id}.json"


def load_state(ctx):
    '''Load the previous verdict state, or start a fresh candidate baseline.'''
    path = state_path(ctx)
    if not path.exists():
        return {"candidate_fingerprint": None, "sufficient_evaluations": 0, "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(ctx, state):
    '''Persist only bounded history so recurring evaluations do not grow unbounded.'''
    state["history"] = state.get("history", [])[-24:]
    state_path(ctx).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def git(ctx, *args):
    '''Run Git in the configured project root without invoking a shell.'''
    return ctx.exec(["git", *args], cwd=ctx.project_root, timeout=300)


def candidate(ctx):
    '''Fingerprint the current working-tree diff and retain its changed paths.'''
    patch = git(ctx, "diff", "--binary", "--")
    changed = [line for line in git(ctx, "diff", "--name-only").splitlines() if line]
    return (hashlib.sha256(patch.encode("utf-8")).hexdigest() if patch else None), changed


def update_prompt_from_accepted_proposals(ctx, proposals):
    '''Replace only OpenOrbit's managed prompt block and retain a rollback version.'''
    prompt_path = str(ctx.evaluation_build.get("managed_prompt_path") or ctx.evaluation_build.get("prompt_bundle") or "").strip()
    if not prompt_path:
        raise ValueError("native improvement cycle requires target_environment.managed_prompt_path")
    target = ctx.project_path(prompt_path)
    current = target.read_text(encoding="utf-8")
    if not proposals:
        # Do not manufacture a changing candidate when the supervisor has not
        # accepted a change. A stable candidate must retain the same fingerprint
        # across repeated validations before it can be promoted.
        return {"path": prompt_path, "changed": False, "reason": "no_accepted_proposals"}
    lines = ["## Accepted improvement proposals", "", f"Iteration: {ctx.loop_index}", ""]
    for proposal in proposals:
        lines.extend(
            (
                f"### {proposal.get('title') or 'Accepted proposal'}",
                str(proposal.get("rationale") or ""),
                f"Acceptance evidence: {proposal.get('acceptanceEvidence') or ''}",
                "",
            )
        )
    block = "\n".join((PROMPT_BLOCK_START, "\n".join(lines).rstrip(), PROMPT_BLOCK_END))
    start, end = current.find(PROMPT_BLOCK_START), current.find(PROMPT_BLOCK_END)
    if start >= 0 and end > start:
        updated = current[:start] + block + current[end + len(PROMPT_BLOCK_END) :]
    elif start >= 0 or end >= 0:
        raise ValueError("prompt has an incomplete OpenOrbit accepted-proposals block")
    else:
        updated = current.rstrip() + "\n\n" + block + "\n"
    return ctx.update_file(prompt_path, updated)


def managed_prompt_evidence(ctx):
    '''Expose the current managed prompt beside the target-AI response evidence.'''
    prompt_path = str(ctx.evaluation_build.get("managed_prompt_path") or ctx.evaluation_build.get("prompt_bundle") or "").strip()
    if not prompt_path:
        raise ValueError("native improvement cycle requires target_environment.managed_prompt_path")
    content = ctx.project_path(prompt_path).read_text(encoding="utf-8")
    return {
        "path": prompt_path,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


@runner.phase("init")
def init(ctx):
    # Process-level validation runs once before the iteration loop begins.
    git(ctx, "rev-parse", "--show-toplevel")
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed target-AI prompt for a native improvement cycle")
    if not isinstance(ctx.resource("model_profile", {}), dict) or not ctx.resource("model_profile", {}).get("model"):
        raise ValueError("Select a configured model profile for a native improvement cycle")
    ctx.log("Validated an OpenOrbit-native target-AI prompt improvement cycle")


@runner.phase("setup")
def setup(ctx):
    # Keep the target's complete pre-evaluation state outside commit history.
    # The call is idempotent because setup runs for every iteration.
    ctx.save_setup_snapshot()
    # Apply the latest accepted supervisor feedback before the next validation.
    feedback = ctx.previous_supervisor_feedback
    accepted = [
        proposal for proposal in feedback.get("improvements", [])
        if isinstance(proposal, dict) and str(proposal.get("status") or "").lower() in {"adopted", "accepted"}
    ]
    requires_human_approval = bool(
        ctx.evaluation_build.get("require_human_approval_before_apply", False)
    )
    if requires_human_approval and accepted:
        # A supervisor's adoption is a recommendation, not an operator
        # authorization. Keep it as evidence until an operator approves it.
        prompt_update = {
            "changed": False,
            "reason": "awaiting_human_approval",
            "proposal_count": len(accepted),
        }
        accepted = []
    else:
        prompt_update = update_prompt_from_accepted_proposals(ctx, accepted)
    accepted_ids = [str(value) for value in feedback.get("_orbit_proposal_ids", [])]
    proposal_applications = ctx.record_proposal_application(accepted_ids, prompt_update)
    fingerprint, changed = candidate(ctx)
    ctx.emit_result(
        {
            "improvement_cycle": {
                "iteration": ctx.loop_index,
                "candidate_fingerprint": fingerprint,
                "changed_paths": changed,
                "prompt_update": prompt_update,
                "requires_human_approval": requires_human_approval,
                "managed_prompt": managed_prompt_evidence(ctx),
                "proposal_applications": proposal_applications,
            }
        }
    )
    ctx.log("Refreshed the rollback-protected prompt from accepted supervisor feedback")


@runner.phase("run")
def run(ctx):
    # Exercise the evaluated AI with the current managed prompt. The raw reply
    # is retained as supervisor evidence instead of treating a browser page as
    # proof that a prompt instruction was followed.
    managed_prompt = managed_prompt_evidence(ctx)
    responses = []
    for case in ctx.test_cases:
        request = str(case.get("prompt") or "").strip()
        if not request:
            raise ValueError("each target-AI test case requires a prompt")
        turn = ctx.complete_model(
            "# Managed agent instructions\\n"
            + managed_prompt["content"]
            + "\\n\\n# User request\\n"
            + request
            + "\\n\\nRespond as the managed agent."
        )
        responses.append(
            {
                "id": case.get("id"),
                "name": case.get("name"),
                "request": request,
                "acceptance": str(case.get("acceptance") or ""),
                "response": turn["response"],
                "model": turn["model"],
            }
        )
    artifact = ctx.save_data_file(
        "target-ai-responses.json",
        json.dumps(responses, ensure_ascii=False, indent=2),
        label="Target AI responses",
        content_type="application/json",
    )
    fingerprint, changed = candidate(ctx)
    ctx.emit_result(
        {
            "improvement_cycle": {
                "iteration": ctx.loop_index,
                "candidate_fingerprint": fingerprint,
                "changed_paths": changed,
                "evidence": {"target_ai_responses": responses, "artifact": artifact},
            }
        }
    )


@runner.phase("eval")
def evaluate(ctx):
    # Promote a candidate only after the required number of stable evaluations.
    state = load_state(ctx)
    fingerprint, changed = candidate(ctx)
    if not fingerprint:
        state["candidate_fingerprint"] = None
        state["sufficient_evaluations"] = 0
        verdict = "no_candidate"
    elif state.get("candidate_fingerprint") == fingerprint:
        state["sufficient_evaluations"] = int(state.get("sufficient_evaluations", 0)) + 1
        verdict = "ready_for_approval" if state["sufficient_evaluations"] >= REQUIRED_SUFFICIENT_EVALUATIONS else "continue_validation"
    else:
        state["candidate_fingerprint"] = fingerprint
        state["sufficient_evaluations"] = 1
        verdict = "continue_validation"
    state.setdefault("history", []).append(
        {"iteration": ctx.loop_index, "fingerprint": fingerprint, "paths": changed, "verdict": verdict}
    )
    save_state(ctx, state)
    ctx.emit_result(
        {
            "improvement_cycle": {
                "candidate_fingerprint": fingerprint,
                "changed_paths": changed,
                "sufficient_evaluations": state["sufficient_evaluations"],
                "required_evaluations": REQUIRED_SUFFICIENT_EVALUATIONS,
                "verdict": verdict,
            }
        }
    )
    ctx.log(f"Candidate verdict: {verdict}")


@runner.phase("teardown")
def teardown(ctx):
    # Preserve the first evaluated state as a named recovery checkpoint.
    ctx.save_first_teardown_snapshot()
    # Per-iteration evidence remains available for supervisor review.
    ctx.log("Retained prompt versions, decisions, and validation evidence")


@runner.phase("finalize")
def finalize(ctx):
    # Return the target to its exact baseline without creating a Git commit.
    ctx.restore_setup_snapshot()
    ctx.log("Restored the native improvement target without committing changes")


if __name__ == "__main__":
    runner.main()
"""

SITE_EXPLORATION_TEMPLATE = r"""# Requirements
# - The target application is running at the evaluation build's browser base URL.
# - Playwright Chromium and LangGraph are available.
# This runner follows only same-site links and excludes destructive-looking routes.

import json
import subprocess
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import orbit_sdk
from orbit_sdk import runner


class ExplorerState(TypedDict, total=False):
    base_url: str
    max_clicks: int
    evidence: dict
    opinion: str


def explore_browser(ctx, state):
    module = str(Path(orbit_sdk.__file__).resolve().parents[1] / "frontend" / "node_modules" / "playwright")
    artifacts = ctx.app_data / "artifacts" / ctx.environment.get("ORBIT_RUN_ID", "manual") / f"loop-{ctx.loop_index}"
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = {"baseUrl": state["base_url"], "maxClicks": state["max_clicks"], "screenshot": str(artifacts / "site-exploration.png")}
    script = r'''const { chromium } = require(process.argv[1]); const input = JSON.parse(process.argv[2]);
const blocked = /(logout|signout|delete|remove|destroy|payment|checkout|purchase|upgrade|unsubscribe)/i;
(async () => { const browser = await chromium.launch({headless:true}); const page = await browser.newPage(); const visited = []; const origin = new URL(input.baseUrl).origin;
  try { await page.goto(input.baseUrl, {waitUntil:"domcontentloaded", timeout:30000});
    for (let step = 0; step <= input.maxClicks; step++) { const text = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 1200); visited.push({url:page.url(), title:await page.title(), text});
      if (step === input.maxClicks) break;
      const links = await page.locator("a[href]").evaluateAll(items => items.map((item, index) => ({index, href:item.href, text:(item.textContent || "").trim()})).filter(item => item.href));
      const candidates = links.filter(item => { try { const url = new URL(item.href); return url.origin === origin && !blocked.test(url.pathname + " " + item.text); } catch { return false; } });
      if (!candidates.length) break; const target = candidates[step % candidates.length]; await page.locator("a[href]").nth(target.index).click({timeout:5000}); await page.waitForLoadState("domcontentloaded", {timeout:10000}).catch(() => {}); await page.waitForTimeout(300);
    }
    await page.screenshot({path:input.screenshot, fullPage:true}); console.log(JSON.stringify({visited, screenshot:input.screenshot}));
  } finally { await browser.close(); } })().catch(error => { console.error(error); process.exit(1); });'''
    result = subprocess.run(["node", "-e", script, module, json.dumps(payload)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stdout[-4000:] or "Site exploration failed")
    return json.loads(result.stdout.strip().splitlines()[-1])


def form_opinion(state):
    pages = state["evidence"].get("visited", [])
    titles = [str(page.get("title") or page.get("url")) for page in pages]
    return {"opinion": f"Explored {len(pages)} rendered page(s): " + "; ".join(titles[:3]) + ". Review the captured pages for clarity, usefulness, and friction."}


def graph(ctx):
    workflow = StateGraph(ExplorerState)
    workflow.add_node("explore", lambda state: {"evidence": explore_browser(ctx, state)})
    workflow.add_node("form_opinion", form_opinion)
    workflow.add_edge(START, "explore")
    workflow.add_edge("explore", "form_opinion")
    workflow.add_edge("form_opinion", END)
    return workflow.compile()


@runner.phase("init")
def init(ctx):
    if not ctx.evaluation_build.get("browser_base_url"):
        raise ValueError("Set a browser base URL before exploring a site")


@runner.phase("run")
def run(ctx):
    result = graph(ctx).invoke({"base_url": ctx.evaluation_build["browser_base_url"], "max_clicks": 3})
    ctx.emit_result({"site_exploration": {"opinion": result["opinion"], "evidence": result["evidence"]}})


if __name__ == "__main__":
    runner.main()
"""

JSON_AGENT_CYCLE_TEMPLATE = r'''"""Run a portable, bounded external agent cycle.

Set ORBIT_AGENT_COMMAND to a JSON argument array or a shell-like command
prefix. The external tool receives one action at a time: ``status`` or
``run-once``. It must write one JSON object to stdout and must never start a
daemon or scheduler; OpenOrbit owns repetition, timing, and supervision.
"""

import json
import os
import shlex

from orbit_sdk import runner


def agent_command():
    """Read an explicit command prefix without depending on target source files."""
    configured = os.environ.get("ORBIT_AGENT_COMMAND", "").strip()
    if not configured:
        raise ValueError("Set ORBIT_AGENT_COMMAND to the external agent command")
    if configured.startswith("["):
        value = json.loads(configured)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("ORBIT_AGENT_COMMAND JSON must be an array of strings")
        return value
    return shlex.split(configured)


def cycle_input(ctx, action):
    """Expose non-secret evaluation context through one documented JSON contract."""
    return json.dumps(
        {
            "action": action,
            "iteration": ctx.loop_index,
            "evaluation_build": ctx.evaluation_build,
            "test_cases": ctx.test_cases,
        },
        ensure_ascii=False,
    )


def invoke(ctx, action):
    """Run one bounded action and require structured evidence from the agent."""
    output = ctx.exec(
        [*agent_command(), action],
        cwd=ctx.project_root,
        timeout=3600,
        env={"ORBIT_CYCLE_INPUT": cycle_input(ctx, action)},
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"External agent action {action!r} did not return JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"External agent action {action!r} must return a JSON object")
    return result


@runner.phase("init")
def init(ctx):
    # Check availability once; later phases must not start an independent loop.
    status = invoke(ctx, "status")
    ctx.emit_result({"agent_cycle": {"status": status}})


@runner.phase("setup")
def setup(ctx):
    # Record the fixed inputs so every external action is auditable.
    ctx.emit_result(
        {
            "agent_cycle": {
                "iteration": ctx.loop_index,
                "test_case_ids": [str(case.get("id", "")) for case in ctx.test_cases],
            }
        }
    )


@runner.phase("run")
def run(ctx):
    # Exactly one unit of agent work; OpenOrbit schedules a future iteration.
    result = invoke(ctx, "run-once")
    ctx.emit_result({"agent_cycle": {"iteration": ctx.loop_index, "result": result}})


@runner.phase("eval")
def evaluate(ctx):
    # Re-read status rather than assuming the prior action completed correctly.
    status = invoke(ctx, "status")
    ctx.emit_result({"agent_cycle": {"iteration": ctx.loop_index, "status": status}})


@runner.phase("teardown")
def teardown(ctx):
    # The external process has already returned; no daemon cleanup is required.
    ctx.log("Completed one bounded external agent cycle")


@runner.phase("finalize")
def finalize(ctx):
    ctx.log("Finalized the external agent evaluation")


if __name__ == "__main__":
    runner.main()
'''

EVIDENCE_GATED_PROBE_CYCLE_TEMPLATE = r'''"""Run a portable evidence-gated probe matrix through an external tool.

Set ORBIT_PROBE_COMMAND to a JSON argument array or a shell-like command
prefix. The tool must support ``preflight``, ``prepare``, ``run-probes``, and
``collect-evidence`` actions. Every action receives ORBIT_CYCLE_INPUT and
returns one JSON object. The tool may create disposable workspaces, but it
must not schedule itself or commit changes to the target repository.
"""

import json
import os
import shlex

from orbit_sdk import runner


def probe_command():
    """Read the explicit probe command prefix configured by the operator."""
    configured = os.environ.get("ORBIT_PROBE_COMMAND", "").strip()
    if not configured:
        raise ValueError("Set ORBIT_PROBE_COMMAND to the evidence-gate command")
    if configured.startswith("["):
        value = json.loads(configured)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("ORBIT_PROBE_COMMAND JSON must be an array of strings")
        return value
    return shlex.split(configured)


def cycle_input(ctx, action):
    """Pass selected probes and non-secret evaluation context to the tool."""
    return json.dumps(
        {
            "action": action,
            "iteration": ctx.loop_index,
            "evaluation_build": ctx.evaluation_build,
            "probes": ctx.test_cases,
        },
        ensure_ascii=False,
    )


def invoke(ctx, action):
    """Run one gate action and reject unstructured evidence early."""
    output = ctx.exec(
        [*probe_command(), action],
        cwd=ctx.project_root,
        timeout=3600,
        env={"ORBIT_CYCLE_INPUT": cycle_input(ctx, action)},
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Probe action {action!r} did not return JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"Probe action {action!r} must return a JSON object")
    return result


@runner.phase("init")
def init(ctx):
    # A fixed probe set keeps the gate repeatable and its evidence comparable.
    if not ctx.test_cases:
        raise ValueError("Select a fixed test case set before running an evidence gate")
    preflight = invoke(ctx, "preflight")
    ctx.emit_result({"probe_gate": {"preflight": preflight}})


@runner.phase("setup")
def setup(ctx):
    # Prepare disposable inputs without mutating the target repository.
    prepared = invoke(ctx, "prepare")
    ctx.emit_result({"probe_gate": {"iteration": ctx.loop_index, "prepared": prepared}})


@runner.phase("run")
def run(ctx):
    # Run the complete fixed matrix once and retain the tool's structured report.
    report = invoke(ctx, "run-probes")
    ctx.emit_result({"probe_gate": {"iteration": ctx.loop_index, "report": report}})


@runner.phase("eval")
def evaluate(ctx):
    # Collect final evidence separately so a supervisor can make an independent decision.
    evidence = invoke(ctx, "collect-evidence")
    ctx.emit_result({"probe_gate": {"iteration": ctx.loop_index, "evidence": evidence}})


@runner.phase("teardown")
def teardown(ctx):
    ctx.log("Completed one evidence-gated probe matrix")


@runner.phase("finalize")
def finalize(ctx):
    ctx.log("Finalized the evidence-gated probe evaluation")


if __name__ == "__main__":
    runner.main()
'''
DATA = APP_DATA / "data"
RUNS = DATA / "runs"
TELEMETRY = DATA / "telemetry.jsonl"
SETTINGS = DATA / "settings.json"
TOOL_TIMES = DATA / "tool-times.json"
RUNNERS = APP_DATA / "runners"
RUNNER_TEMPLATES = APP_DATA / "runner-templates"
QUICK_STARTS = APP_DATA / "quick-starts"
QUICK_START_INSTANCES = CONFIG / "quick-start-instances.yaml"
TEMPLATE_TRANSLATIONS = DATA / "template-translations.json"


def configure_application_data(path: str) -> Path:
    """Switch the local state root and retain it for later application starts."""
    requested = Path(path.strip()).expanduser()
    if not requested.is_absolute():
        raise ValueError("app data location must be an absolute path")
    target = requested.resolve()
    target.mkdir(parents=True, exist_ok=True)
    pointer = _application_data_pointer()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(str(target), encoding="utf-8")
    temporary.replace(pointer)
    os.environ["ORBIT_APP_DATA"] = str(target)

    global APP_DATA, CONFIG, TARGET_TEST_CASE_SETS, EXECUTION_ENVIRONMENTS, TARGET_ENVIRONMENTS
    global CYCLE_INTERVENTIONS, DATA, RUNS, TELEMETRY, SETTINGS, TOOL_TIMES, RUNNERS
    global RUNNER_TEMPLATES, QUICK_STARTS, QUICK_START_INSTANCES, TEMPLATE_TRANSLATIONS
    APP_DATA = target
    CONFIG = APP_DATA / "config"
    TARGET_TEST_CASE_SETS = CONFIG / "target-ai-test-case-sets.yaml"
    EXECUTION_ENVIRONMENTS = CONFIG / "execution-environments.yaml"
    TARGET_ENVIRONMENTS = CONFIG / "target-environments.yaml"
    CYCLE_INTERVENTIONS = CONFIG / "cycle-interventions.yaml"
    DATA = APP_DATA / "data"
    RUNS = DATA / "runs"
    TELEMETRY = DATA / "telemetry.jsonl"
    SETTINGS = DATA / "settings.json"
    TOOL_TIMES = DATA / "tool-times.json"
    RUNNERS = APP_DATA / "runners"
    RUNNER_TEMPLATES = APP_DATA / "runner-templates"
    QUICK_STARTS = APP_DATA / "quick-starts"
    QUICK_START_INSTANCES = CONFIG / "quick-start-instances.yaml"
    TEMPLATE_TRANSLATIONS = DATA / "template-translations.json"
    return APP_DATA


def now() -> datetime:
    return datetime.now(UTC)


class ConsoleStore:
    """File-backed local state. Commands are always executed without a shell."""

    def __init__(self) -> None:
        self._initialize_application_data()
        RUNS.mkdir(parents=True, exist_ok=True)
        RUNNERS.mkdir(parents=True, exist_ok=True)
        RUNNER_TEMPLATES.mkdir(parents=True, exist_ok=True)
        QUICK_STARTS.mkdir(parents=True, exist_ok=True)
        self._migrate_evaluation_environments()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        # Test runs are deliberately process-local: they support the build-page
        # test dialog without becoming an evaluation-run record or surviving a
        # server restart.
        self._test_sessions: dict[str, Run] = {}
        self._lock = threading.Lock()
        self._recover_interrupted_runs()
        self.tracer = configure_telemetry(TELEMETRY)

    def _recover_interrupted_runs(self) -> None:
        """Do not present orphaned in-memory pipelines as still running.

        The local scheduler is process-bound.  A server restart ends all worker
        threads, so unfinished records from the previous process are explicitly
        marked cancelled before they can distort active-evaluation metrics.
        """
        for path in RUNS.glob("*.json"):
            try:
                run = Run.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if run.status not in {"queued", "running", "awaiting_approval"}:
                continue
            run.status, run.current_step, run.current_phase = "cancelled", None, None
            run.updated_at, run.finished_at = now(), now()
            run.step_results.append(
                {
                    "step_id": "orbit-restart",
                    "error": "OpenOrbit restarted before this local pipeline completed.",
                    "ended_at": now(),
                }
            )
            temporary = path.with_suffix(".tmp")
            temporary.write_text(run.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(path)

    @staticmethod
    def _initialize_application_data() -> None:
        """Create empty, environment-local state; never seed operational assets from Git."""
        for destination in (CONFIG, DATA):
            destination.mkdir(parents=True, exist_ok=True)
        stored = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
        document = stored if isinstance(stored, dict) else {}
        application = (
            document.get("application_settings")
            if isinstance(document.get("application_settings"), dict)
            else {}
        )
        current_prompt = str(application.get("manager_prompt_template", "")).strip()
        if not current_prompt or current_prompt == LEGACY_OPERATIONAL_MANAGER_PROMPT:
            document["application_settings"] = {
                **application,
                "manager_prompt_template": DEFAULT_OPERATIONAL_MANAGER_PROMPT,
                "manager_output_locale": str(application.get("manager_output_locale", "en")).strip(),
                "chat_model_profile_name": str(application.get("chat_model_profile_name", "")).strip(),
            }
            SETTINGS.write_text(json.dumps(document, indent=2), encoding="utf-8")

    @staticmethod
    def runner_templates() -> list[dict[str, str]]:
        templates = [
            {
                "id": "user-journey-cycle",
                "name": "Browser journey validation",
                "description": "Validates fixed browser journeys and retains page evidence. Requires a running app and Playwright browser.",
                "source": """# Requirements
# - The target application is running at the evaluation build's browser base URL.
# - The evaluation build selects at least one fixed test case.
# - Playwright Chromium and its operating-system libraries are available.
# No external runner script, adapter repository, or background program is required.

import json
import re

from orbit_sdk import runner

# Validate only configuration that the runner cannot safely infer. This runs
# once when an evaluation process starts, before its iteration loop.
def validate(ctx):
    build = ctx.evaluation_build
    if not build.get("browser_base_url"):
        raise ValueError("Set a browser base URL on the evaluation build")
    if not ctx.test_cases:
        raise ValueError("Select a fixed test case set before running a user journey")

def state_path(ctx):
    # Keep state in OpenOrbit AppData, keyed by build, so a later iteration can
    # resume its focused journey without writing into the target repository.
    build_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(ctx.evaluation_build.get("id") or "manual"))
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
    rules = ["Preserve observable evidence for every browser action.", "Do not infer a result that the page did not expose."]
    if failed:
        rules.insert(0, "Revisit previously failed journeys before exploring a new route.")
    if feedback.get("reported_issues"):
        rules.insert(0, "Prioritize the supervisor's previously reported issues.")
    reason = "Previously failed journeys require confirmation." if failed else "Rotate one fixed journey to retain broad, bounded coverage."
    return {"case_ids": [str(case.get("id")) for case in focused], "rules": rules, "reason": reason, "supervisor_feedback": feedback}

@runner.phase("init")
def init(ctx):
    # Process-level preparation: run once before OpenOrbit starts repeating.
    validate(ctx)
    ctx.log("Validated the bounded user-journey contract")

@runner.phase("setup")
def setup(ctx):
    # Iteration-level preparation: persist a plan that the run phase consumes.
    state = load_state(ctx)
    journey_plan = plan(ctx, state)
    state["plan"] = journey_plan
    save_state(ctx, state)
    ctx.emit_result({"user_journey": {"iteration": ctx.loop_index, "case_count": len(ctx.test_cases), "plan": journey_plan}})
    ctx.log(f"Planned {len(journey_plan['case_ids'])} focused journey case(s): {journey_plan['reason']}")

@runner.phase("run")
def run(ctx):
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
    state["handoff"] = {"iteration": ctx.loop_index, "reason": journey_plan["reason"], "rules": journey_plan["rules"], "passed": passed, "failed": len(results) - passed, "failed_case_ids": failed}
    state.setdefault("history", []).append(state["handoff"])
    save_state(ctx, state)
    ctx.emit_result({"user_journey": {"iteration": ctx.loop_index, "plan": journey_plan, "passed": passed, "failed": len(results) - passed, "results": results, "evidence": evidence, "handoff": state["handoff"]}})

@runner.phase("eval")
def evaluate(ctx):
    # Expose the persisted handoff as structured run output for supervision.
    state = load_state(ctx)
    ctx.emit_result({"user_journey": {"next_iteration": state.get("handoff", {}), "state_path": str(state_path(ctx))}})
    ctx.log("Stored the journey summary, reasons, and behavior rules for the next iteration")
@runner.phase("teardown")
def teardown(ctx): ctx.log("Closed this bounded browser journey")
@runner.phase("finalize")
def finalize(ctx): ctx.log("Finalized the user-journey evaluation")

if __name__ == "__main__": runner.main()
""",
            },
            {
                "id": "external-command-adapter",
                "name": "External automation integration",
                "description": "Connects an existing automation tool while OpenOrbit retains scheduling, evidence collection, and supervision.",
                "source": """import json\nimport os\nimport shlex\n\nfrom orbit_sdk import ORBIT_PROJECT_PATH, runner\n\n# Set ORBIT_ADAPTER_COMMAND to the command prefix for an external tool. It may\n# be a JSON array or a shell-like string. The tool must support the bounded\n# actions appended below and must never start its own scheduler.\ndef adapter_command():\n    # Parse once per invocation so the configuration remains explicit and does\n    # not depend on a target repository's source files.\n    configured = os.environ.get("ORBIT_ADAPTER_COMMAND", "").strip()\n    if not configured:\n        raise ValueError("Set ORBIT_ADAPTER_COMMAND to an external tool command")\n    if configured.startswith("["):\n        value = json.loads(configured)\n        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):\n            raise ValueError("ORBIT_ADAPTER_COMMAND JSON must be an array of strings")\n        return value\n    return shlex.split(configured)\n\ndef invoke(ctx, action):\n    # OpenOrbit owns the lifecycle: the adapter receives one bounded action and\n    # must return instead of starting a daemon or an independent scheduler.\n    return ctx.exec([*adapter_command(), action], cwd=ORBIT_PROJECT_PATH(), timeout=3600)\n\n@runner.phase("init")\ndef init(ctx):\n    # Process-level readiness check, performed once before the repeat loop.\n    invoke(ctx, "status")\n\n@runner.phase("setup")\ndef setup(ctx):\n    # Per-iteration preparation, such as refreshing target-side test data.\n    invoke(ctx, "prepare")\n\n@runner.phase("run")\ndef run(ctx):\n    # Exactly one unit of adapter work; OpenOrbit schedules further iterations.\n    invoke(ctx, "run-once")\n\n@runner.phase("eval")\ndef evaluate(ctx):\n    # Return machine-readable or textual evidence for the supervisor to assess.\n    invoke(ctx, "collect-evidence")\n\n@runner.phase("teardown")\ndef teardown(ctx):\n    # Per-iteration cleanup after evidence collection.\n    ctx.log("Completed the bounded external command")\n\n@runner.phase("finalize")\ndef finalize(ctx):\n    # Process-level finalization, performed once after the loop exits.\n    ctx.log("Finalized the external command evaluation")\n\nif __name__ == "__main__": runner.main()\n""",
            },
            {
                "id": "native-improvement-cycle",
                "name": "Native improvement cycle",
                "description": "Tracks a Git change candidate, validates fixed browser journeys, and promotes only repeatedly sufficient evidence. OpenOrbit owns all cycle state and never runs an external improvement script.",
                "source": """# Requirements\n# - PROJECT_ROOT is a Git repository.\n# - The evaluation build selects fixed browser test cases and a browser base URL.\n# - Candidate source changes are supplied through the normal reviewed change flow.\n# This runner never launches an external improvement script or commits a change.\n\nimport hashlib\nimport json\nimport re\nfrom pathlib import Path\n\nfrom orbit_sdk import runner\n\nREQUIRED_SUFFICIENT_EVALUATIONS = 3\n\ndef state_path(ctx):\n    build_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(ctx.evaluation_build.get("id") or "manual"))\n    directory = ctx.app_data / "improvement-cycles"\n    directory.mkdir(parents=True, exist_ok=True)\n    return directory / f"{build_id}.json"\n\ndef load_state(ctx):\n    path = state_path(ctx)\n    if not path.exists():\n        return {"candidate_fingerprint": None, "sufficient_evaluations": 0, "history": []}\n    return json.loads(path.read_text(encoding="utf-8"))\n\ndef save_state(ctx, state):\n    state["history"] = state.get("history", [])[-24:]\n    state_path(ctx).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")\n\ndef git(ctx, *args):\n    return ctx.exec(["git", *args], cwd=ctx.project_root, timeout=300)\n\ndef candidate(ctx):\n    patch = git(ctx, "diff", "--binary", "--")\n    changed = [line for line in git(ctx, "diff", "--name-only").splitlines() if line]\n    return (hashlib.sha256(patch.encode("utf-8")).hexdigest() if patch else None), changed\n\n@runner.phase("init")\ndef init(ctx):\n    git(ctx, "rev-parse", "--show-toplevel")\n    if not ctx.evaluation_build.get("browser_base_url") or not ctx.test_cases:\n        raise ValueError("Select a browser base URL and fixed test cases for a native improvement cycle")\n    ctx.log("Validated a Git-backed, OpenOrbit-native improvement cycle")\n\n@runner.phase("setup")\ndef setup(ctx):\n    fingerprint, changed = candidate(ctx)\n    ctx.emit_result({"improvement_cycle": {"iteration": ctx.loop_index, "candidate_fingerprint": fingerprint, "changed_paths": changed}})\n    ctx.log("Captured the candidate baseline before validation")\n\n@runner.phase("run")\ndef run(ctx):\n    evidence = ctx.playwright_journey()\n    results = evidence["results"]\n    passed = all(item["passed"] for item in results)\n    fingerprint, changed = candidate(ctx)\n    ctx.emit_result({"improvement_cycle": {"iteration": ctx.loop_index, "candidate_fingerprint": fingerprint, "changed_paths": changed, "passed": passed, "evidence": evidence}})\n    if not passed:\n        raise SystemExit("A fixed validation journey failed")\n\n@runner.phase("eval")\ndef evaluate(ctx):\n    state = load_state(ctx)\n    fingerprint, changed = candidate(ctx)\n    if not fingerprint:\n        state["candidate_fingerprint"] = None\n        state["sufficient_evaluations"] = 0\n        verdict = "no_candidate"\n    elif state.get("candidate_fingerprint") == fingerprint:\n        state["sufficient_evaluations"] = int(state.get("sufficient_evaluations", 0)) + 1\n        verdict = "ready_for_approval" if state["sufficient_evaluations"] >= REQUIRED_SUFFICIENT_EVALUATIONS else "continue_validation"\n    else:\n        state["candidate_fingerprint"] = fingerprint\n        state["sufficient_evaluations"] = 1\n        verdict = "continue_validation"\n    state.setdefault("history", []).append({"iteration": ctx.loop_index, "fingerprint": fingerprint, "paths": changed, "verdict": verdict})\n    save_state(ctx, state)\n    ctx.emit_result({"improvement_cycle": {"candidate_fingerprint": fingerprint, "changed_paths": changed, "sufficient_evaluations": state["sufficient_evaluations"], "required_evaluations": REQUIRED_SUFFICIENT_EVALUATIONS, "verdict": verdict}})\n    ctx.log(f"Candidate verdict: {verdict}")\n\n@runner.phase("teardown")\ndef teardown(ctx): ctx.log("Retained native improvement evidence for supervision")\n@runner.phase("finalize")\ndef finalize(ctx): ctx.log("Finalized the native improvement cycle without committing changes")\n\nif __name__ == "__main__": runner.main()\n""",
            },
        ]
        templates[-1] = {
            "id": "native-improvement-cycle",
            "name": "Prompt improvement validation",
            "description": "Applies accepted prompt improvements with rollback history, validates fixed browser journeys, and records review decisions.",
            "source": NATIVE_IMPROVEMENT_CYCLE_TEMPLATE,
        }
        templates.extend(
            (
                {
                    "id": "site-exploration",
                    "name": "Site exploration review",
                    "description": "Explores safe same-site links through LangGraph and retains rendered evidence for product feedback.",
                    "source": SITE_EXPLORATION_TEMPLATE,
                },
                {
                    "id": "json-agent-cycle",
                    "name": "User journey simulation",
                    "description": "Runs one bounded agent simulation per iteration while OpenOrbit retains fixed inputs, evidence, and supervision.",
                    "source": JSON_AGENT_CYCLE_TEMPLATE,
                },
                {
                    "id": "evidence-gated-probe-cycle",
                    "name": "Evidence-driven improvement gate",
                    "description": "Validates a fixed probe matrix and returns structured preflight, result, and evidence records for improvement decisions.",
                    "source": EVIDENCE_GATED_PROBE_CYCLE_TEMPLATE,
                },
            )
        )
        return templates

    def _custom_runner_templates(self) -> list[dict[str, str]]:
        templates = []
        for path in sorted(RUNNER_TEMPLATES.glob("*.py")):
            metadata = path.with_suffix(".json")
            if metadata.exists():
                values = json.loads(metadata.read_text(encoding="utf-8"))
                templates.append({**values, "source": path.read_text(encoding="utf-8"), "origin": "user"})
        return templates

    def available_runner_templates(self) -> list[dict[str, str]]:
        builtins = [{**item, "origin": "built-in"} for item in self.runner_templates()]
        return [*builtins, *self._custom_runner_templates()]

    def template_translation_input(self, kind: str, template_id: str) -> dict[str, Any]:
        """Return only display text that may safely be translated."""
        if kind == "runner-template":
            template = next(
                (item for item in self.available_runner_templates() if item["id"] == template_id), None
            )
            if template is None:
                raise KeyError(template_id)
            return {"name": template["name"], "description": template["description"]}
        if kind == "quick-start":
            quick_start = next((item for item in self.quick_starts() if item["id"] == template_id), None)
            if quick_start is None:
                raise KeyError(template_id)
            return {
                "name": quick_start["name"],
                "description": quick_start["description"],
                "parameters": [
                    {
                        **{"label": parameter["label"]},
                        **({"description": parameter["description"]} if "description" in parameter else {}),
                        **({"placeholder": parameter["placeholder"]} if "placeholder" in parameter else {}),
                        **(
                            {
                                "options": [
                                    {"label": option["label"]} for option in parameter.get("options", [])
                                ]
                            }
                            if "options" in parameter
                            else {}
                        ),
                    }
                    for parameter in quick_start["parameters"]
                ],
            }
        if kind == "supervisor-result":
            run_id, separator, iteration_value = template_id.partition(":")
            if not separator or not iteration_value.isdigit():
                raise ValueError("supervisor result translation ID must be run_id:iteration")
            record = next(
                (
                    item
                    for item in self._load(run_id).supervisor_results
                    if isinstance(item, dict) and int(item.get("iteration", 0)) == int(iteration_value)
                ),
                None,
            )
            response = record.get("response") if isinstance(record, dict) else None
            if not isinstance(response, dict):
                raise KeyError(template_id)

            def display_fields(item: Any, fields: tuple[str, ...]) -> dict[str, str]:
                return {
                    field: value
                    for field in fields
                    if isinstance((value := item.get(field)), str) and value.strip()
                }

            evaluation = response.get("evaluation")
            behavior_trace = evaluation.get("behavior_trace") if isinstance(evaluation, dict) else None
            return {
                **(
                    {"prompt": record["prompt"]}
                    if isinstance(record.get("prompt"), str) and record["prompt"].strip()
                    else {}
                ),
                "response": {
                    "evaluation": {
                        **(
                            display_fields(evaluation, ("behavior_summary", "summary"))
                            if isinstance(evaluation, dict)
                            else {}
                        ),
                        **(
                            {
                                "behavior_trace": display_fields(
                                    behavior_trace,
                                    ("purpose", "rationale", "observation", "decision", "next_action"),
                                )
                            }
                            if isinstance(behavior_trace, dict)
                            else {}
                        ),
                    },
                    "improvements": [
                        display_fields(
                            item,
                            (
                                "title",
                                "rationale",
                                "proposed_change",
                                "acceptanceEvidence",
                                "validation",
                                "rollback",
                            ),
                        )
                        for item in response.get("improvements", [])
                        if isinstance(item, dict)
                    ],
                    "reported_issues": [
                        display_fields(item, ("title", "evidence", "reproduction"))
                        for item in response.get("reported_issues", [])
                        if isinstance(item, dict)
                    ],
                },
            }
        raise ValueError("template translation kind is not supported")

    @staticmethod
    def validate_template_translation(source: Any, translated: Any) -> dict[str, Any]:
        """Accept the exact display-text shape and no executable metadata."""
        if isinstance(source, str):
            if not isinstance(translated, str):
                raise ValueError("translation must retain the requested text structure")
            return translated
        if isinstance(source, list):
            if not isinstance(translated, list) or len(source) != len(translated):
                raise ValueError("translation must retain the requested text structure")
            return [
                ConsoleStore.validate_template_translation(item, translated[index])
                for index, item in enumerate(source)
            ]
        if isinstance(source, dict):
            if not isinstance(translated, dict) or set(source) != set(translated):
                raise ValueError("translation must retain the requested text structure")
            return {
                key: ConsoleStore.validate_template_translation(value, translated[key])
                for key, value in source.items()
            }
        raise ValueError("translation source must contain text only")

    @staticmethod
    def _template_translation_key(kind: str, template_id: str, locale: str, source: dict[str, Any]) -> str:
        digest = hashlib.sha256(
            json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"{kind}:{template_id}:{locale}:{digest}"

    def cached_template_translation(
        self, kind: str, template_id: str, locale: str, source: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not TEMPLATE_TRANSLATIONS.exists():
            return None
        translations = json.loads(TEMPLATE_TRANSLATIONS.read_text(encoding="utf-8"))
        cached = translations.get(self._template_translation_key(kind, template_id, locale, source))
        return self.validate_template_translation(source, cached) if cached is not None else None

    def save_template_translation(
        self, kind: str, template_id: str, locale: str, source: dict[str, Any], translated: Any
    ) -> dict[str, Any]:
        content = self.validate_template_translation(source, translated)
        translations = (
            json.loads(TEMPLATE_TRANSLATIONS.read_text(encoding="utf-8"))
            if TEMPLATE_TRANSLATIONS.exists()
            else {}
        )
        translations[self._template_translation_key(kind, template_id, locale, source)] = content
        TEMPLATE_TRANSLATIONS.parent.mkdir(parents=True, exist_ok=True)
        temporary = TEMPLATE_TRANSLATIONS.with_suffix(".tmp")
        temporary.write_text(json.dumps(translations, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(TEMPLATE_TRANSLATIONS)
        return content

    @staticmethod
    def _quick_start_browser_runner() -> str:
        return """from orbit_sdk import runner

@runner.phase("init")
def init(ctx):
    if not ctx.evaluation_build.get("browser_base_url"):
        raise ValueError("Quick start browser evaluation requires a browser base URL")

@runner.phase("run")
def run(ctx):
    evidence = ctx.playwright_journey()
    if not all(item["passed"] for item in evidence["results"]):
        raise SystemExit("A browser journey failed")

@runner.phase("eval")
def evaluate(ctx):
    ctx.log("Quick start browser evaluation completed")

if __name__ == "__main__":
    runner.main()
"""

    def _built_in_quick_starts(self) -> list[dict[str, Any]]:
        return [
            {
                "schema_version": 1,
                "id": "openorbit.user-journey-smoke-test",
                "version": "1.0.1",
                "name": "User journey smoke test",
                "description": "Create a browser-based smoke test. Requires a running app and Playwright browser.",
                "publisher": {"name": "OpenOrbit"},
                "parameters": [
                    {
                        "key": "build_name",
                        "label": "Evaluation name",
                        "type": "string",
                        "required": True,
                        "default": "Browser quality check",
                    },
                    {
                        "key": "repository",
                        "label": "Target repository",
                        "type": "workspace",
                        "required": True,
                        "placeholder": "/absolute/path/to/your-repository",
                    },
                    {
                        "key": "base_url",
                        "label": "Browser base URL",
                        "type": "url",
                        "required": True,
                        "placeholder": "http://localhost:3000",
                    },
                    {
                        "key": "journey_name",
                        "label": "User journey name",
                        "type": "string",
                        "required": True,
                        "default": "Home page smoke test",
                        "placeholder": "e.g. Sign in and view orders",
                    },
                    {
                        "key": "journey_path",
                        "label": "Journey start path",
                        "type": "string",
                        "required": True,
                        "default": "/",
                        "placeholder": "e.g. /login",
                    },
                    {
                        "key": "journey_prompt",
                        "label": "User actions",
                        "type": "string",
                        "required": True,
                        "placeholder": "e.g. Sign in with the test account and open order history.",
                    },
                    {
                        "key": "acceptance",
                        "label": "Success condition",
                        "type": "string",
                        "required": True,
                        "placeholder": "e.g. The order history page loads without an error.",
                    },
                    {
                        "key": "expected_text",
                        "label": "Expected visible text (optional)",
                        "type": "string",
                        "required": False,
                        "placeholder": "e.g. Recent orders",
                    },
                    {
                        "key": "profile_name",
                        "label": "AI model profile name",
                        "type": "string",
                        "required": True,
                        "default": "Browser quality AI",
                        "placeholder": "e.g. Evaluation GPT-4o",
                    },
                    {
                        "key": "provider",
                        "label": "AI provider",
                        "type": "select",
                        "required": True,
                        "default": "azure-openai",
                        "options": [
                            {"value": "azure-openai", "label": "Azure OpenAI"},
                            {"value": "aws-bedrock", "label": "AWS Bedrock"},
                        ],
                    },
                    {
                        "key": "model",
                        "label": "Model / deployment",
                        "type": "string",
                        "required": True,
                        "placeholder": "e.g. gpt-4o",
                    },
                    {
                        "key": "endpoint",
                        "label": "Provider endpoint",
                        "type": "url",
                        "required": False,
                        "placeholder": "https://your-resource.openai.azure.com",
                    },
                    {
                        "key": "region",
                        "label": "Region",
                        "type": "string",
                        "required": True,
                        "default": "us-east-1",
                        "placeholder": "e.g. eastus",
                    },
                    {
                        "key": "secret_env",
                        "label": "API key environment variable",
                        "type": "string",
                        "required": True,
                        "default": "AZURE_OPENAI_API_KEY",
                        "placeholder": "e.g. AZURE_OPENAI_API_KEY",
                    },
                ],
                "assets": {
                    "runner": {
                        "name": "${build_name} runner",
                        "description": "Browser journey runner created by Quick Start.",
                        "template_id": "quickstart-browser",
                        "source": self._quick_start_browser_runner(),
                    },
                    "prompt_template": {
                        "name": "${build_name} policy",
                        "version": 1,
                        "content": "Assess the fixed browser journey evidence and return the required evaluation JSON.",
                    },
                    "test_case_set": {
                        "name": "${build_name} smoke tests",
                        "description": "A smoke journey created by Quick Start.",
                        "cases": [
                            {
                                "id": "primary-journey",
                                "name": "${journey_name}",
                                "path": "${journey_path}",
                                "prompt": "${journey_prompt}",
                                "acceptance": "${acceptance}",
                                "expected_text": "${expected_text}",
                            }
                        ],
                    },
                    "execution_environment": {"name": "${build_name} execution", "executor_type": "local"},
                    "target_environment": {
                        "name": "${build_name} target",
                        "repository": "${repository}",
                        "browser_base_url": "${base_url}",
                    },
                    "model_profile": {
                        "profile_name": "${profile_name}",
                        "provider": "${provider}",
                        "model": "${model}",
                        "endpoint": "${endpoint}",
                        "region": "${region}",
                        "secret_env": "${secret_env}",
                    },
                },
                "build": {
                    "name": "${build_name}",
                    "purpose": "Evaluate the browser journey created by Quick Start.",
                    "model_profile_name": "${profile_name}",
                    "timezone": "Asia/Tokyo",
                    "repeat_interval_minutes": 30,
                    "run_limit": 1,
                    "approval_score": 8,
                    "enabled": True,
                },
            },
            {
                "schema_version": 1,
                "id": "openorbit.site-exploration-review",
                "version": "1.0.0",
                "name": "Site exploration review",
                "description": "Explore a site through safe links and leave evidence-backed product feedback. Requires a running app, Playwright browser, and LangGraph.",
                "publisher": {"name": "OpenOrbit"},
                "parameters": [
                    {
                        "key": "build_name",
                        "label": "Evaluation name",
                        "type": "string",
                        "required": True,
                        "default": "Site exploration review",
                    },
                    {
                        "key": "repository",
                        "label": "Target repository",
                        "type": "workspace",
                        "required": True,
                        "placeholder": "/absolute/path/to/your-repository",
                    },
                    {
                        "key": "base_url",
                        "label": "Browser base URL",
                        "type": "url",
                        "required": True,
                        "placeholder": "http://localhost:3000",
                    },
                    {
                        "key": "review_focus",
                        "label": "Review focus",
                        "type": "string",
                        "required": True,
                        "default": "clarity, usefulness, and friction",
                        "placeholder": "e.g. first-time visitor experience",
                    },
                    {
                        "key": "profile_name",
                        "label": "AI model profile name",
                        "type": "string",
                        "required": True,
                        "default": "Site exploration AI",
                    },
                    {
                        "key": "provider",
                        "label": "AI provider",
                        "type": "select",
                        "required": True,
                        "default": "azure-openai",
                        "options": [
                            {"value": "azure-openai", "label": "Azure OpenAI"},
                            {"value": "aws-bedrock", "label": "AWS Bedrock"},
                        ],
                    },
                    {
                        "key": "model",
                        "label": "Model / deployment",
                        "type": "string",
                        "required": True,
                        "placeholder": "e.g. gpt-4o",
                    },
                    {
                        "key": "endpoint",
                        "label": "Provider endpoint",
                        "type": "url",
                        "required": False,
                        "placeholder": "https://your-resource.openai.azure.com",
                    },
                    {
                        "key": "region",
                        "label": "Region",
                        "type": "string",
                        "required": True,
                        "default": "us-east-1",
                    },
                    {
                        "key": "secret_env",
                        "label": "API key environment variable",
                        "type": "string",
                        "required": True,
                        "default": "AZURE_OPENAI_API_KEY",
                    },
                ],
                "assets": {
                    "runner": {
                        "name": "${build_name} runner",
                        "description": "LangGraph site exploration runner created by Quick Start.",
                        "template_id": "site-exploration",
                        "source": SITE_EXPLORATION_TEMPLATE,
                    },
                    "prompt_template": {
                        "name": "${build_name} policy",
                        "version": 1,
                        "content": "Review the site-exploration evidence for ${review_focus}. Give an evidence-backed product opinion and report reproducible friction or defects only.",
                    },
                    "test_case_set": {
                        "name": "${build_name} exploration",
                        "description": "Bounded site exploration created by Quick Start.",
                        "cases": [
                            {
                                "id": "site-exploration",
                                "name": "Explore site",
                                "path": "/",
                                "prompt": "Follow safe same-site links.",
                                "acceptance": "Capture rendered page evidence.",
                            }
                        ],
                    },
                    "execution_environment": {"name": "${build_name} execution", "executor_type": "local"},
                    "target_environment": {
                        "name": "${build_name} target",
                        "repository": "${repository}",
                        "browser_base_url": "${base_url}",
                    },
                    "model_profile": {
                        "profile_name": "${profile_name}",
                        "provider": "${provider}",
                        "model": "${model}",
                        "endpoint": "${endpoint}",
                        "region": "${region}",
                        "secret_env": "${secret_env}",
                    },
                },
                "build": {
                    "name": "${build_name}",
                    "purpose": "Explore a site and assess the rendered experience.",
                    "model_profile_name": "${profile_name}",
                    "timezone": "Asia/Tokyo",
                    "repeat_interval_minutes": 30,
                    "run_limit": 1,
                    "approval_score": 8,
                    "enabled": True,
                },
            },
            {
                "schema_version": 1,
                "id": "openorbit.agent-self-improvement",
                "version": "1.1.0",
                "name": "Agent self-improvement",
                "description": "Improve a managed prompt from retained responses of the real target AI. Requires a Git repository, prompt file, and configured model profile.",
                "publisher": {"name": "OpenOrbit"},
                "parameters": [
                    {
                        "key": "build_name",
                        "label": "Evaluation name",
                        "type": "string",
                        "required": True,
                        "default": "Agent self-improvement",
                    },
                    {
                        "key": "repository",
                        "label": "Git repository",
                        "type": "workspace",
                        "required": True,
                        "placeholder": "/absolute/path/to/your-git-repository",
                    },
                    {
                        "key": "base_url",
                        "label": "Browser base URL (optional)",
                        "type": "url",
                        "required": False,
                        "placeholder": "Not used for target-AI response evaluation",
                    },
                    {
                        "key": "managed_prompt_path",
                        "label": "Agent prompt file path",
                        "type": "string",
                        "required": True,
                        "default": "examples/agent-improvement-sample-prompt.md",
                        "placeholder": "e.g. prompts/system.md",
                    },
                    {
                        "key": "journey_name",
                        "label": "Test case name",
                        "type": "string",
                        "required": True,
                        "default": "Missing refund context",
                        "placeholder": "e.g. Missing order details",
                    },
                    {
                        "key": "journey_prompt",
                        "label": "User request",
                        "type": "string",
                        "required": True,
                        "placeholder": "e.g. I need a refund, but I do not have my order number.",
                    },
                    {
                        "key": "acceptance",
                        "label": "Success condition",
                        "type": "string",
                        "required": True,
                        "placeholder": "e.g. The response is complete, grounded, and has no error.",
                    },
                    {
                        "key": "profile_name",
                        "label": "AI model profile name",
                        "type": "string",
                        "required": True,
                        "default": "Agent improvement AI",
                        "placeholder": "e.g. Agent evaluation GPT-4o",
                    },
                    {
                        "key": "provider",
                        "label": "AI provider",
                        "type": "select",
                        "required": True,
                        "default": "azure-openai",
                        "options": [
                            {"value": "azure-openai", "label": "Azure OpenAI"},
                            {"value": "aws-bedrock", "label": "AWS Bedrock"},
                        ],
                    },
                    {
                        "key": "model",
                        "label": "Model / deployment",
                        "type": "string",
                        "required": True,
                        "placeholder": "e.g. gpt-4o",
                    },
                    {
                        "key": "endpoint",
                        "label": "Provider endpoint",
                        "type": "url",
                        "required": False,
                        "placeholder": "https://your-resource.openai.azure.com",
                    },
                    {
                        "key": "region",
                        "label": "Region",
                        "type": "string",
                        "required": True,
                        "default": "us-east-1",
                        "placeholder": "e.g. eastus",
                    },
                    {
                        "key": "secret_env",
                        "label": "API key environment variable",
                        "type": "string",
                        "required": True,
                        "default": "AZURE_OPENAI_API_KEY",
                        "placeholder": "e.g. AZURE_OPENAI_API_KEY",
                    },
                ],
                "assets": {
                    "runner": {
                        "name": "${build_name} runner",
                        "description": "Agent self-improvement runner created by Quick Start.",
                        "template_id": "native-improvement-cycle",
                        "source": NATIVE_IMPROVEMENT_CYCLE_TEMPLATE,
                    },
                    "prompt_template": {
                        "name": "${build_name} policy",
                        "version": 1,
                        "content": "Evaluate the managed agent prompt strictly against retained responses from the real target AI. Compare each response with its fixed user request and acceptance criterion. Check scope and task clarity; grounding in observable product evidence; uncertainty and missing-context handling; safety and refusal boundaries; and an actionable next step. For every unmet criterion observed in an actual response, return one concrete, non-duplicative prompt improvement with validation and rollback evidence. Never repeat an instruction already present in the managed prompt or its accepted-proposals block. Mark a low-risk, additive, reversible prompt-only improvement adopted only when it is directly supported by the observed response and has measurable response-level acceptance evidence. Keep code, infrastructure, policy, or insufficiently evidenced changes proposed. Return empty arrays only when every criterion is demonstrably met.",
                    },
                    "test_case_set": {
                        "name": "${build_name} validation",
                        "description": "A fixed agent validation journey created by Quick Start.",
                        "cases": [
                            {
                                "id": "agent-journey",
                                "name": "${journey_name}",
                                "prompt": "${journey_prompt}",
                                "acceptance": "${acceptance}",
                            }
                        ],
                    },
                    "execution_environment": {"name": "${build_name} execution", "executor_type": "local"},
                    "target_environment": {
                        "name": "${build_name} target",
                        "repository": "${repository}",
                        "browser_base_url": "${base_url}",
                        "managed_prompt_path": "${managed_prompt_path}",
                    },
                    "model_profile": {
                        "profile_name": "${profile_name}",
                        "provider": "${provider}",
                        "model": "${model}",
                        "endpoint": "${endpoint}",
                        "region": "${region}",
                        "secret_env": "${secret_env}",
                    },
                },
                "build": {
                    "name": "${build_name}",
                    "purpose": "Validate and improve a managed prompt with retained responses from the real target AI.",
                    "model_profile_name": "${profile_name}",
                    "timezone": "Asia/Tokyo",
                    "repeat_interval_minutes": 30,
                    "run_limit": 3,
                    "approval_score": 8,
                    "enabled": True,
                },
            },
            {
                "schema_version": 1,
                "id": "openorbit.ai-slo-drift-monitor",
                "version": "1.0.0",
                "name": "AI SLO and behavior drift monitor",
                "description": "Repeatedly assess AI quality, safety, latency, and cost against a fixed baseline. Connects an existing structured AI evaluator; OpenOrbit retains the evidence, supervision, and improvement decisions.",
                "publisher": {"name": "OpenOrbit"},
                "parameters": [
                    {
                        "key": "build_name",
                        "label": "Evaluation name",
                        "type": "string",
                        "required": True,
                        "default": "AI operational SLO monitor",
                    },
                    {
                        "key": "repository",
                        "label": "Evaluator workspace",
                        "type": "workspace",
                        "required": True,
                        "placeholder": "/absolute/path/to/your-ai-evaluator",
                    },
                    {
                        "key": "probe_command",
                        "label": "Structured evaluator command",
                        "type": "string",
                        "required": True,
                        "placeholder": "e.g. uv run ai-eval",
                        "description": "A command that supports preflight, prepare, run-probes, and collect-evidence and returns JSON for each action.",
                    },
                    {
                        "key": "slo_focus",
                        "label": "SLO focus",
                        "type": "string",
                        "required": True,
                        "default": "response quality, policy compliance, latency, and cost",
                        "placeholder": "e.g. grounded answers and p95 latency under 3 seconds",
                    },
                    {
                        "key": "profile_name",
                        "label": "AI model profile name",
                        "type": "string",
                        "required": True,
                        "default": "AI operations supervisor",
                    },
                    {
                        "key": "provider",
                        "label": "AI provider",
                        "type": "select",
                        "required": True,
                        "default": "azure-openai",
                        "options": [
                            {"value": "azure-openai", "label": "Azure OpenAI"},
                            {"value": "aws-bedrock", "label": "AWS Bedrock"},
                        ],
                    },
                    {
                        "key": "model",
                        "label": "Model / deployment",
                        "type": "string",
                        "required": True,
                        "placeholder": "e.g. gpt-4o",
                    },
                    {
                        "key": "endpoint",
                        "label": "Provider endpoint",
                        "type": "url",
                        "required": False,
                        "placeholder": "https://your-resource.openai.azure.com",
                    },
                    {
                        "key": "region",
                        "label": "Region",
                        "type": "string",
                        "required": True,
                        "default": "us-east-1",
                    },
                    {
                        "key": "secret_env",
                        "label": "API key environment variable",
                        "type": "string",
                        "required": True,
                        "default": "AZURE_OPENAI_API_KEY",
                    },
                ],
                "assets": {
                    "runner": {
                        "name": "${build_name} runner",
                        "description": "Evidence-gated AI SLO and drift monitor created by Quick Start.",
                        "template_id": "evidence-gated-probe-cycle",
                        "source": EVIDENCE_GATED_PROBE_CYCLE_TEMPLATE,
                    },
                    "prompt_template": {
                        "name": "${build_name} policy",
                        "version": 1,
                        "content": "Review the fixed AI SLO evidence for ${slo_focus}. Compare each reported metric with its retained baseline and threshold. Report only evidence-backed drift, regressions, or risks; propose reversible improvements with explicit validation and rollback steps.",
                    },
                    "test_case_set": {
                        "name": "${build_name} probe matrix",
                        "description": "A fixed, repeatable AI operational SLO probe matrix.",
                        "cases": [
                            {
                                "id": "ai-slo-drift",
                                "name": "AI SLO and behavior drift",
                                "path": "/",
                                "prompt": "Evaluate ${slo_focus} against the evaluator's fixed representative input matrix.",
                                "acceptance": "Return structured current metrics, baseline comparisons, configured thresholds, outliers, and reproducible evidence for every detected drift.",
                            }
                        ],
                    },
                    "execution_environment": {
                        "name": "${build_name} execution",
                        "executor_type": "local",
                        "environment_variables": {"ORBIT_PROBE_COMMAND": "${probe_command}"},
                    },
                    "target_environment": {"name": "${build_name} target", "repository": "${repository}"},
                    "model_profile": {
                        "profile_name": "${profile_name}",
                        "provider": "${provider}",
                        "model": "${model}",
                        "endpoint": "${endpoint}",
                        "region": "${region}",
                        "secret_env": "${secret_env}",
                    },
                },
                "build": {
                    "name": "${build_name}",
                    "purpose": "Continuously monitor AI operational SLOs and behavior drift with retained evidence.",
                    "model_profile_name": "${profile_name}",
                    "timezone": "Asia/Tokyo",
                    "repeat_interval_minutes": 1440,
                    "run_limit": 30,
                    "approval_score": 8,
                    "enabled": True,
                },
            },
        ]

    @staticmethod
    def _public_quick_start(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            key: deepcopy(manifest.get(key))
            for key in ("schema_version", "id", "version", "name", "description", "publisher", "parameters")
        }

    def quick_starts(self) -> list[dict[str, Any]]:
        custom = []
        for path in sorted(QUICK_STARTS.glob("*.json")):
            try:
                custom.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        manifests = [*self._built_in_quick_starts(), *custom]
        return [self._public_quick_start(item) for item in manifests]

    def _quick_start(self, quick_start_id: str) -> dict[str, Any]:
        for manifest in self._built_in_quick_starts():
            if manifest["id"] == quick_start_id:
                return manifest
        path = QUICK_STARTS / f"{quick_start_id}.json"
        if not path.exists():
            raise KeyError(quick_start_id)
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _validate_quick_start(manifest: dict[str, Any]) -> dict[str, Any]:
        required = ("schema_version", "id", "version", "name", "description", "parameters", "assets", "build")
        if not isinstance(manifest, dict) or any(key not in manifest for key in required):
            raise ValueError("quick start requires schema_version, identity, parameters, assets, and build")
        if manifest["schema_version"] != 1 or not re.fullmatch(
            r"[a-z][a-z0-9.-]{2,127}", str(manifest["id"])
        ):
            raise ValueError("quick start must use schema version 1 and a lowercase qualified ID")
        if (
            not isinstance(manifest["parameters"], list)
            or not isinstance(manifest["assets"], dict)
            or not isinstance(manifest["build"], dict)
        ):
            raise ValueError("quick start parameters, assets, and build must be structured values")
        keys = [str(item.get("key", "")) for item in manifest["parameters"] if isinstance(item, dict)]
        if (
            len(keys) != len(manifest["parameters"])
            or not all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) for key in keys)
            or len(set(keys)) != len(keys)
        ):
            raise ValueError("quick start parameter keys must be unique lowercase identifiers")
        for key in (
            "runner",
            "prompt_template",
            "test_case_set",
            "execution_environment",
            "target_environment",
        ):
            if not isinstance(manifest["assets"].get(key), dict):
                raise ValueError(f"quick start requires a {key} asset")
        if not str(manifest["assets"]["runner"].get("source", "")).strip():
            raise ValueError("quick start runner requires source")
        compile(str(manifest["assets"]["runner"]["source"]), f"{manifest['id']}.py", "exec")
        return manifest

    def import_quick_start(self, manifest: dict[str, Any]) -> dict[str, Any]:
        manifest = self._validate_quick_start(manifest)
        if (
            any(item["id"] == manifest["id"] for item in self._built_in_quick_starts())
            or (QUICK_STARTS / f"{manifest['id']}.json").exists()
        ):
            raise ValueError("quick start ID already exists")
        (QUICK_STARTS / f"{manifest['id']}.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self._public_quick_start(manifest)

    @staticmethod
    def _substitute(value: Any, inputs: dict[str, str]) -> Any:
        if isinstance(value, str):
            return re.sub(
                r"\$\{([a-z][a-z0-9_]*)\}", lambda match: inputs.get(match.group(1), match.group(0)), value
            )
        if isinstance(value, list):
            return [ConsoleStore._substitute(item, inputs) for item in value]
        if isinstance(value, dict):
            return {key: ConsoleStore._substitute(item, inputs) for key, item in value.items()}
        return value

    def instantiate_quick_start(self, quick_start_id: str, inputs: dict[str, str]) -> dict[str, Any]:
        manifest = self._validate_quick_start(self._quick_start(quick_start_id))
        values = {str(key): str(value).strip() for key, value in inputs.items()}
        for parameter in manifest["parameters"]:
            key = parameter["key"]
            if not values.get(key) and parameter.get("default") is not None:
                values[key] = str(parameter["default"])
            if parameter.get("required") and not values.get(key):
                raise ValueError(f"quick start parameter '{key}' is required")
            values.setdefault(key, "")
        token = uuid.uuid4().hex[:8]
        prefix = re.sub(r"[^a-z0-9]+", "-", quick_start_id.lower()).strip("-")[-36:]
        generated = {
            "runner_id": f"qs-{prefix}-{token}-runner",
            "prompt_template_id": f"qs-{prefix}-{token}-policy",
            "test_case_set_id": f"qs-{prefix}-{token}-tests",
            "execution_environment_id": f"qs-{prefix}-{token}-execution",
            "target_environment_id": f"qs-{prefix}-{token}-target",
            "build_id": f"qs-{prefix}-{token}",
        }
        resolved = self._substitute(manifest, values)
        assets, build = resolved["assets"], resolved["build"]
        snapshots = {
            path: path.read_bytes() if path.exists() else None
            for path in (
                EXECUTION_ENVIRONMENTS,
                TARGET_ENVIRONMENTS,
                TARGET_TEST_CASE_SETS,
                CONFIG / "prompt-templates.yaml",
                CONFIG / "evaluation-builds.yaml",
                QUICK_START_INSTANCES,
                SETTINGS,
            )
        }
        runner_paths = [RUNNERS / f"{generated['runner_id']}.py", RUNNERS / f"{generated['runner_id']}.json"]
        try:
            runner = self.create_runner({"id": generated["runner_id"], **assets["runner"]})
            prompt = self.create_prompt_template(
                {"id": generated["prompt_template_id"], **assets["prompt_template"]}
            )
            tests = self.create_target_test_case_set(
                {"id": generated["test_case_set_id"], **assets["test_case_set"]}
            )
            execution = self.create_execution_environment(
                {"id": generated["execution_environment_id"], **assets["execution_environment"]}
            )
            target = self.create_target_environment(
                {"id": generated["target_environment_id"], **assets["target_environment"]}
            )
            if isinstance(assets.get("model_profile"), dict):
                profile_name = str(assets["model_profile"].get("profile_name", "")).strip()
                if any(item["profile_name"] == profile_name for item in self.profiles()):
                    raise ValueError("AI model profile name already exists")
                self.save_settings(assets["model_profile"])
            created = self.create_evaluation_build(
                {
                    "id": generated["build_id"],
                    "runner_id": runner["id"],
                    "manager_template_id": prompt["id"],
                    "test_case_set_id": tests["id"],
                    "execution_environment_id": execution["id"],
                    "target_environment_id": target["id"],
                    **build,
                }
            )
            instances = self._asset_list(QUICK_START_INSTANCES)
            instances.append(
                {
                    "quick_start_id": quick_start_id,
                    "version": manifest["version"],
                    "inputs": values,
                    "generated": generated,
                    "created_at": now().isoformat(),
                }
            )
            self._save_asset_list(QUICK_START_INSTANCES, instances)
            return {"build": created, "generated": generated}
        except Exception:
            for path, content in snapshots.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
            for path in runner_paths:
                path.unlink(missing_ok=True)
            raise

    def create_runner_template(self, values: dict[str, str]) -> dict[str, str]:
        template_id = str(values["id"])
        if any(item["id"] == template_id for item in self.available_runner_templates()):
            raise ValueError("runner template ID already exists")
        return self._write_runner_template(template_id, values)

    def _write_runner_template(self, template_id: str, values: dict[str, str]) -> dict[str, str]:
        source = str(values["source"])
        compile(source, f"{template_id}.py", "exec")
        template = {
            "id": template_id,
            "name": str(values["name"]).strip(),
            "description": str(values["description"]).strip(),
        }
        if not template["name"] or not template["description"]:
            raise ValueError("runner template requires a name and description")
        (RUNNER_TEMPLATES / f"{template_id}.py").write_text(source, encoding="utf-8")
        (RUNNER_TEMPLATES / f"{template_id}.json").write_text(
            json.dumps(template, indent=2), encoding="utf-8"
        )
        return {**template, "source": source, "origin": "user"}

    def update_runner_template(self, template_id: str, values: dict[str, str]) -> dict[str, str]:
        if not any(item["id"] == template_id for item in self._custom_runner_templates()):
            raise KeyError(template_id)
        return self._write_runner_template(template_id, values)

    def delete_runner_template(self, template_id: str) -> None:
        if not any(item["id"] == template_id for item in self._custom_runner_templates()):
            raise KeyError(template_id)
        (RUNNER_TEMPLATES / f"{template_id}.py").unlink(missing_ok=True)
        (RUNNER_TEMPLATES / f"{template_id}.json").unlink(missing_ok=True)

    def runners(self) -> list[dict[str, str]]:
        assets = []
        for path in sorted(RUNNERS.glob("*.py")):
            metadata = path.with_suffix(".json")
            if metadata.exists():
                values = json.loads(metadata.read_text(encoding="utf-8"))
                assets.append({**values, "source": path.read_text(encoding="utf-8")})
        return assets

    def _runner(self, runner_id: str) -> dict[str, str]:
        return next(item for item in self.runners() if item["id"] == runner_id)

    def create_runner(self, values: dict[str, str]) -> dict[str, str]:
        if any(item["id"] == values["id"] for item in self.runners()):
            raise ValueError("runner ID already exists")
        return self._write_runner(values["id"], values)

    def update_runner(self, runner_id: str, values: dict[str, str]) -> dict[str, str]:
        existing = self._runner(runner_id)
        return self._write_runner(
            runner_id, {**existing, **{key: value for key, value in values.items() if value is not None}}
        )

    def _write_runner(self, runner_id: str, values: dict[str, str]) -> dict[str, str]:
        source = str(values["source"])
        compile(source, f"{runner_id}.py", "exec")
        asset = {
            "id": runner_id,
            "name": str(values["name"]).strip(),
            "description": str(values["description"]).strip(),
            "template_id": str(values.get("template_id", "custom")),
            "created_at": str(values.get("created_at") or now().isoformat()),
        }
        if not asset["name"] or not asset["description"]:
            raise ValueError("runner requires a name and description")
        source_path, metadata_path = RUNNERS / f"{runner_id}.py", RUNNERS / f"{runner_id}.json"
        source_path.write_text(source, encoding="utf-8")
        metadata_path.write_text(json.dumps(asset, indent=2), encoding="utf-8")
        return {**asset, "source": source}

    @staticmethod
    def _open_in_vscode(path: Path) -> None:
        """Open a local, already-validated asset through the shared VS Code launcher."""
        executable = shutil.which("code")
        if executable is None:
            raise ValueError("VS Code command-line launcher 'code' is not available")
        subprocess.Popen([executable, "--reuse-window", str(path)])

    def open_runner_in_vscode(self, runner_id: str) -> dict[str, str]:
        self._runner(runner_id)
        self._open_in_vscode(RUNNERS / f"{runner_id}.py")
        return {"status": "opened"}

    def delete_runner(self, runner_id: str) -> None:
        self._runner(runner_id)
        if any(build.get("runner_id") == runner_id for build in self.evaluation_builds()):
            raise ValueError("runner is used by an evaluation build")
        (RUNNERS / f"{runner_id}.py").unlink(missing_ok=True)
        (RUNNERS / f"{runner_id}.json").unlink(missing_ok=True)

    def _runner_execution_plan(self, runner_id: str) -> Workflow:
        """Build the lifecycle declared by a runner without a workflow asset."""
        runner = self._runner(runner_id)
        lifecycle_order = ("init", "setup", "run", "eval", "teardown", "finalize")
        declared = set(re.findall(r'@runner\.phase\(\s*["\']([^"\']+)["\']\s*\)', runner["source"]))
        phases = [phase for phase in lifecycle_order if phase in declared]
        if not phases:
            raise ValueError("runner must declare at least one Orbit lifecycle phase")
        steps = [
            Step(
                id=phase,
                phase=phase,
                name=phase,
                command=[sys.executable, str(RUNNERS / f"{runner_id}.py"), "--phase", phase],
                working_directory=str(ROOT),
                timeout_seconds=86_400 if phase == "run" else 300,
                approval="not_required",
                # A non-zero process exit means the lifecycle did not produce
                # a valid evaluation. Runners that intentionally tolerate a
                # probe failure must model it as structured evidence instead.
                on_failure="stop",
            )
            for phase in phases
        ]
        return Workflow(
            id=runner_id,
            name=runner["name"],
            description=runner["description"],
            kind="improvement" if runner.get("template_id") == "native-improvement-cycle" else "simulation",
            enabled=True,
            risk="medium",
            runner_id=runner_id,
            steps=steps,
            test_steps=deepcopy(steps),
        )

    def evaluation_builds(self) -> list[dict[str, Any]]:
        path = CONFIG / "evaluation-builds.yaml"
        builds = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []
        builds = builds if isinstance(builds, list) else []
        fallback = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat() if path.exists() else None
        runs = self.runs()
        for build in builds:
            # Existing builds predate this optional policy, so leave it off
            # unless an operator explicitly enabled it.
            build.setdefault("require_human_approval_before_apply", False)
            self._hydrate_build_environment(build)
            build.update(self._repository_metadata(str(build.get("repository", ""))))
            build.setdefault("created_at", fallback)
            dates = [run.created_at for run in runs if run.evaluation_build_id == build["id"]]
            build["last_run_at"] = max(dates).isoformat() if dates else None
        return builds

    def _hydrate_build_environment(self, build: dict[str, Any]) -> None:
        """Project reusable environment assets onto legacy runtime build fields."""
        execution_id = str(build.get("execution_environment_id", ""))
        target_id = str(build.get("target_environment_id", ""))
        execution = next(
            (item for item in self.execution_environments() if item.get("id") == execution_id), None
        )
        target = next((item for item in self.target_environments() if item.get("id") == target_id), None)
        if execution:
            build["executor"] = execution.get("executor", {"type": "local"})
            build["browser_executable_path"] = execution.get("browser_executable_path", "")
            build["browser_library_path"] = execution.get("browser_library_path", "")
        if target:
            build["repository"] = target.get("repository", "")
            build["browser_base_url"] = target.get("browser_base_url", "")
            # This is runner-specific target configuration, not supervisor prompt input.
            build["managed_prompt_path"] = target.get("managed_prompt_path", build.get("prompt_bundle", ""))
            build["prompt_bundle"] = build["managed_prompt_path"]  # Legacy runner compatibility.

    @staticmethod
    def _repository_metadata(value: str) -> dict[str, str | bool]:
        path = Path(value).expanduser()
        if value.startswith("remote://"):
            return {
                "repository_name": value.removeprefix("remote://"),
                "repository_is_git": False,
                "repository_error": "A remote invocation is not a local Git working tree.",
            }
        if not path.is_dir():
            return {
                "repository_name": path.name or value,
                "repository_is_git": False,
                "repository_error": "Repository folder does not exist.",
            }
        probe = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True
        )
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return {
                "repository_name": path.name,
                "repository_is_git": False,
                "repository_error": "This folder is not a Git working tree.",
            }
        remote = subprocess.run(
            ["git", "-C", str(path), "config", "--get", "remote.origin.url"], capture_output=True, text=True
        ).stdout.strip()
        name = (
            remote.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
            if remote
            else path.name
        )
        return {"repository_name": name, "repository_is_git": True, "repository_error": ""}

    @staticmethod
    def _executor_from_values(values: dict[str, Any]) -> dict[str, Any]:
        if values.get("executor_type") == "local":
            return {"type": "local"}
        headers = values.get("remote_headers", {})
        if not isinstance(headers, dict):
            raise ValueError("remote HTTP headers must be an object")
        normalized_headers = {
            str(name).strip(): str(value) for name, value in headers.items() if str(name).strip()
        }
        invocation = RemoteInvocation(
            endpoint=str(values.get("remote_endpoint", "")).strip(),
            method=str(values.get("remote_method", "POST")),
            timeout_seconds=int(values.get("remote_timeout_seconds", 60)),
            headers=normalized_headers,
        )
        invocation.validate()
        return {
            "type": "remote-http",
            "endpoint": invocation.endpoint,
            "method": invocation.method,
            "timeout_seconds": invocation.timeout_seconds,
            "headers": normalized_headers,
        }

    @staticmethod
    def _environment_variables_from_values(values: dict[str, Any]) -> dict[str, str]:
        variables = values.get("environment_variables", {})
        if not isinstance(variables, dict):
            raise ValueError("execution environment variables must be an object")
        allowed_orbit_variables = {
            "ORBIT_ADAPTER_COMMAND",
            "ORBIT_AGENT_COMMAND",
            "ORBIT_PROBE_COMMAND",
        }
        normalized = {str(key).strip(): str(value) for key, value in variables.items()}
        if any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
            or (key.startswith("ORBIT_") and key not in allowed_orbit_variables)
            for key in normalized
        ):
            raise ValueError("execution environment variables include an unsupported name")
        return normalized

    @staticmethod
    def _asset_list(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        values = yaml.safe_load(path.read_text(encoding="utf-8"))
        return values if isinstance(values, list) else []

    @staticmethod
    def _save_asset_list(path: Path, values: list[dict[str, Any]]) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(yaml.safe_dump(values, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(path)

    def execution_environments(self) -> list[dict[str, Any]]:
        return self._asset_list(EXECUTION_ENVIRONMENTS)

    def target_environments(self) -> list[dict[str, Any]]:
        return self._asset_list(TARGET_ENVIRONMENTS)

    def _execution_environment(self, environment_id: str) -> dict[str, Any]:
        return next(item for item in self.execution_environments() if item.get("id") == environment_id)

    def _target_environment(self, environment_id: str) -> dict[str, Any]:
        return next(item for item in self.target_environments() if item.get("id") == environment_id)

    def _build_environment_values(self, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        execution_id, target_id = (
            str(values.get("execution_environment_id", "")).strip(),
            str(values.get("target_environment_id", "")).strip(),
        )
        if execution_id and target_id:
            try:
                return self._execution_environment(execution_id), self._target_environment(target_id)
            except StopIteration as error:
                raise ValueError("selected execution or target environment does not exist") from error
        return (
            {
                "id": "",
                "executor": self._executor_from_values(values),
                "browser_executable_path": values.get("browser_executable_path", ""),
                "browser_library_path": values.get("browser_library_path", ""),
            },
            {
                "id": "",
                "repository": values.get("repository", ""),
                "browser_base_url": values.get("browser_base_url", ""),
            },
        )

    def create_execution_environment(self, values: dict[str, Any]) -> dict[str, Any]:
        items = self.execution_environments()
        if any(item.get("id") == values["id"] for item in items):
            raise ValueError("execution environment ID already exists")
        item = {
            "id": values["id"],
            "name": values["name"],
            "executor": self._executor_from_values(values),
            "browser_executable_path": str(values.get("browser_executable_path", "")).strip(),
            "browser_library_path": str(values.get("browser_library_path", "")).strip(),
            "environment_variables": self._environment_variables_from_values(values),
            "created_at": now().isoformat(),
        }
        items.append(item)
        self._save_asset_list(EXECUTION_ENVIRONMENTS, items)
        return item

    def create_target_environment(self, values: dict[str, Any]) -> dict[str, Any]:
        items = self.target_environments()
        if any(item.get("id") == values["id"] for item in items):
            raise ValueError("target environment ID already exists")
        item = {
            "id": values["id"],
            "name": values["name"],
            "repository": str(values["repository"]).strip(),
            "browser_base_url": str(values.get("browser_base_url", "")).strip(),
            "managed_prompt_path": str(values.get("managed_prompt_path", "")).strip(),
            "created_at": now().isoformat(),
        }
        items.append(item)
        self._save_asset_list(TARGET_ENVIRONMENTS, items)
        return item

    def update_execution_environment(self, environment_id: str, values: dict[str, Any]) -> dict[str, Any]:
        items = self.execution_environments()
        index = next((i for i, item in enumerate(items) if item.get("id") == environment_id), None)
        if index is None:
            raise KeyError(environment_id)
        item = {
            "id": environment_id,
            "name": values["name"],
            "executor": self._executor_from_values(values),
            "browser_executable_path": str(values.get("browser_executable_path", "")).strip(),
            "browser_library_path": str(values.get("browser_library_path", "")).strip(),
            "environment_variables": self._environment_variables_from_values(values),
            "created_at": items[index].get("created_at", now().isoformat()),
        }
        items[index] = item
        self._save_asset_list(EXECUTION_ENVIRONMENTS, items)
        return item

    def update_target_environment(self, environment_id: str, values: dict[str, Any]) -> dict[str, Any]:
        items = self.target_environments()
        index = next((i for i, item in enumerate(items) if item.get("id") == environment_id), None)
        if index is None:
            raise KeyError(environment_id)
        item = {
            "id": environment_id,
            "name": values["name"],
            "repository": str(values["repository"]).strip(),
            "browser_base_url": str(values.get("browser_base_url", "")).strip(),
            "managed_prompt_path": str(values.get("managed_prompt_path", "")).strip(),
            "created_at": items[index].get("created_at", now().isoformat()),
        }
        items[index] = item
        self._save_asset_list(TARGET_ENVIRONMENTS, items)
        return item

    def _delete_environment(self, environment_id: str, path: Path, reference_key: str, label: str) -> None:
        if any(build.get(reference_key) == environment_id for build in self.evaluation_builds()):
            raise ValueError(f"{label} is used by an evaluation build")
        items = self._asset_list(path)
        remaining = [item for item in items if item.get("id") != environment_id]
        if len(remaining) == len(items):
            raise KeyError(environment_id)
        self._save_asset_list(path, remaining)

    def delete_execution_environment(self, environment_id: str) -> None:
        self._delete_environment(
            environment_id, EXECUTION_ENVIRONMENTS, "execution_environment_id", "execution environment"
        )

    def delete_target_environment(self, environment_id: str) -> None:
        self._delete_environment(
            environment_id, TARGET_ENVIRONMENTS, "target_environment_id", "target environment"
        )

    def _migrate_evaluation_environments(self) -> None:
        path = CONFIG / "evaluation-builds.yaml"
        builds = self._asset_list(path)
        if not builds:
            return
        executions, targets, changed = self.execution_environments(), self.target_environments(), False
        for build in builds:
            build_id = str(build.get("id", "legacy"))
            execution_id, target_id = f"{build_id}-execution", f"{build_id}-target"
            if not build.get("execution_environment_id"):
                if not any(item.get("id") == execution_id for item in executions):
                    executions.append(
                        {
                            "id": execution_id,
                            "name": f"{build.get('name', build_id)} execution",
                            "executor": build.get("executor", {"type": "local"}),
                            "browser_executable_path": build.get("browser_executable_path", ""),
                            "browser_library_path": build.get("browser_library_path", ""),
                        }
                    )
                build["execution_environment_id"], changed = execution_id, True
            if not build.get("target_environment_id"):
                if not any(item.get("id") == target_id for item in targets):
                    targets.append(
                        {
                            "id": target_id,
                            "name": f"{build.get('name', build_id)} target",
                            "repository": build.get("repository", ""),
                            "browser_base_url": build.get("browser_base_url", ""),
                            "managed_prompt_path": build.get("prompt_bundle", ""),
                        }
                    )
                build["target_environment_id"], changed = target_id, True
        if changed:
            self._save_asset_list(EXECUTION_ENVIRONMENTS, executions)
            self._save_asset_list(TARGET_ENVIRONMENTS, targets)
            self._save_asset_list(path, builds)

    def prompt_templates(self) -> list[dict[str, Any]]:
        path = CONFIG / "prompt-templates.yaml"
        templates = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []
        for template in templates:
            versions = template.get("versions")
            if not versions:
                versions = [
                    {"version": int(template.get("version", 1)), "content": template.get("content", "")}
                ]
                template["versions"] = versions
            latest = max(versions, key=lambda item: int(item.get("version", 0)))
            template["version"] = int(latest["version"])
            template["content"] = str(latest["content"])
        return templates

    def target_test_case_sets(self) -> list[dict[str, Any]]:
        return (
            yaml.safe_load(TARGET_TEST_CASE_SETS.read_text(encoding="utf-8"))
            if TARGET_TEST_CASE_SETS.exists()
            else []
        )

    @staticmethod
    def _validated_target_test_case_set(values: dict[str, Any], set_id: str) -> dict[str, Any]:
        name, description = str(values.get("name", "")).strip(), str(values.get("description", "")).strip()
        cases = values.get("cases")
        if not name or not description or not isinstance(cases, list) or not cases:
            raise ValueError("target-AI test case set requires a name, description, and at least one case")
        normalized = []
        for item in cases:
            if not isinstance(item, dict):
                raise ValueError("each target-AI test case must be an object")
            case_id, case_name = str(item.get("id", "")).strip(), str(item.get("name", "")).strip()
            prompt, acceptance = str(item.get("prompt", "")).strip(), str(item.get("acceptance", "")).strip()
            if not case_id or not case_name or not prompt or not acceptance:
                raise ValueError(
                    "each target-AI test case requires an ID, name, prompt, and acceptance evidence"
                )
            path = str(item.get("path", "/")).strip() or "/"
            if not path.startswith("/"):
                raise ValueError("browser test case path must start with '/'")
            normalized.append(
                {
                    "id": case_id,
                    "name": case_name,
                    "prompt": prompt,
                    "acceptance": acceptance,
                    "path": path,
                    "expected_text": str(item.get("expected_text", "")).strip(),
                }
            )
        if len({item["id"] for item in normalized}) != len(normalized):
            raise ValueError("target-AI test case IDs must be unique within a set")
        return {"id": set_id, "name": name, "description": description, "cases": normalized}

    def create_target_test_case_set(self, values: dict[str, Any]) -> dict[str, Any]:
        set_id = str(values.get("id", "")).strip()
        if not set_id or any(item.get("id") == set_id for item in self.target_test_case_sets()):
            raise ValueError("target-AI test case set ID is required and must be unique")
        sets = self.target_test_case_sets()
        test_set = self._validated_target_test_case_set(values, set_id)
        test_set["created_at"] = now().isoformat()
        sets.append(test_set)
        temporary = TARGET_TEST_CASE_SETS.with_suffix(".tmp")
        temporary.write_text(yaml.safe_dump(sets, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(TARGET_TEST_CASE_SETS)
        return test_set

    def update_target_test_case_set(self, set_id: str, values: dict[str, Any]) -> dict[str, Any]:
        sets = self.target_test_case_sets()
        index = next((i for i, item in enumerate(sets) if item.get("id") == set_id), None)
        if index is None:
            raise KeyError(set_id)
        test_set = self._validated_target_test_case_set(values, set_id)
        test_set["created_at"] = sets[index].get("created_at", now().isoformat())
        sets[index] = test_set
        temporary = TARGET_TEST_CASE_SETS.with_suffix(".tmp")
        temporary.write_text(yaml.safe_dump(sets, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(TARGET_TEST_CASE_SETS)
        return test_set

    def delete_target_test_case_set(self, set_id: str) -> None:
        sets = self.target_test_case_sets()
        if not any(item.get("id") == set_id for item in sets):
            raise KeyError(set_id)
        if any(build.get("test_case_set_id") == set_id for build in self.evaluation_builds()):
            raise ValueError("test case set is used by an evaluation build")
        temporary = TARGET_TEST_CASE_SETS.with_suffix(".tmp")
        temporary.write_text(
            yaml.safe_dump(
                [item for item in sets if item.get("id") != set_id], allow_unicode=True, sort_keys=False
            ),
            encoding="utf-8",
        )
        temporary.replace(TARGET_TEST_CASE_SETS)

    def update_prompt_template(self, template_id: str, values: dict[str, Any]) -> dict[str, Any]:
        templates = self.prompt_templates()
        index = next((i for i, item in enumerate(templates) if item.get("id") == template_id), None)
        if index is None:
            raise KeyError(template_id)
        name, content = str(values.get("name", "")).strip(), str(values.get("content", "")).strip()
        if not name or not content:
            raise ValueError("prompt template requires a name and content")
        current = templates[index]
        versions = list(
            current.get("versions")
            or [{"version": int(current.get("version", 1)), "content": current.get("content", "")}]
        )
        version = max(int(item.get("version", 0)) for item in versions) + 1
        versions.append({"version": version, "content": content})
        template = {
            "id": template_id,
            "name": name,
            "version": version,
            "content": content,
            "versions": versions,
            "created_at": current.get("created_at", now().isoformat()),
        }
        templates[index] = template
        temporary = CONFIG / "prompt-templates.tmp"
        temporary.write_text(yaml.safe_dump(templates, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(CONFIG / "prompt-templates.yaml")
        # Preserve the established update response shape; the persisted value
        # is exposed by the subsequent catalog refresh.
        return {key: value for key, value in template.items() if key != "created_at"}

    def create_prompt_template(self, values: dict[str, Any]) -> dict[str, Any]:
        template_id = str(values["id"])
        templates = self.prompt_templates()
        if any(item.get("id") == template_id for item in templates):
            raise ValueError("prompt template ID already exists")
        return self._write_prompt_template(templates, template_id, values)

    def delete_prompt_template(self, template_id: str) -> None:
        templates = self.prompt_templates()
        if not any(item.get("id") == template_id for item in templates):
            raise KeyError(template_id)
        if any(build.get("manager_template_id") == template_id for build in self.evaluation_builds()):
            raise ValueError("prompt template is used by an evaluation build")
        temporary = CONFIG / "prompt-templates.tmp"
        temporary.write_text(
            yaml.safe_dump(
                [item for item in templates if item.get("id") != template_id],
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(CONFIG / "prompt-templates.yaml")

    def _write_prompt_template(
        self, templates: list[dict[str, Any]], template_id: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        name, content = str(values.get("name", "")).strip(), str(values.get("content", "")).strip()
        if not name or not content:
            raise ValueError("prompt template requires a name and content")
        version = 1
        template = {
            "id": template_id,
            "name": name,
            "version": version,
            "content": content,
            "versions": [{"version": version, "content": content}],
            "created_at": now().isoformat(),
        }
        templates.append(template)
        temporary = CONFIG / "prompt-templates.tmp"
        temporary.write_text(yaml.safe_dump(templates, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(CONFIG / "prompt-templates.yaml")
        return template

    def _assembled_prompt(self, build: dict[str, Any]) -> tuple[str, str]:
        """Resolve the global manager contract and the build's evaluation policy."""
        template_id = build.get("manager_template_id", "manager-default-v1")
        template = next((item for item in self.prompt_templates() if item.get("id") == template_id), None)
        if template is None:
            raise ValueError(f"manager prompt template does not exist: {template_id}")
        operational = self.application_settings()["manager_prompt_template"]
        if MANAGER_PROMPT_SLOT not in operational:
            raise ValueError(f"operational manager prompt must include {MANAGER_PROMPT_SLOT}")
        if MANAGER_OUTPUT_LANGUAGE_SLOT not in operational:
            raise ValueError(f"operational manager prompt must include {MANAGER_OUTPUT_LANGUAGE_SLOT}")
        selected_set = next(
            (
                item
                for item in self.target_test_case_sets()
                if item.get("id") == build.get("test_case_set_id")
            ),
            None,
        )
        cases = selected_set.get("cases", []) if selected_set else build.get("test_cases") or []
        case_text = (
            "\n\n".join(
                "## Fixed target-AI test case: {name}\n{prompt}\n\nAcceptance evidence:\n{acceptance}".format(
                    name=item.get("name") or item.get("id") or "unnamed",
                    prompt=item.get("prompt", ""),
                    acceptance=item.get("acceptance", ""),
                )
                for item in cases
            )
            or "## Fixed target-AI test cases\nNo fixed test cases were configured."
        )
        manager_policy = (
            f"# Manager evaluation policy: {template['name']} (v{template.get('version', 1)})\n"
            f"{template['content']}"
        )
        legacy_context = "\n".join(
            part
            for part in (
                f"Purpose: {build.get('purpose', '')}" if build.get("purpose") else "",
                f"Legacy evaluation criteria: {build.get('criteria', '')}" if build.get("criteria") else "",
                f"Legacy task instruction: {build.get('task_instruction', '')}"
                if build.get("task_instruction")
                else "",
            )
            if part
        )
        assembled = "\n\n".join(
            part
            for part in (
                operational.replace(MANAGER_PROMPT_SLOT, manager_policy).replace(
                    MANAGER_OUTPUT_LANGUAGE_SLOT,
                    "# Output language\n"
                    "Write all human-readable string values in the configured application language "
                    f"({self.application_settings()['manager_output_locale']}). "
                    "Keep JSON keys, field names, and required enum values exactly as specified.",
                ),
                f"# Evaluation context\nRepository: {build.get('repository', '')}\n{legacy_context}",
                case_text,
                PROPOSAL_DECISION_POLICY,
            )
            if part
        )
        return f"application-settings + manager-template:{template_id}", assembled[:100_000]

    def evaluation_build(self, build_id: str) -> dict[str, Any]:
        for build in self.evaluation_builds():
            if build["id"] == build_id:
                return build
        raise KeyError(build_id)

    def workspaces(self, path: str | None = None) -> dict[str, Any]:
        if path is None:
            root = Path(Path.cwd().anchor)
            return {"path": "", "directories": [{"name": str(root), "path": str(root)}]}
        directory = Path(path).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError("workspace path must be an existing directory")
        children = sorted(
            (entry for entry in directory.iterdir() if entry.is_dir()),
            key=lambda entry: entry.name.lower(),
        )
        return {
            "path": str(directory),
            "directories": [{"name": entry.name, "path": str(entry)} for entry in children[:200]],
        }

    def create_evaluation_build(self, values: dict[str, Any]) -> dict[str, Any]:
        build_id = values["id"]
        if any(build["id"] == build_id for build in self.evaluation_builds()):
            raise ValueError("같은 ID의 평가 빌드가 이미 있습니다.")
        runner = self._runner(values["runner_id"])
        execution_environment, target_environment = self._build_environment_values(values)
        executor = execution_environment["executor"]
        repository_value = str(target_environment["repository"])
        repository = Path(repository_value).expanduser().resolve()
        if executor["type"] != "remote-http" and not repository.is_dir():
            raise ValueError("repository must be an existing directory")
        if (
            executor["type"] == "remote-http"
            and not repository_value.startswith("remote://")
            and not repository.is_dir()
        ):
            raise ValueError(
                "remote HTTP builds require an existing repository or a remote:// repository label"
            )
        if "manager_template_id" in values and not any(
            item.get("id") == values.get("manager_template_id") for item in self.prompt_templates()
        ):
            raise ValueError("manager prompt template does not exist")
        if "model_profile_name" in values and not any(
            item["profile_name"] == values.get("model_profile_name") for item in self.profiles()
        ):
            raise ValueError("AI model profile does not exist")
        if not any(item.get("id") == values.get("test_case_set_id") for item in self.target_test_case_sets()):
            raise ValueError("target-AI test case set does not exist")
        build = {
            "id": build_id,
            "name": values["name"],
            "enabled": values["enabled"],
            "runner_id": runner["id"],
            "execution_environment_id": execution_environment.get("id", ""),
            "target_environment_id": target_environment.get("id", ""),
            "repository": repository_value
            if executor["type"] == "remote-http" and repository_value.startswith("remote://")
            else str(repository),
            "purpose": values["purpose"],
            "criteria": values.get("criteria", ""),
            "prompt_bundle": values.get("prompt_bundle", ""),
            "managed_prompt_path": str(target_environment.get("managed_prompt_path", "")).strip(),
            "manager_template_id": values.get("manager_template_id", "manager-default-v1"),
            "model_profile_name": values.get("model_profile_name", "Default"),
            "task_instruction": values.get("task_instruction", ""),
            "test_case_set_id": values["test_case_set_id"],
            "browser_base_url": str(target_environment.get("browser_base_url", "")).strip(),
            "browser_executable_path": str(execution_environment.get("browser_executable_path", "")).strip(),
            "browser_library_path": str(execution_environment.get("browser_library_path", "")).strip(),
            "timezone": values["timezone"],
            "repeat_interval_minutes": values["repeat_interval_minutes"],
            "cadence_mode": values.get("cadence_mode", "after_completion"),
            "overrun_policy": values.get("overrun_policy", "wait"),
            "run_limit": values["run_limit"],
            "schedule_enabled": bool(values.get("schedule_enabled", False)),
            "schedule_weekdays": [
                int(day) for day in values.get("schedule_weekdays", []) if 0 <= int(day) <= 6
            ],
            "schedule_start_time": values.get("schedule_start_time", "09:00"),
            "schedule_end_time": values.get("schedule_end_time", "18:00"),
            "iteration_strategy": values.get("iteration_strategy", "linear"),
            "candidates_per_iteration": values.get("candidates_per_iteration", 2),
            "approval_score": values["approval_score"],
            "require_human_approval_before_apply": bool(
                values.get("require_human_approval_before_apply", False)
            ),
            "executor": executor,
        }
        builds = self.evaluation_builds()
        builds.append(build)
        temporary = CONFIG / "evaluation-builds.tmp"
        temporary.write_text(yaml.safe_dump(builds, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(CONFIG / "evaluation-builds.yaml")
        return build

    def update_evaluation_build(self, build_id: str, values: dict[str, Any]) -> dict[str, Any]:
        builds = self.evaluation_builds()
        index = next((i for i, build in enumerate(builds) if build["id"] == build_id), None)
        if index is None:
            raise KeyError(build_id)
        if values["id"] != build_id:
            raise ValueError("evaluation build ID cannot be changed")
        runner = self._runner(values["runner_id"])
        execution_environment, target_environment = self._build_environment_values(values)
        executor = execution_environment["executor"]
        repository_value = str(target_environment["repository"])
        repository = Path(repository_value).expanduser().resolve()
        if executor["type"] != "remote-http" and not repository.is_dir():
            raise ValueError("repository must be an existing directory")
        if (
            executor["type"] == "remote-http"
            and not repository_value.startswith("remote://")
            and not repository.is_dir()
        ):
            raise ValueError(
                "remote HTTP builds require an existing repository or a remote:// repository label"
            )
        if "manager_template_id" in values and not any(
            item.get("id") == values.get("manager_template_id") for item in self.prompt_templates()
        ):
            raise ValueError("manager prompt template does not exist")
        if "model_profile_name" in values and not any(
            item["profile_name"] == values.get("model_profile_name") for item in self.profiles()
        ):
            raise ValueError("AI model profile does not exist")
        if not any(item.get("id") == values.get("test_case_set_id") for item in self.target_test_case_sets()):
            raise ValueError("target-AI test case set does not exist")
        existing = builds[index]
        build = {
            "id": build_id,
            "name": values["name"],
            "enabled": values["enabled"],
            "runner_id": runner["id"],
            "execution_environment_id": execution_environment.get("id", ""),
            "target_environment_id": target_environment.get("id", ""),
            "repository": repository_value
            if executor["type"] == "remote-http" and repository_value.startswith("remote://")
            else str(repository),
            "purpose": values["purpose"],
            "criteria": existing.get("criteria", ""),
            "prompt_bundle": existing.get("prompt_bundle", ""),
            "managed_prompt_path": str(target_environment.get("managed_prompt_path", "")).strip(),
            "manager_template_id": values.get("manager_template_id", "manager-default-v1"),
            "model_profile_name": values.get("model_profile_name", "Default"),
            "task_instruction": existing.get("task_instruction", ""),
            "test_case_set_id": values["test_case_set_id"],
            "browser_base_url": str(target_environment.get("browser_base_url", "")).strip(),
            "browser_executable_path": str(execution_environment.get("browser_executable_path", "")).strip(),
            "browser_library_path": str(execution_environment.get("browser_library_path", "")).strip(),
            "timezone": values["timezone"],
            "repeat_interval_minutes": values["repeat_interval_minutes"],
            "cadence_mode": values.get("cadence_mode", "after_completion"),
            "overrun_policy": values.get("overrun_policy", "wait"),
            "run_limit": values["run_limit"],
            "schedule_enabled": bool(values.get("schedule_enabled", False)),
            "schedule_weekdays": [
                int(day) for day in values.get("schedule_weekdays", []) if 0 <= int(day) <= 6
            ],
            "schedule_start_time": values.get("schedule_start_time", "09:00"),
            "schedule_end_time": values.get("schedule_end_time", "18:00"),
            "iteration_strategy": values.get("iteration_strategy", "linear"),
            "candidates_per_iteration": values.get("candidates_per_iteration", 2),
            "approval_score": values["approval_score"],
            "require_human_approval_before_apply": bool(
                values.get("require_human_approval_before_apply", False)
            ),
            "executor": executor,
        }
        builds[index] = build
        temporary = CONFIG / "evaluation-builds.tmp"
        temporary.write_text(yaml.safe_dump(builds, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(CONFIG / "evaluation-builds.yaml")
        return build

    def delete_evaluation_build(self, build_id: str) -> None:
        builds = self.evaluation_builds()
        remaining = [build for build in builds if build["id"] != build_id]
        if len(remaining) == len(builds):
            raise KeyError(build_id)
        temporary = CONFIG / "evaluation-builds.tmp"
        temporary.write_text(yaml.safe_dump(remaining, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(CONFIG / "evaluation-builds.yaml")

    def improvements(self) -> list[dict[str, Any]]:
        path = CONFIG / "improvements.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []

    def cycle_interventions(self) -> list[dict[str, Any]]:
        return (
            yaml.safe_load(CYCLE_INTERVENTIONS.read_text(encoding="utf-8"))
            if CYCLE_INTERVENTIONS.exists()
            else []
        )

    def proposal_lifecycles(
        self, evaluation_build_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Present supervisor proposals directly from evaluation-run results.

        Proposal history is an analysis view of what supervisors proposed and
        decided in each run. It deliberately does not depend on a separate
        runner-owned decision ledger, which could omit ordinary evaluations.
        """
        values: list[dict[str, Any]] = []
        for run in self.runs():
            if evaluation_build_id and run.evaluation_build_id != evaluation_build_id:
                continue
            records = run.supervisor_results or []
            if not records and run.supervisor_response:
                records = [
                    {
                        "iteration": 1,
                        "recorded_at": run.updated_at.isoformat(),
                        "response": run.supervisor_response,
                    }
                ]
            for record in records:
                if not isinstance(record, dict):
                    continue
                iteration = record.get("iteration")
                data_files: list[dict[str, Any]] = []
                for step in run.step_results:
                    if not isinstance(step, dict) or step.get("loop_index") != iteration:
                        continue
                    for data_file in step.get("data_files", []):
                        if not isinstance(data_file, dict):
                            continue
                        path, filename = data_file.get("path"), data_file.get("filename")
                        if not isinstance(path, str) or not isinstance(filename, str):
                            continue
                        data_files.append(
                            {
                                "label": str(data_file.get("label") or "")[:256],
                                "filename": filename,
                                "path": path,
                                "relative_path": str(data_file.get("relative_path") or ""),
                            }
                        )
                response = record.get("response")
                if not isinstance(response, dict):
                    continue
                improvements = response.get("improvements", [])
                evaluation = response.get("evaluation")
                score = evaluation.get("score") if isinstance(evaluation, dict) else None
                if isinstance(score, bool) or not isinstance(score, (int, float)):
                    score = None
                if not isinstance(improvements, list):
                    continue
                for index, proposal in enumerate(improvements):
                    if not isinstance(proposal, dict):
                        continue
                    source_status = str(proposal.get("status") or "proposed").lower()
                    decision = (
                        "accepted"
                        if source_status in {"adopted", "accepted"}
                        else "rejected"
                        if source_status == "rejected"
                        else "pending"
                    )
                    values.append(
                        {
                            "proposal_id": f"{run.id}:{record.get('iteration', 0)}:{index}",
                            "title": str(proposal.get("title") or "Untitled proposal"),
                            "target": str(proposal.get("target") or "prompt"),
                            "proposal": proposal,
                            "decision": decision,
                            "score": score,
                            "decision_rationale": str(
                                proposal.get("rationale") or proposal.get("acceptanceEvidence") or ""
                            ),
                            "status": "proposed" if decision == "pending" else decision,
                            "evaluation_build_id": run.evaluation_build_id,
                            "evaluation_build_name": run.evaluation_build_name,
                            "run_id": run.id,
                            "iteration": iteration,
                            "recorded_at": record.get("recorded_at") or run.updated_at.isoformat(),
                            "data_files": data_files,
                            "prompt_version": None,
                            "events": [
                                {
                                    "id": f"{run.id}:{record.get('iteration', 0)}:{index}",
                                    "event_type": "decision",
                                    "proposal_id": f"{run.id}:{record.get('iteration', 0)}:{index}",
                                    "decision": decision,
                                    "rationale": str(proposal.get("rationale") or ""),
                                    "recorded_at": record.get("recorded_at") or run.updated_at.isoformat(),
                                    "iteration": record.get("iteration"),
                                    "phase": "supervisor",
                                    "run_id": run.id,
                                }
                            ],
                        }
                    )
        if status:
            values = [item for item in values if item["status"] == status or item["decision"] == status]
        return sorted(values, key=lambda item: str(item.get("recorded_at", "")), reverse=True)

    def improvement_iteration_data(self, evaluation_build_id: str | None = None) -> list[dict[str, Any]]:
        """List SDK-saved data files by persisted evaluation run and iteration.

        These entries intentionally exist even when a supervisor did not make a
        proposal. The proposal-decision history uses them to expose the full
        iteration record rather than hiding developer-retained evidence behind
        a proposal requirement.
        """
        values: list[dict[str, Any]] = []
        for run in self.runs():
            if evaluation_build_id and run.evaluation_build_id != evaluation_build_id:
                continue
            grouped: dict[int, list[dict[str, Any]]] = {}
            timestamps: dict[int, str] = {}
            for step in run.step_results:
                if not isinstance(step, dict) or not isinstance(step.get("loop_index"), int):
                    continue
                iteration = step["loop_index"]
                for data_file in step.get("data_files", []):
                    if not isinstance(data_file, dict):
                        continue
                    path, filename = data_file.get("path"), data_file.get("filename")
                    if not isinstance(path, str) or not isinstance(filename, str):
                        continue
                    grouped.setdefault(iteration, []).append(
                        {
                            "label": str(data_file.get("label") or "")[:256],
                            "filename": filename,
                            "path": path,
                            "relative_path": str(data_file.get("relative_path") or ""),
                        }
                    )
                    timestamps.setdefault(iteration, str(step.get("ended_at") or run.updated_at.isoformat()))
            for iteration, data_files in grouped.items():
                values.append(
                    {
                        "evaluation_build_id": run.evaluation_build_id,
                        "evaluation_build_name": run.evaluation_build_name,
                        "run_id": run.id,
                        "iteration": iteration,
                        "recorded_at": timestamps[iteration],
                        "data_files": data_files,
                    }
                )
        return sorted(values, key=lambda item: str(item["recorded_at"]), reverse=True)

    def _save_cycle_interventions(self, values: list[dict[str, Any]]) -> None:
        temporary = CYCLE_INTERVENTIONS.with_suffix(".tmp")
        temporary.write_text(yaml.safe_dump(values, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(CYCLE_INTERVENTIONS)

    def reported_issues(self) -> list[dict[str, Any]]:
        path = CONFIG / "reported-issues.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []

    def telemetry(self) -> list[dict[str, Any]]:
        if not TELEMETRY.exists():
            return []
        lines = TELEMETRY.read_text(encoding="utf-8").splitlines()[-100:]
        return [json.loads(line) for line in reversed(lines)]

    @staticmethod
    def _prompt_snapshot_content(directory: Path, state: object) -> str | None:
        if not isinstance(state, dict) or not state.get("exists"):
            return ""
        snapshot = state.get("snapshot")
        if not isinstance(snapshot, str):
            return None
        candidate = (directory / snapshot).resolve()
        if directory.resolve() not in candidate.parents:
            return None
        try:
            payload = candidate.read_bytes()
        except OSError:
            return None
        if len(payload) > 100_000:
            return None
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def prompt_revisions(self, run_id: str) -> list[dict[str, Any]]:
        """Return immutable managed-prompt changes and blocked writes for one Run."""
        run = self._load(run_id)
        repository = Path(run.repository or "").expanduser()
        if not repository.is_dir():
            return []
        revisions: list[dict[str, Any]] = []
        for step in run.step_results:
            result = step.get("result")
            if not isinstance(result, dict):
                continue
            update = result.get("file_update") or result.get("file_rollback")
            blocked = result.get("file_update_blocked")
            cycle = result.get("improvement_cycle")
            prompt_update = cycle.get("prompt_update") if isinstance(cycle, dict) else None
            if (
                not isinstance(update, dict)
                and not isinstance(blocked, dict)
                and not isinstance(prompt_update, dict)
            ):
                continue
            event = (
                update
                if isinstance(update, dict)
                else blocked
                if isinstance(blocked, dict)
                else prompt_update
            )
            path = str(event.get("path") or "")
            version = event.get("version") if isinstance(event.get("version"), dict) else None
            if not path and isinstance(prompt_update, dict):
                path = str(prompt_update.get("path") or "")
                version = (
                    prompt_update.get("version")
                    if isinstance(prompt_update.get("version"), dict)
                    else version
                )
            if not path:
                continue
            project_key = hashlib.sha256(str(repository.resolve()).encode("utf-8")).hexdigest()
            path_key = hashlib.sha256(path.encode("utf-8")).hexdigest()
            directory = APP_DATA / "file-history" / project_key / path_key
            previous = version.get("previous") if version else None
            written = version.get("written") if version else None
            operation = str(version.get("operation") if version else "")
            reason = str(event.get("reason") or (prompt_update or {}).get("reason") or "")
            if not version and reason != "awaiting_human_approval":
                continue
            revisions.append(
                {
                    "iteration": step.get("loop_index"),
                    "phase": step.get("phase"),
                    "path": path,
                    "status": "blocked"
                    if reason == "awaiting_human_approval"
                    else "rolled_back"
                    if operation == "rollback"
                    else "applied"
                    if version
                    else "unchanged",
                    "reason": reason or None,
                    "recorded_at": (version or {}).get("recorded_at") or step.get("ended_at"),
                    "version_id": (version or {}).get("id"),
                    "run_id": (version or {}).get("run_id") or run.id,
                    "before": self._prompt_snapshot_content(directory, previous),
                    "after": self._prompt_snapshot_content(directory, written),
                    "before_sha256": (previous or {}).get("sha256"),
                    "after_sha256": (written or {}).get("sha256"),
                }
            )
        # A Run record is convenient for current executions, but prompt files
        # have a longer life than a single Run. Merge the durable file history
        # so older updates remain visible even when their old runner did not
        # emit a structured result in the current schema.
        expected_path = ""
        if run.evaluation_build_id:
            try:
                expected_path = str(
                    self.evaluation_build(run.evaluation_build_id).get("managed_prompt_path", "")
                )
            except KeyError:
                pass
        history_root = APP_DATA / "file-history"
        for manifest_path in history_root.glob("*/*/manifest.json"):
            try:
                document = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if document.get("project_root") != str(repository.resolve()):
                continue
            path = str(document.get("relative_path") or "")
            if not path or (expected_path and path != expected_path):
                continue
            history = document.get("history")
            if not isinstance(history, list):
                continue
            directory = manifest_path.parent
            current_path = repository / path
            current = current_path.read_bytes() if current_path.is_file() else None
            for index, version in enumerate(history):
                if not isinstance(version, dict):
                    continue
                previous = version.get("previous")
                written = version.get("written")
                after = self._prompt_snapshot_content(directory, written)
                if after is None and isinstance(written, dict):
                    next_previous = (
                        history[index + 1].get("previous")
                        if index + 1 < len(history) and isinstance(history[index + 1], dict)
                        else None
                    )
                    if isinstance(next_previous, dict) and next_previous.get("sha256") == written.get(
                        "sha256"
                    ):
                        after = self._prompt_snapshot_content(directory, next_previous)
                    elif current is not None and hashlib.sha256(current).hexdigest() == written.get("sha256"):
                        try:
                            after = current.decode("utf-8")
                        except UnicodeDecodeError:
                            pass
                existing = next(
                    (item for item in revisions if item.get("version_id") == version.get("id")), None
                )
                if existing is not None:
                    if existing.get("before") is None:
                        existing["before"] = self._prompt_snapshot_content(directory, previous)
                    if existing.get("after") is None:
                        existing["after"] = after
                    existing["run_id"] = existing.get("run_id") or version.get("run_id")
                    continue
                operation = str(version.get("operation") or "")
                revisions.append(
                    {
                        "iteration": version.get("iteration"),
                        "phase": version.get("phase"),
                        "path": path,
                        "status": "rolled_back" if operation == "rollback" else "applied",
                        "recorded_at": version.get("recorded_at"),
                        "version_id": version.get("id"),
                        "run_id": version.get("run_id"),
                        "before": self._prompt_snapshot_content(directory, previous),
                        "after": after,
                        "before_sha256": previous.get("sha256") if isinstance(previous, dict) else None,
                        "after_sha256": written.get("sha256") if isinstance(written, dict) else None,
                    }
                )
        ordered = sorted(revisions, key=lambda item: str(item.get("recorded_at") or ""))
        initial_revisions: list[dict[str, Any]] = []
        current_by_path: dict[str, str] = {}
        for revision in ordered:
            path = str(revision.get("path") or "")
            before = revision.get("before")
            after = revision.get("after")
            if path and path not in current_by_path:
                initial = before if isinstance(before, str) else after if isinstance(after, str) else None
                if initial is not None:
                    initial_revisions.append(
                        {
                            "iteration": None,
                            "phase": "initial",
                            "path": path,
                            "status": "initial",
                            "reason": None,
                            "recorded_at": None,
                            "version_id": None,
                            "run_id": None,
                            "before": initial,
                            "after": initial,
                            "before_sha256": hashlib.sha256(initial.encode("utf-8")).hexdigest(),
                            "after_sha256": hashlib.sha256(initial.encode("utf-8")).hexdigest(),
                        }
                    )
                    current_by_path[path] = initial
            if revision.get("status") == "blocked" and path in current_by_path:
                revision["before"] = current_by_path[path]
                revision["after"] = current_by_path[path]
                digest = hashlib.sha256(current_by_path[path].encode("utf-8")).hexdigest()
                revision["before_sha256"] = digest
                revision["after_sha256"] = digest
            elif isinstance(after, str) and path:
                current_by_path[path] = after
        return [*initial_revisions, *ordered]

    def commit_changes(self, run_id: str) -> list[dict[str, Any]]:
        """Return commit ranges automatically retained by SDK runner phases."""
        run = self._load(run_id)
        changes: list[dict[str, Any]] = []
        for step in run.step_results:
            result = step.get("result")
            event = result.get("commit_change") if isinstance(result, dict) else None
            if not isinstance(event, dict) and isinstance(result, dict):
                jgent = result.get("jgent_paired")
                candidate = jgent.get("committed_source_candidate") if isinstance(jgent, dict) else None
                event = candidate if isinstance(candidate, dict) else None
            if not isinstance(event, dict):
                continue
            before, after = str(event.get("before") or ""), str(event.get("after") or "")
            if not before or not after or before == after:
                continue
            artifact = event.get("diff_artifact") if isinstance(event.get("diff_artifact"), dict) else None
            diff: str | None = None
            if artifact:
                raw_path = artifact.get("path")
                candidate = Path(str(raw_path)).resolve() if isinstance(raw_path, str) else None
                artifacts_root = (APP_DATA / "artifacts").resolve()
                if candidate and artifacts_root in candidate.parents:
                    try:
                        if candidate.stat().st_size <= 500_000:
                            diff = candidate.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        pass
            changes.append(
                {
                    "iteration": step.get("loop_index"),
                    "phase": step.get("phase"),
                    "recorded_at": step.get("ended_at"),
                    "before": before,
                    "after": after,
                    "changed_paths": event.get("changed_paths")
                    if isinstance(event.get("changed_paths"), list)
                    else [],
                    "commits": event.get("commits") if isinstance(event.get("commits"), list) else [],
                    "diff_artifact": artifact,
                    "diff": diff,
                }
            )
        return sorted(changes, key=lambda item: str(item.get("recorded_at") or ""), reverse=True)

    def run_artifact(self, run_id: str, loop_index: int, relative_path: str) -> Path:
        """Resolve one retained run artifact without permitting path traversal."""
        if loop_index < 0:
            raise KeyError(relative_path)
        relative = Path(relative_path)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise KeyError(relative_path)
        directory = (APP_DATA / "artifacts" / run_id / f"loop-{loop_index}").resolve()
        candidate = (directory / relative).resolve()
        if directory not in candidate.parents or not candidate.is_file():
            raise KeyError(relative_path)
        return candidate

    def run_telemetry(self, run_id: str) -> dict[str, Any]:
        """Return the exported OpenTelemetry spans belonging to one execution."""
        run = self._load(run_id)
        trace_id = run.telemetry_trace_id
        if not trace_id or not TELEMETRY.exists():
            return {"trace_id": trace_id, "spans": []}
        spans: list[dict[str, Any]] = []
        for line in TELEMETRY.read_text(encoding="utf-8").splitlines():
            try:
                span = json.loads(line)["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                continue
            if span.get("traceId") == trace_id:
                spans.append(span)
        known_span_ids = {str(span.get("spanId", "")) for span in spans}
        missing_parents = {
            str(span["parentSpanId"])
            for span in spans
            if span.get("parentSpanId") and span["parentSpanId"] not in known_span_ids
        }
        # The workflow root span remains open while a persistent runner is active,
        # so the batch exporter has not emitted it yet. Preserve its OTEL parent
        # relationship in the live tree rather than showing its child spans flat.
        if len(missing_parents) == 1:
            spans.append(
                {
                    "name": "workflow.run",
                    "traceId": trace_id,
                    "spanId": missing_parents.pop(),
                    "parentSpanId": None,
                    "startTime": int(run.created_at.timestamp() * 1_000_000_000),
                    "endTime": 0,
                    "attributes": {"run.id": run_id, "orbit.live_root": True},
                    "status": "UNSET",
                    "events": [],
                }
            )
        spans.sort(key=lambda item: int(item.get("startTime", 0)))
        return {"trace_id": trace_id, "spans": spans}

    def orbit_logs(self) -> list[dict[str, str]]:
        entries = []
        for record in self.telemetry():
            try:
                span = record["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
                events = span.get("events", [])
                message = next(
                    (
                        str(event.get("attributes", {}).get("exception.message", ""))
                        for event in events
                        if event.get("attributes", {}).get("exception.message")
                    ),
                    "",
                )
                entries.append(
                    {
                        "time": str(record.get("exportedAt", "")),
                        "name": str(span.get("name", "orbit")),
                        "status": str(span.get("status", "UNSET")),
                        "message": message,
                    }
                )
            except (KeyError, IndexError, TypeError):
                continue
        return entries[:80]

    def dashboard(self) -> dict[str, Any]:
        runs = self.runs()
        builds = self.evaluation_builds()
        build_ids = {build["id"] for build in builds}
        recent_runs: list[Run] = []
        seen_builds: set[str] = set()
        for run in runs:
            if not run.evaluation_build_id or run.evaluation_build_id not in build_ids:
                continue
            if run.evaluation_build_id in seen_builds:
                continue
            seen_builds.add(run.evaluation_build_id)
            recent_runs.append(run)
            if len(recent_runs) == 8:
                break
        return {
            "active_builds": [build for build in builds if build["enabled"]],
            "active_runs": [
                run.model_dump(mode="json")
                for run in runs
                if run.execution_type == "pipeline"
                and run.execution_mode == "run"
                and run.evaluation_build_id in build_ids
                and run.status in {"queued", "running", "awaiting_approval"}
            ],
            "recent_runs": recent_runs,
            "improvements": self.improvements(),
            "metrics": {
                "evaluation_builds": len(builds),
                "completed_evaluations": len(
                    [
                        run
                        for run in runs
                        if run.evaluation_build_id in build_ids
                        and run.status in {"succeeded", "failed", "cancelled"}
                    ]
                ),
                "commits": len([item for item in self.improvements() if item["status"] == "committed"]),
            },
        }

    def improvement_analytics(self, hours: int = 24) -> dict[str, Any]:
        """Aggregate retained supervisor feedback into operator-facing trends."""
        hours = max(1, min(hours, 24 * 30))
        end = now()
        start = end - timedelta(hours=hours)
        feedback_by_build: dict[str, dict[str, Any]] = {}
        trends_by_build: dict[str, dict[str, Any]] = {}
        feedback_status_by_build: dict[str, dict[str, Any]] = {}
        bucket_count = min(24, max(6, hours))
        interval = timedelta(seconds=(end - start).total_seconds() / bucket_count)
        issue_severity = [
            {"time": (start + interval * index).isoformat(), "low": 0, "medium": 0, "high": 0, "critical": 0}
            for index in range(bucket_count + 1)
        ]
        summary_start = end - timedelta(hours=24)
        previous_summary_start = summary_start - timedelta(hours=24)
        summary = {
            "feedback": 0,
            "accepted": 0,
            "issues": 0,
            "scores": [],
            "previous_scores": [],
        }

        def parse_timestamp(value: object) -> datetime | None:
            if not isinstance(value, str):
                return None
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None

        pipeline_runs = [
            run for run in self.runs() if run.execution_type == "pipeline" and run.evaluation_build_id
        ]
        for run in pipeline_runs:
            build_id = str(run.evaluation_build_id)
            name = run.evaluation_build_name or build_id
            feedback = feedback_by_build.setdefault(
                build_id, {"build_id": build_id, "name": name, "feedback_count": 0}
            )
            trend = trends_by_build.setdefault(build_id, {"build_id": build_id, "name": name, "points": []})
            status_counts = feedback_status_by_build.setdefault(
                build_id, {"build_id": build_id, "name": name, "proposed": 0, "adopted": 0, "rejected": 0}
            )
            for record in run.supervisor_results:
                recorded_at = parse_timestamp(record.get("recorded_at"))
                if recorded_at is None or recorded_at > end:
                    continue
                response = record.get("response") if isinstance(record.get("response"), dict) else {}
                improvements = (
                    response.get("improvements", []) if isinstance(response.get("improvements"), list) else []
                )
                issues = (
                    response.get("reported_issues", [])
                    if isinstance(response.get("reported_issues"), list)
                    else []
                )
                evaluation = (
                    response.get("evaluation") if isinstance(response.get("evaluation"), dict) else {}
                )
                score = evaluation.get("score") if isinstance(evaluation.get("score"), (int, float)) else None
                if recorded_at >= summary_start:
                    summary["feedback"] += len(improvements) + len(issues)
                    summary["accepted"] += len(
                        [
                            item
                            for item in improvements
                            if isinstance(item, dict) and item.get("status") == "adopted"
                        ]
                    )
                    summary["issues"] += len(issues)
                    if score is not None:
                        summary["scores"].append(score)
                elif recorded_at >= previous_summary_start and score is not None:
                    summary["previous_scores"].append(score)
                if recorded_at < start:
                    continue
                feedback["feedback_count"] += len(improvements) + len(issues)
                for improvement in improvements:
                    if isinstance(improvement, dict) and improvement.get("status") in {
                        "proposed",
                        "adopted",
                        "rejected",
                    }:
                        status_counts[str(improvement["status"])] += 1
                for issue in issues:
                    if not isinstance(issue, dict) or issue.get("severity") not in {
                        "low",
                        "medium",
                        "high",
                        "critical",
                    }:
                        continue
                    issue_time = parse_timestamp(issue.get("reported_at")) or recorded_at
                    bucket = min(bucket_count, max(0, int((issue_time - start) / interval)))
                    issue_severity[bucket][str(issue["severity"])] += 1
                trend["points"].append(
                    {
                        "run_id": run.id,
                        "iteration": record.get("iteration", 0),
                        "recorded_at": recorded_at.isoformat(),
                        "accepted_count": len(
                            [
                                item
                                for item in improvements
                                if isinstance(item, dict) and item.get("status") == "adopted"
                            ]
                        ),
                        "feedback_count": len(improvements) + len(issues),
                        "score": score,
                    }
                )

        active_counts = []
        for index in range(bucket_count + 1):
            timestamp = start + interval * index
            bucket_end = min(end, timestamp + interval)
            count = 0
            for run in pipeline_runs:
                # Older records can predate finished_at. A terminal status is
                # authoritative in that case and must never inflate the live
                # active-evaluation graph.
                if run.status in {"succeeded", "failed", "cancelled"} and run.finished_at is None:
                    continue
                if index == bucket_count:
                    if run.created_at > timestamp or (
                        run.finished_at is not None and run.finished_at <= timestamp
                    ):
                        continue
                elif run.created_at >= bucket_end or (
                    run.finished_at is not None and run.finished_at <= timestamp
                ):
                    continue
                count += 1
            active_counts.append({"time": timestamp.isoformat(), "count": count})
        health_by_build: dict[str, dict[str, Any]] = {}
        for run in pipeline_runs:
            if run.created_at < start or run.created_at > end:
                continue
            build_id = str(run.evaluation_build_id)
            item = health_by_build.setdefault(
                build_id,
                {
                    "build_id": build_id,
                    "name": run.evaluation_build_name or build_id,
                    "succeeded": 0,
                    "failed": 0,
                    "cancelled": 0,
                    "running": 0,
                },
            )
            item[run.status if run.status in item else "running"] += 1
        for trend in trends_by_build.values():
            trend["points"].sort(key=lambda point: point["recorded_at"])
        average_score = (
            round(sum(summary["scores"]) / len(summary["scores"]), 1) if summary["scores"] else None
        )
        previous_average = (
            sum(summary["previous_scores"]) / len(summary["previous_scores"])
            if summary["previous_scores"]
            else None
        )
        return {
            "window_hours": hours,
            "operational_summary": {
                "feedback": summary["feedback"],
                "accepted": summary["accepted"],
                "issues": summary["issues"],
                "average_score": average_score,
                "score_delta": round(average_score - previous_average, 1)
                if average_score is not None and previous_average is not None
                else None,
            },
            "feedback_by_build": sorted(
                feedback_by_build.values(), key=lambda item: item["feedback_count"], reverse=True
            ),
            "iteration_trends": sorted(trends_by_build.values(), key=lambda item: item["name"]),
            "active_evaluations": active_counts,
            "feedback_status": sorted(feedback_status_by_build.values(), key=lambda item: item["name"]),
            "issue_severity": issue_severity,
            "run_health": sorted(health_by_build.values(), key=lambda item: item["name"]),
        }

    def active_evaluations(self, runs: list[Run] | None = None) -> list[dict[str, Any]]:
        """Return only operator-managed, long-running pipeline executions.

        One-shot tests and remote HTTP invocations deliberately stay out of this
        view: neither represents a running local evaluation pipeline.
        """
        # This is the build-facing operations view, not a raw run log.  Keep
        # exactly one (the most recent) pipeline state per evaluation build so
        # completed and failed activity remains visible without duplicate rows.
        active = []
        seen_builds: set[str] = set()
        builds_by_id = {build["id"]: build for build in self.evaluation_builds()}
        existing_build_ids = set(builds_by_id)
        for run in sorted(
            runs if runs is not None else self.runs(), key=lambda item: item.created_at, reverse=True
        ):
            if run.execution_type != "pipeline" or run.execution_mode != "run" or not run.evaluation_build_id:
                continue
            if run.evaluation_build_id not in existing_build_ids:
                continue
            if run.evaluation_build_id in seen_builds:
                continue
            seen_builds.add(run.evaluation_build_id)
            item = run.model_dump(mode="json")
            # The run-level response is the newest iteration only. The table
            # represents the whole retained run, so a successful later
            # iteration must not hide feedback recorded by an earlier one.
            responses = [
                record.get("response")
                for record in run.supervisor_results
                if isinstance(record, dict) and isinstance(record.get("response"), dict)
            ]
            if not responses and isinstance(run.supervisor_response, dict):
                responses = [run.supervisor_response]
            improvements = [
                improvement
                for response in responses
                for improvement in response.get("improvements", [])
                if isinstance(improvement, dict)
            ]
            issues = [
                issue
                for response in responses
                for issue in response.get("reported_issues", [])
                if isinstance(issue, dict)
            ]
            item["proposed_improvements"] = len(improvements)
            item["approved_improvements"] = len(
                [item for item in improvements if item.get("status") == "adopted"]
            )
            item["reported_issues"] = len(issues)
            item["approval_score"] = builds_by_id[run.evaluation_build_id].get("approval_score")
            active.append(item)
        return active

    def workflow(self, workflow_id: str) -> Workflow:
        for workflow in self.workflows():
            if workflow.id == workflow_id:
                if workflow.behavior_bundle:
                    load_bundle(workflow.behavior_bundle)
                return workflow
        raise KeyError(workflow_id)

    def _path(self, run_id: str) -> Path:
        return RUNS / f"{run_id}.json"

    def _save(self, run: Run) -> None:
        with self._lock:
            if run.id in self._test_sessions:
                self._test_sessions[run.id] = run
                return
        temporary = self._path(run.id).with_suffix(".tmp")
        temporary.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self._path(run.id))

    def _load(self, run_id: str) -> Run:
        with self._lock:
            session = self._test_sessions.get(run_id)
            if session is not None:
                # Do not expose the mutable in-memory instance to a caller that
                # may run concurrently with the worker thread.
                return Run.model_validate(session.model_dump(mode="python"))
        path = self._path(run_id)
        if not path.exists():
            raise KeyError(run_id)
        return Run.model_validate_json(path.read_text(encoding="utf-8"))

    def run(self, run_id: str) -> Run:
        return self._load(run_id)

    def runs(self) -> list[Run]:
        entries = [Run.model_validate_json(path.read_text(encoding="utf-8")) for path in RUNS.glob("*.json")]
        return sorted(entries, key=lambda run: run.created_at, reverse=True)

    def delete_run(self, run_id: str) -> None:
        run = self._load(run_id)
        if run.status in {"queued", "running", "awaiting_approval"}:
            raise ValueError("Active runs must be stopped before they can be deleted")
        self._path(run.id).unlink()

    def test_session(self, session_id: str) -> Run:
        with self._lock:
            session = self._test_sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            return Run.model_validate(session.model_dump(mode="python"))

    def discard_test_session(self, session_id: str) -> None:
        with self._lock:
            session = self._test_sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            if session.status in {"queued", "running", "awaiting_approval"}:
                raise ValueError("An active test session cannot be discarded")
            del self._test_sessions[session_id]

    def create_run(
        self,
        runner_id: str,
        execution_mode: str = "run",
        evaluation_build_id: str | None = None,
        evaluation_build_name: str | None = None,
        supervisor_profile_name: str | None = None,
        prompt_source: str | None = None,
        prompt_snapshot: str | None = None,
        loop_limit: int = 1,
        timezone: str = "UTC",
        schedule_enabled: bool = False,
        schedule_weekdays: list[int] | None = None,
        schedule_start_time: str = "09:00",
        schedule_end_time: str = "18:00",
        start_iteration: int = 1,
        retry_of_run_id: str | None = None,
        retry_mode: str | None = None,
        repeat_interval_minutes: int = 0,
        cadence_mode: str = "after_completion",
        overrun_policy: str = "wait",
        approval_score: int | None = None,
        iteration_strategy: str = "linear",
        candidates_per_iteration: int = 1,
        repository: str | None = None,
        transient: bool = False,
    ) -> Run:
        if execution_mode not in {"run", "test"}:
            raise ValueError("execution_mode must be run or test")
        runner = self._runner_execution_plan(runner_id)
        needs_approval = False
        run = Run(
            id=uuid.uuid4().hex[:12],
            workflow_id=runner.id,
            workflow_name=runner.name,
            evaluation_build_id=evaluation_build_id,
            evaluation_build_name=evaluation_build_name,
            repository=repository,
            supervisor_profile_name=supervisor_profile_name,
            prompt_source=prompt_source,
            prompt_snapshot=prompt_snapshot,
            execution_mode=execution_mode,
            execution_type="pipeline",
            loop_limit=max(1, loop_limit),
            timezone=timezone,
            schedule_enabled=schedule_enabled,
            schedule_weekdays=schedule_weekdays or [],
            schedule_start_time=schedule_start_time,
            schedule_end_time=schedule_end_time,
            start_iteration=max(1, min(start_iteration, max(1, loop_limit))),
            retry_of_run_id=retry_of_run_id,
            retry_mode=retry_mode if retry_mode in {"restart", "resume"} else None,
            repeat_interval_minutes=max(0, repeat_interval_minutes),
            cadence_mode="fixed" if cadence_mode == "fixed" else "after_completion",
            overrun_policy="interrupt_eval" if overrun_policy == "interrupt_eval" else "wait",
            approval_score=approval_score,
            iteration_strategy=("score_select" if iteration_strategy == "score_select" else "linear"),
            candidates_per_iteration=max(1, candidates_per_iteration),
            status="awaiting_approval" if needs_approval else "queued",
            created_at=now(),
            updated_at=now(),
            approval_reason="변경 적용 또는 고위험 단계가 포함되어 있습니다." if needs_approval else None,
        )
        if transient:
            with self._lock:
                self._test_sessions[run.id] = run
        self._save(run)
        if not needs_approval:
            self._start(run.id)
        return run

    @staticmethod
    def _default_settings() -> dict[str, str]:
        return {
            "profile_name": "Default",
            "provider": "azure-openai",
            "model": "",
            "endpoint": "",
            "region": "us-east-1",
            "secret_env": "AZURE_OPENAI_API_KEY",
            "aws_profile": "",
        }

    def profiles(self) -> list[dict[str, str]]:
        default = self._default_settings()
        if not SETTINGS.exists():
            return [default]
        stored = json.loads(SETTINGS.read_text(encoding="utf-8"))
        raw_profiles = stored.get("profiles") if isinstance(stored, dict) else None
        if not isinstance(raw_profiles, list):
            legacy = dict(default)
            if isinstance(stored, dict):
                legacy.update(stored)
            return [legacy]
        profiles = []
        for item in raw_profiles:
            if isinstance(item, dict) and item.get("profile_name", "").strip():
                profile = dict(default)
                profile.update({key: str(value) for key, value in item.items() if key in default})
                if item.get("created_at"):
                    profile["created_at"] = str(item["created_at"])
                profiles.append(profile)
        return profiles or [default]

    def settings(self) -> dict[str, str]:
        profiles = self.profiles()
        active = ""
        if SETTINGS.exists():
            stored = json.loads(SETTINGS.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                active = str(stored.get("active_profile", ""))
        return next((profile for profile in profiles if profile["profile_name"] == active), profiles[0])

    def application_settings(self) -> dict[str, Any]:
        """Settings for operating this console, separate from build assets."""
        if not SETTINGS.exists():
            return {
                "manager_prompt_template": DEFAULT_OPERATIONAL_MANAGER_PROMPT,
                "manager_output_locale": "en",
                "chat_model_profile_name": "",
                "assistant_tools": normalize_assistant_tools(None),
            }
        stored = json.loads(SETTINGS.read_text(encoding="utf-8"))
        values = stored.get("application_settings", {}) if isinstance(stored, dict) else {}
        if not isinstance(values, dict):
            return {
                "manager_prompt_template": DEFAULT_OPERATIONAL_MANAGER_PROMPT,
                "manager_output_locale": "en",
                "chat_model_profile_name": "",
                "assistant_tools": normalize_assistant_tools(None),
            }
        prompt = str(values.get("manager_prompt_template", "")).strip()
        if MANAGER_PROMPT_SLOT not in prompt:
            prompt = f"{prompt}\n\n{MANAGER_PROMPT_SLOT}".strip()
        if MANAGER_OUTPUT_LANGUAGE_SLOT not in prompt:
            prompt = f"{prompt}\n\n{MANAGER_OUTPUT_LANGUAGE_SLOT}".strip()
        output_locale = str(values.get("manager_output_locale", "en")).strip() or "en"
        return {
            "manager_prompt_template": prompt or DEFAULT_OPERATIONAL_MANAGER_PROMPT,
            "manager_output_locale": output_locale,
            "chat_model_profile_name": str(values.get("chat_model_profile_name", "")).strip(),
            "assistant_tools": normalize_assistant_tools(values.get("assistant_tools")),
        }

    def save_application_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        current = self.application_settings()
        chat_profile_name = str(
            values.get("chat_model_profile_name", current["chat_model_profile_name"])
        ).strip()
        output_locale = (
            str(values.get("manager_output_locale", current["manager_output_locale"])).strip()
            or current["manager_output_locale"]
        )
        if chat_profile_name and not any(
            item["profile_name"] == chat_profile_name for item in self.profiles()
        ):
            raise ValueError("AI model profile does not exist")
        stored = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
        document = stored if isinstance(stored, dict) else {}
        document["application_settings"] = {
            "manager_prompt_template": str(
                values.get("manager_prompt_template", current["manager_prompt_template"])
            ).strip(),
            "manager_output_locale": output_locale,
            "chat_model_profile_name": chat_profile_name,
            "assistant_tools": normalize_assistant_tools(
                values.get("assistant_tools", current["assistant_tools"])
            ),
        }
        temporary = SETTINGS.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
        temporary.replace(SETTINGS)
        return self.application_settings()

    def save_settings(self, values: dict[str, str]) -> dict[str, str]:
        allowed = {"profile_name", "provider", "model", "endpoint", "region", "secret_env", "aws_profile"}
        stored = {key: str(value) for key, value in values.items() if key in allowed}
        stored["profile_name"] = stored.get("profile_name", "").strip()
        if not stored["profile_name"]:
            raise ValueError("프로필 이름을 입력해야 합니다.")
        existing_profile = next(
            (item for item in self.profiles() if item["profile_name"] == stored["profile_name"]), None
        )
        profile = dict(self._default_settings())
        profile.update(stored)
        profile["created_at"] = (existing_profile or {}).get("created_at", now().isoformat())
        profiles = self.profiles() if SETTINGS.exists() else []
        profiles = [item for item in profiles if item["profile_name"] != profile["profile_name"]]
        profiles.append(profile)
        temporary = SETTINGS.with_suffix(".tmp")
        existing = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
        document = existing if isinstance(existing, dict) else {}
        document.update({"active_profile": profile["profile_name"], "profiles": profiles})
        temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
        temporary.replace(SETTINGS)
        return self.settings()

    def delete_profile(self, profile_name: str) -> None:
        profiles = self.profiles()
        if not any(item["profile_name"] == profile_name for item in profiles):
            raise KeyError(profile_name)
        if any(build.get("model_profile_name") == profile_name for build in self.evaluation_builds()):
            raise ValueError("AI model profile is used by an evaluation build")
        if self.application_settings()["chat_model_profile_name"] == profile_name:
            raise ValueError("AI model profile is used by the chat assistant")
        remaining = [item for item in profiles if item["profile_name"] != profile_name]
        stored = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
        document = stored if isinstance(stored, dict) else {}
        document["profiles"] = remaining
        if document.get("active_profile") == profile_name:
            document["active_profile"] = remaining[0]["profile_name"] if remaining else ""
        temporary = SETTINGS.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
        temporary.replace(SETTINGS)

    def _wait_for_tool_interval(self, step_id: str, minimum_seconds: int) -> None:
        if minimum_seconds == 0:
            return
        last_times = json.loads(TOOL_TIMES.read_text(encoding="utf-8")) if TOOL_TIMES.exists() else {}
        previous = last_times.get(step_id)
        if previous:
            elapsed = (now() - datetime.fromisoformat(previous)).total_seconds()
            if elapsed < minimum_seconds:
                raise ValueError(
                    f"Tool interval active for {step_id}; "
                    f"retry in {round(minimum_seconds - elapsed)} seconds."
                )
        last_times[step_id] = now().isoformat()
        TOOL_TIMES.write_text(json.dumps(last_times, indent=2), encoding="utf-8")

    def approve(self, run_id: str) -> Run:
        run = self._load(run_id)
        if run.status != "awaiting_approval":
            raise ValueError("승인을 기다리는 실행이 아닙니다.")
        run.status, run.updated_at = "queued", now()
        self._save(run)
        self._start(run_id)
        return self._load(run_id)

    def reject(self, run_id: str) -> Run:
        run = self._load(run_id)
        if run.status not in {"awaiting_approval", "queued"}:
            raise ValueError("대기 중인 실행만 거절할 수 있습니다.")
        run.status, run.updated_at, run.finished_at = "cancelled", now(), now()
        self._save(run)
        return run

    def _start(self, run_id: str) -> None:
        threading.Thread(target=self._execute, args=(run_id,), daemon=True).start()

    def _execute(self, run_id: str) -> None:
        run = self._load(run_id)
        workflow = self._runner_execution_plan(run.workflow_id)
        resources: dict[str, Any] = {
            "workflow": workflow.model_dump(mode="json"),
            "evaluation_build": {},
            "test_cases": [],
        }
        if run.evaluation_build_id:
            build = self.evaluation_build(run.evaluation_build_id)
            resources["evaluation_build"] = {
                key: value for key, value in build.items() if key not in {"executor"}
            }
            resources["execution_environment"] = self._execution_environment(
                str(build.get("execution_environment_id", ""))
            )
            selected = next(
                (
                    item
                    for item in self.target_test_case_sets()
                    if item.get("id") == build.get("test_case_set_id")
                ),
                None,
            )
            resources["test_cases"] = selected.get("cases", []) if selected else build.get("test_cases", [])
            profile_name = str(build.get("model_profile_name", ""))
            resources["model_profile"] = next(
                (profile for profile in self.profiles() if profile.get("profile_name") == profile_name),
                self.settings(),
            )
        # A build repository is the product under evaluation, while a workflow
        # step may execute through a separate adapter project (for example the
        # Insighta user simulator).  Keep each step's runner directory intact;
        # the build repository is still captured on the Run and in its prompt.
        if workflow.runner_id:
            runner_path = RUNNERS / f"{workflow.runner_id}.py"
            for step in [*workflow.steps, *(workflow.test_steps or [])]:
                step.command = [sys.executable, str(runner_path), "--phase", step.phase]
                step.working_directory = run.repository or str(ROOT)
        with self.tracer.start_as_current_span(
            "workflow.run",
            attributes={
                "workflow.id": workflow.id,
                "run.id": run_id,
                "workflow.kind": workflow.kind,
            },
        ) as workflow_span:
            trace_id = f"{workflow_span.get_span_context().trace_id:032x}"
            run.status, run.updated_at, run.telemetry_trace_id = "running", now(), trace_id
            self._save(run)
            steps = workflow.steps_for(run.execution_mode)
            init = [step for step in steps if step.phase == "init"]
            loop_steps = [step for step in steps if step.phase in {"setup", "run", "eval"}]
            teardown_steps = [step for step in steps if step.phase == "teardown"]
            finalize = [step for step in steps if step.phase == "finalize"]
            if not self._wait_for_schedule(run_id):
                return
            if run.start_iteration == 1 and run.retry_mode != "resume":
                for step in init:
                    self._execute_step(run_id, step, 0, resources)
                    if self._load(run_id).status in {"failed", "cancelled"}:
                        break
            for loop_index in range(run.start_iteration, run.loop_limit + 1):
                if not self._wait_for_schedule(run_id):
                    break
                run = self._load(run_id)
                if run.cadence_mode == "fixed" and run.repeat_interval_minutes:
                    run.iteration_deadline_at = run.created_at + timedelta(
                        minutes=run.repeat_interval_minutes * loop_index
                    )
                    self._save(run)
                candidate_ids = (
                    (
                        [str(loop_index)]
                        if loop_index == 1
                        else [f"{loop_index}-{index}" for index in range(1, run.candidates_per_iteration + 1)]
                    )
                    if run.iteration_strategy == "score_select"
                    else []
                )
                base_candidate_id = next(
                    (
                        str(item["id"])
                        for item in reversed(run.iteration_candidates)
                        if item.get("iteration") == loop_index - 1 and item.get("selected")
                    ),
                    None,
                )
                candidate_results: list[dict[str, Any]] = []
                for candidate_id in candidate_ids:
                    if self._load(run_id).status in {"failed", "cancelled"}:
                        break
                    for step in loop_steps:
                        self._execute_step(
                            run_id,
                            step,
                            loop_index,
                            resources,
                            candidate_id=candidate_id,
                            base_candidate_id=base_candidate_id,
                        )
                        if self._load(run_id).status in {"failed", "cancelled"}:
                            break
                    for step in teardown_steps:
                        self._execute_step(
                            run_id,
                            step,
                            loop_index,
                            resources,
                            allow_terminal=True,
                            candidate_id=candidate_id,
                            base_candidate_id=base_candidate_id,
                        )
                    if self._load(run_id).status == "running" and run.execution_mode == "run":
                        self._complete_supervision(run_id)
                        record = (self._load(run_id).supervisor_results or [])[-1:]
                        response = record[0].get("response", {}) if record else {}
                        evaluation = response.get("evaluation", {}) if isinstance(response, dict) else {}
                        candidate_results.append(
                            {
                                "id": candidate_id,
                                "iteration": loop_index,
                                "score": evaluation.get("score"),
                                "status": record[0].get("status") if record else "failed",
                            }
                        )
                if candidate_results:
                    ranked = sorted(
                        candidate_results,
                        key=lambda item: (
                            item.get("score") is not None,
                            item.get("score") or float("-inf"),
                            item["id"],
                        ),
                        reverse=True,
                    )
                    winner = ranked[0]
                    current = self._load(run_id)
                    for candidate in candidate_results:
                        candidate["selected"] = candidate["id"] == winner["id"]
                    current.iteration_candidates.extend(candidate_results)
                    self._save(current)
                if run.iteration_strategy == "score_select":
                    continue
                terminal_before_iteration = self._load(run_id).status in {"failed", "cancelled"}
                if not terminal_before_iteration:
                    for step in loop_steps:
                        self._execute_step(run_id, step, loop_index, resources)
                        if self._load(run_id).status in {"failed", "cancelled"}:
                            break
                # Cleanup is part of the lifecycle contract, not merely the
                # happy path. Run it after an earlier phase fails or a user
                # cancels the Run; the terminal status remains unchanged.
                for step in teardown_steps:
                    self._execute_step(run_id, step, loop_index, resources, allow_terminal=True)
                if self._load(run_id).status in {"failed", "cancelled"}:
                    break
                if (
                    self._load(run_id).status == "running"
                    and run.execution_mode == "run"
                    and self._latest_cycle_has_persona_evidence(self._load(run_id))
                ):
                    self._complete_supervision(run_id)
                if (
                    loop_index < run.loop_limit
                    and run.repeat_interval_minutes
                    and run.execution_mode == "run"
                    and self._load(run_id).status == "running"
                ):
                    run = self._load(run_id)
                    run.current_step, run.current_phase, run.updated_at = None, "waiting", now()
                    self._save(run)
                    wait_seconds = run.repeat_interval_minutes * 60
                    if run.cadence_mode == "fixed":
                        next_start = run.created_at + timedelta(
                            minutes=run.repeat_interval_minutes * loop_index
                        )
                        wait_seconds = max(0, int((next_start - now()).total_seconds()))
                    for _ in range(wait_seconds):
                        if self._load(run_id).status != "running":
                            break
                        time.sleep(1)
            for step in finalize:
                # Finalization owns process-level recovery. It must still run
                # after a failed or cancelled iteration so a runner can restore
                # the repository baseline it captured during setup.
                self._execute_step(run_id, step, run.loop_limit + 1, resources, allow_terminal=True)
            run = self._load(run_id)
            if run.status == "running":
                run.status = "succeeded"
                run.current_step, run.current_phase, run.updated_at, run.finished_at = (
                    None,
                    None,
                    now(),
                    now(),
                )
                self._save(run)

    @staticmethod
    def _latest_cycle_has_persona_evidence(run: Run) -> bool:
        """Only spend a supervisor call when the bounded cycle did real work.

        The source daemon polls frequently but often finds no active/due persona.
        OpenOrbit preserves that polling behavior without treating an empty poll
        as an evaluation outcome.
        """
        for step in reversed(run.step_results):
            if step.get("phase") != "run":
                continue
            result = step.get("result")
            if not isinstance(result, dict):
                return False
            cycle = (
                result.get("insighta_persona_simulator")
                or result.get("persona_cycle")
                or result.get("user_journey")
                or result.get("improvement_cycle")
                or result.get("jgent_paired")
                or result.get("agent_cycle")
                or result.get("probe_gate")
                or result.get("browser_journey")
                or result.get("site_exploration")
            )
            if not isinstance(cycle, dict):
                return False
            return bool(
                cycle.get("persona_evidence")
                or cycle.get("processed_personas")
                or cycle.get("results")
                or cycle.get("evidence")
                or cycle.get("candidate_fingerprint")
                or cycle.get("prompt_update")
                or cycle.get("report")
                or cycle.get("result")
            )
        return False

    @staticmethod
    def _validated_supervisor_result(text: str) -> dict[str, Any]:
        """Validate the exact structured result required by the manager template."""
        try:
            result = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("supervisor did not return valid JSON") from error
        if not isinstance(result, dict) or not {"improvements", "reported_issues"}.issubset(result):
            raise ValueError("supervisor JSON must contain improvements and reported_issues")
        if set(result) not in (
            {"improvements", "reported_issues"},
            {"evaluation", "improvements", "reported_issues"},
        ):
            raise ValueError("supervisor JSON contains unsupported result fields")
        if not all(
            isinstance(result[key], list) and all(isinstance(item, dict) for item in result[key])
            for key in ("improvements", "reported_issues")
        ):
            raise ValueError("supervisor improvements and reported_issues must be arrays of objects")
        evaluation = result.get("evaluation")
        if evaluation is not None:
            if (
                not isinstance(evaluation, dict)
                or not {"score", "approval", "summary"}.issubset(evaluation)
                or not set(evaluation).issubset(
                    {"score", "approval", "summary", "behavior_summary", "behavior_trace"}
                )
            ):
                raise ValueError(
                    "supervisor evaluation must contain score, approval, summary, and behavior_summary"
                )
            score = evaluation["score"]
            if isinstance(score, str):
                try:
                    score = float(score.strip())
                except ValueError:
                    pass
                else:
                    evaluation["score"] = score
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 10:
                raise ValueError("supervisor evaluation score must be between 0 and 10")
            if evaluation["approval"] not in {"approved", "rejected", "pending"} or not isinstance(
                evaluation["summary"], str
            ):
                raise ValueError("supervisor evaluation approval or summary is invalid")
            if "behavior_summary" in evaluation and not isinstance(evaluation["behavior_summary"], str):
                raise ValueError("supervisor evaluation behavior_summary is invalid")
            if "behavior_trace" in evaluation:
                trace = evaluation["behavior_trace"]
                trace_fields = {"purpose", "rationale", "observation", "decision", "next_action"}
                if (
                    not isinstance(trace, dict)
                    or set(trace) != trace_fields
                    or not all(
                        isinstance(trace[field], str) and trace[field].strip() for field in trace_fields
                    )
                ):
                    raise ValueError("supervisor evaluation behavior_trace is invalid")
        return result

    def _complete_supervision(self, run_id: str) -> None:
        """Ask the configured manager model and retain its validated JSON per Run.

        A missing profile is observable but never turns a successfully completed
        target pipeline into a failed pipeline.
        """
        run = self._load(run_id)
        # Finalization is recorded after the last run/eval loop and therefore
        # has a higher loop index.  Supervision must evaluate the most recent
        # loop that actually produced runner evidence, not that bookkeeping
        # phase.
        iteration = max(
            (
                int(item.get("loop_index", 0))
                for item in run.step_results
                if item.get("phase") in {"run", "eval"}
            ),
            default=0,
        )
        candidate_id = next(
            (
                str(item.get("candidate_id"))
                for item in reversed(run.step_results)
                if item.get("loop_index") == iteration and item.get("candidate_id")
            ),
            None,
        )
        configured = next(
            (item for item in self.profiles() if item["profile_name"] == run.supervisor_profile_name),
            self.settings(),
        )
        if not configured.get("model"):
            run.supervisor_status, run.supervisor_error, run.updated_at = (
                "not_configured",
                "No AI model profile is configured.",
                now(),
            )
            run.supervisor_results.append(
                {
                    "iteration": iteration,
                    "status": "not_configured",
                    "error": run.supervisor_error,
                    "recorded_at": now().isoformat(),
                }
            )
            self._save(run)
            return
        settings = ModelSettings(**{key: value for key, value in configured.items() if key != "profile_name"})
        provider = AzureOpenAIProvider() if settings.provider == "azure-openai" else BedrockProvider()

        def supervisor_result(result: object) -> object:
            if not isinstance(result, dict):
                return result
            # Embedded runners can materialize a large source bundle.  Its file
            # manifest is useful for audit but would crowd out the actual
            # persona evidence the manager must evaluate.
            for key in (
                "insighta_persona_simulator",
                "persona_cycle",
                "user_journey",
                "improvement_cycle",
                "jgent_paired",
                "agent_cycle",
                "probe_gate",
            ):
                if key in result:
                    return {key: result[key]}
            return result

        cycle_evidence = [
            {
                "phase": item.get("phase"),
                "iteration": item.get("loop_index"),
                "exit_code": item.get("exit_code"),
                "result": supervisor_result(item.get("result")),
                "output": str(item.get("output", ""))[-4_000:],
            }
            for item in run.step_results
            if item.get("phase") in {"setup", "run", "eval"} and item.get("loop_index") == iteration
        ]
        # A native improvement runner can update its rollback-protected prompt
        # during setup. Reassemble before every supervision pass so the next
        # iteration uses that exact file version; the actual text is retained
        # on the supervisor result below for auditability.
        supervisor_prompt = run.prompt_snapshot or ""
        if run.evaluation_build_id:
            try:
                _, supervisor_prompt = self._assembled_prompt(self.evaluation_build(run.evaluation_build_id))
            except ValueError:
                # The original immutable run snapshot remains a safe fallback
                # if an operator has made the prompt temporarily unreadable.
                pass
        if cycle_evidence:
            supervisor_prompt += "\n\n# OpenOrbit cycle evidence\n"
            supervisor_prompt += json.dumps(cycle_evidence, ensure_ascii=False, default=str)
        with self.tracer.start_as_current_span(
            "supervisor.evaluate",
            attributes={
                "run.id": run_id,
                "gen_ai.provider.name": settings.provider,
                "gen_ai.request.model": settings.model,
                "orbit.manager.template": (
                    self.evaluation_build(run.evaluation_build_id).get("manager_template_id")
                    if run.evaluation_build_id
                    else ""
                ),
                "orbit.iteration": iteration,
            },
        ) as span:
            try:
                result = self._validated_supervisor_result(provider.complete(settings, supervisor_prompt))
                evaluation = result.get("evaluation")
                if evaluation is not None:
                    threshold = (
                        run.approval_score
                        if run.approval_score is not None
                        else int(self.evaluation_build(run.evaluation_build_id).get("approval_score", 0))
                    )
                    evaluation["approval"] = "approved" if evaluation["score"] >= threshold else "rejected"
                reported_at = now().isoformat()
                for improvement in result["improvements"]:
                    improvement.setdefault("reported_at", reported_at)
                    improvement.setdefault("effect_score", (result.get("evaluation") or {}).get("score"))
                    improvement.setdefault("attempted", improvement.get("status") in {"adopted", "rejected"})
                for issue in result["reported_issues"]:
                    issue.setdefault("reported_at", reported_at)
                run = self._load(run_id)
                run.supervisor_status, run.supervisor_response, run.supervisor_error, run.updated_at = (
                    "completed",
                    result,
                    None,
                    now(),
                )
                run.supervisor_results.append(
                    {
                        "iteration": iteration,
                        "candidate_id": candidate_id,
                        "status": "completed",
                        "prompt": supervisor_prompt,
                        "response": result,
                        "recorded_at": now().isoformat(),
                    }
                )
                self._save(run)
                self._review_cycle_improvement(run, iteration, result, settings, provider)
                span.set_attribute("orbit.supervisor.improvements", len(result["improvements"]))
                span.set_attribute("orbit.supervisor.reported_issues", len(result["reported_issues"]))
                span.add_event("supervisor.response.validated")
            except ValueError as error:
                run = self._load(run_id)
                run.supervisor_status, run.supervisor_error, run.updated_at = (
                    "invalid_response",
                    str(error),
                    now(),
                )
                run.supervisor_results.append(
                    {
                        "iteration": iteration,
                        "status": "invalid_response",
                        "prompt": supervisor_prompt,
                        "error": str(error),
                        "recorded_at": now().isoformat(),
                    }
                )
                self._save(run)
                span.record_exception(error)
                span.add_event("supervisor.response.invalid", {"reason": str(error)})
            except (RuntimeError, requests.RequestException) as error:
                run = self._load(run_id)
                run.supervisor_status, run.supervisor_error, run.updated_at = "failed", str(error), now()
                run.supervisor_results.append(
                    {
                        "iteration": iteration,
                        "status": "failed",
                        "prompt": supervisor_prompt,
                        "error": str(error),
                        "recorded_at": now().isoformat(),
                    }
                )
                self._save(run)
                span.record_exception(error)
                span.add_event("supervisor.request.failed", {"reason": str(error)})

    def _review_cycle_improvement(
        self, run: Run, iteration: int, result: dict[str, Any], settings: ModelSettings, provider: Any
    ) -> None:
        """Let a second AI pass improve the operating cycle, not the target."""
        prompt = (
            """You improve an OpenOrbit evaluation cycle, not the evaluated product.\nReturn exactly JSON: {\"diagnosis\":\"string\",\"interventions\":[{\"target\":\"runner|workflow|test_case_set|manager_prompt|schedule\",\"title\":\"string\",\"rationale\":\"string\",\"proposed_change\":\"string\",\"risk\":\"low|medium|high\",\"validation\":\"string\",\"rollback\":\"string\"}]}.\nOnly propose evidence-backed changes. Do not propose target repository code changes.\n\n"""
            + json.dumps(
                {
                    "evaluation_build": run.evaluation_build_name,
                    "iteration": iteration,
                    "supervisor_result": result,
                },
                ensure_ascii=False,
            )
        )
        try:
            reviewed = json.loads(provider.complete(settings, prompt))
            interventions = reviewed.get("interventions", []) if isinstance(reviewed, dict) else []
            if not isinstance(interventions, list):
                return
            stored = self.cycle_interventions()
            for intervention in interventions:
                if not isinstance(intervention, dict) or not isinstance(intervention.get("title"), str):
                    continue
                stored.append(
                    {
                        "id": f"ci-{uuid.uuid4().hex[:10]}",
                        "evaluation_build_id": run.evaluation_build_id,
                        "evaluation_build_name": run.evaluation_build_name,
                        "run_id": run.id,
                        "iteration": iteration,
                        "diagnosis": str(reviewed.get("diagnosis", "")),
                        "status": "proposed",
                        "created_at": now().isoformat(),
                        **intervention,
                    }
                )
            self._save_cycle_interventions(stored)
        except (ValueError, RuntimeError, requests.RequestException, json.JSONDecodeError):
            return

    def _execute_step(
        self,
        run_id: str,
        step,
        loop_index: int = 1,
        resources: dict[str, Any] | None = None,
        *,
        allow_terminal: bool = False,
        candidate_id: str | None = None,
        base_candidate_id: str | None = None,
    ) -> None:  # type: ignore[no-untyped-def]
        with self.tracer.start_as_current_span(
            "workflow.step",
            attributes={
                "run.id": run_id,
                "step.id": step.id,
                "step.phase": step.phase,
            },
        ) as span:
            run = self._load(run_id)
            if run.status in {"failed", "cancelled"} and not allow_terminal:
                return
            run.current_step, run.current_phase, run.updated_at = step.id, step.phase, now()
            self._save(run)
            configured_directory = Path(step.working_directory).expanduser()
            directory = (
                configured_directory.resolve()
                if configured_directory.is_absolute()
                else (ROOT / configured_directory).resolve()
            )
            if not directory.is_dir():
                self._fail(run, step.id, "working_directory is missing")
                return
            started = now()
            try:
                self._wait_for_tool_interval(step.id, step.minimum_interval_seconds)
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                environment = os.environ.copy()
                execution_environment = (resources or {}).get("execution_environment", {})
                if isinstance(execution_environment, dict):
                    configured_variables = execution_environment.get("environment_variables", {})
                    if isinstance(configured_variables, dict):
                        environment.update(
                            {
                                str(key): str(value)
                                for key, value in configured_variables.items()
                                if str(key).strip()
                            }
                        )
                environment["PYTHONPATH"] = str(ROOT / "backend") + (
                    os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
                )
                environment["ORBIT_TARGET_REPOSITORY"] = run.repository or step.working_directory
                environment["ORBIT_APP_DATA"] = str(APP_DATA)
                environment["ORBIT_EXECUTION_MODE"] = run.execution_mode
                environment["ORBIT_LOOP_INDEX"] = str(loop_index)
                if candidate_id:
                    environment["ORBIT_CANDIDATE_ID"] = candidate_id
                if base_candidate_id:
                    environment["ORBIT_BASE_CANDIDATE_ID"] = base_candidate_id
                environment["ORBIT_RUN_ID"] = run_id
                environment["ORBIT_RUNNER_RESOURCES"] = base64.b64encode(
                    json.dumps(resources or {}, ensure_ascii=False).encode("utf-8")
                ).decode("ascii")
                if run.prompt_snapshot:
                    environment["ORBIT_EVALUATION_PROMPT"] = run.prompt_snapshot
                if run.evaluation_build_id:
                    environment["ORBIT_EVALUATION_BUILD_ID"] = run.evaluation_build_id
                process = subprocess.Popen(
                    step.command,
                    cwd=directory,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=os.name != "nt",
                    creationflags=creation_flags,
                    env=environment,
                )
                interruption_timer: threading.Timer | None = None
                if (
                    step.phase == "eval"
                    and run.overrun_policy == "interrupt_eval"
                    and run.iteration_deadline_at
                ):
                    delay = (run.iteration_deadline_at - now()).total_seconds()
                    if delay <= 0:
                        delay = 0.01

                    def interrupt_overdue_evaluation() -> None:
                        current = self._load(run_id)
                        if current.current_phase != "eval" or process.poll() is not None:
                            return
                        current.advance_requested, current.updated_at = True, now()
                        self._save(current)
                        if os.name == "nt":
                            process.terminate()
                        else:
                            os.killpg(process.pid, signal.SIGTERM)

                    interruption_timer = threading.Timer(delay, interrupt_overdue_evaluation)
                    interruption_timer.daemon = True
                    interruption_timer.start()
                captured_lines: list[tuple[str, str]] = []
                live_step_key = f"{step.id}:{loop_index}:{candidate_id or '-'}:{started}"

                def retained_visible_lines() -> list[tuple[str, str]]:
                    retained: list[tuple[str, str]] = []
                    retained_size = 0
                    for item in reversed(captured_lines):
                        if item[1].startswith("__ORBIT_RESULT__"):
                            continue
                        line_size = len(item[1]) + (1 if retained else 0)
                        if retained and retained_size + line_size > 12_000:
                            break
                        retained.append(item)
                        retained_size += line_size
                    retained.reverse()
                    return retained

                def persist_live_output() -> None:
                    retained = retained_visible_lines()
                    # `_load` and `_save` each acquire the store lock for their
                    # in-memory test-session handling.  Do not hold it here as
                    # well: `Lock` is deliberately non-reentrant, and doing so
                    # would deadlock the reader thread on its first live update.
                    current = self._load(run_id)
                    for item in reversed(current.step_results):
                        if item.get("_live_step_key") == live_step_key:
                            item["output"] = "\n".join(line for _, line in retained)
                            item["log_lines"] = [
                                {"timestamp": timestamp, "value": line} for timestamp, line in retained
                            ]
                            current.updated_at = now()
                            self._save(current)
                            return

                def capture_output() -> None:
                    assert process.stdout is not None
                    last_persist = 0.0
                    for line in process.stdout:
                        captured_lines.append((now(), line.rstrip("\r\n")))
                        if time.monotonic() - last_persist >= 0.75:
                            persist_live_output()
                            last_persist = time.monotonic()

                output_reader = threading.Thread(target=capture_output, daemon=True)
                output_reader.start()
                with self._lock:
                    self._processes[run_id] = process
                run = self._load(run_id)
                run.pid, run.last_pid, run.updated_at = process.pid, process.pid, now()
                run.step_results.append(
                    {
                        "step_id": step.id,
                        "phase": step.phase,
                        "loop_index": loop_index,
                        "candidate_id": candidate_id,
                        "name": step.name,
                        "command": step.command,
                        "working_directory": str(directory),
                        "started_at": started,
                        "in_progress": True,
                        "_live_step_key": live_step_key,
                        "output": "",
                        "log_lines": [],
                    }
                )
                self._save(run)
                span.set_attribute("process.pid", process.pid)
                process.wait(timeout=step.timeout_seconds)
                if interruption_timer:
                    interruption_timer.cancel()
                output_reader.join()
                persist_live_output()
                structured_result: dict[str, Any] | None = None
                target_logs: list[dict[str, Any]] = []
                data_files: list[dict[str, Any]] = []
                visible_lines: list[tuple[str, str]] = []
                for timestamp, line in captured_lines:
                    if line.startswith("__ORBIT_RESULT__"):
                        try:
                            emitted = json.loads(line.removeprefix("__ORBIT_RESULT__"))
                            if not isinstance(emitted, dict):
                                raise ValueError("structured runner result must be an object")
                            emitted_target_logs = emitted.pop("target_logs", [])
                            if isinstance(emitted_target_logs, list):
                                for entry in emitted_target_logs:
                                    if not isinstance(entry, dict):
                                        continue
                                    message = entry.get("message")
                                    if not isinstance(message, str) or not message.strip():
                                        continue
                                    target_logs.append(
                                        {
                                            "timestamp": entry.get("timestamp")
                                            if isinstance(entry.get("timestamp"), str)
                                            else timestamp,
                                            "level": str(entry.get("level") or "info")[:32],
                                            "source": str(entry.get("source") or "")[:256],
                                            "message": message.strip()[:4000],
                                            "run_id": run_id,
                                            "iteration": loop_index,
                                            "phase": step.phase,
                                        }
                                    )
                            emitted_data_files = emitted.pop("data_files", [])
                            if isinstance(emitted_data_files, list):
                                for entry in emitted_data_files:
                                    if not isinstance(entry, dict):
                                        continue
                                    path = entry.get("path")
                                    relative_path = entry.get("relative_path")
                                    if not isinstance(path, str) or not isinstance(relative_path, str):
                                        continue
                                    data_files.append(
                                        {
                                            "label": str(entry.get("label") or "")[:256],
                                            "filename": str(
                                                entry.get("filename") or Path(relative_path).name
                                            ),
                                            "path": path,
                                            "relative_path": relative_path,
                                            "sha256": str(entry.get("sha256") or ""),
                                            "size": entry.get("size")
                                            if isinstance(entry.get("size"), int)
                                            else 0,
                                            "content_type": str(entry.get("content_type") or ""),
                                        }
                                    )
                            structured_result = {**(structured_result or {}), **emitted}
                        except json.JSONDecodeError:
                            visible_lines.append((timestamp, line))
                    else:
                        visible_lines.append((timestamp, line))
                retained_lines = retained_visible_lines()
                result: dict[str, Any] = {
                    "step_id": step.id,
                    "phase": step.phase,
                    "loop_index": loop_index,
                    "candidate_id": candidate_id,
                    "name": step.name,
                    "command": step.command,
                    "working_directory": str(directory),
                    "started_at": started,
                    "ended_at": now(),
                    "exit_code": process.returncode,
                    "output": "\n".join(line for _, line in retained_lines),
                    "log_lines": [
                        {"timestamp": timestamp, "value": line} for timestamp, line in retained_lines
                    ],
                }
                if structured_result is not None:
                    result["result"] = structured_result
                if target_logs:
                    result["target_logs"] = target_logs[-200:]
                if data_files:
                    result["data_files"] = data_files
                run = self._load(run_id)
                live_index = next(
                    (
                        index
                        for index, item in enumerate(run.step_results)
                        if item.get("_live_step_key") == live_step_key
                    ),
                    None,
                )
                if live_index is None:
                    run.step_results.append(result)
                else:
                    run.step_results[live_index] = result
                run.pid, run.updated_at = None, now()
                self._save(run)
                span.add_event("process.completed", {"process.exit_code": process.returncode})
                if process.returncode and step.on_failure == "stop":
                    if step.phase == "eval" and run.advance_requested:
                        run.advance_requested = False
                        self._save(run)
                        return
                    # A stop request intentionally terminates the subprocess.
                    # Preserve cancellation while still letting the caller run
                    # the terminal teardown path.
                    if self._load(run_id).status == "cancelled":
                        return
                    self._fail(run, step.id, f"exit code {process.returncode}")
                    return
            except subprocess.TimeoutExpired:
                process.kill()
                span.add_event("process.timeout", {"timeout.seconds": step.timeout_seconds})
                if self._load(run_id).status == "cancelled":
                    return
                self._fail(self._load(run_id), step.id, f"timed out after {step.timeout_seconds}s")
                return
            except ValueError as error:
                span.add_event("step.rejected", {"reason": str(error)})
                self._fail(self._load(run_id), step.id, str(error))
                return
            finally:
                with self._lock:
                    self._processes.pop(run_id, None)

    def _fail(self, run: Run, step_id: str, reason: str) -> None:
        run.status, run.current_step, run.updated_at, run.finished_at = "failed", step_id, now(), now()
        run.step_results.append({"step_id": step_id, "error": reason, "ended_at": now()})
        self._save(run)

    def cancel(self, run_id: str) -> Run:
        run = self._load(run_id)
        with self._lock:
            process = self._processes.get(run_id)
        if process and process.poll() is None:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
        run.status, run.pid, run.current_step, run.current_phase, run.updated_at, run.finished_at = (
            "cancelled",
            None,
            None,
            None,
            now(),
            now(),
        )
        self._save(run)
        return run

    def _wait_for_schedule(self, run_id: str) -> bool:
        while True:
            run = self._load(run_id)
            if run.status in {"failed", "cancelled"}:
                return False
            if not run.schedule_enabled or run.execution_mode != "run":
                return True
            try:
                current = datetime.now(ZoneInfo(run.timezone))
            except ZoneInfoNotFoundError:
                current = datetime.now(UTC)
            now_time = current.strftime("%H:%M")
            weekdays = set(run.schedule_weekdays)
            start, end = run.schedule_start_time, run.schedule_end_time
            in_day = not weekdays or current.weekday() in weekdays
            in_time = start <= now_time <= end if start <= end else now_time >= start or now_time <= end
            if in_day and in_time:
                return True
            run.current_step, run.current_phase, run.updated_at = None, "waiting", now()
            self._save(run)
            time.sleep(30)

    def retry(self, run_id: str, restart_from_first: bool) -> Run:
        run = self._load(run_id)
        if run.execution_type != "pipeline" or run.status not in {"failed", "cancelled"}:
            raise ValueError("Only failed or cancelled pipeline runs can be retried")
        latest_iteration = max(
            (
                int(item.get("loop_index", 0))
                for item in run.step_results
                if int(item.get("loop_index", 0)) > 0
            ),
            default=1,
        )
        return self.create_run(
            run.workflow_id,
            execution_mode=run.execution_mode,
            evaluation_build_id=run.evaluation_build_id,
            evaluation_build_name=run.evaluation_build_name,
            supervisor_profile_name=run.supervisor_profile_name,
            prompt_source=run.prompt_source,
            prompt_snapshot=run.prompt_snapshot,
            loop_limit=run.loop_limit,
            timezone=run.timezone,
            schedule_enabled=run.schedule_enabled,
            schedule_weekdays=run.schedule_weekdays,
            schedule_start_time=run.schedule_start_time,
            schedule_end_time=run.schedule_end_time,
            start_iteration=1 if restart_from_first else min(latest_iteration, run.loop_limit),
            repeat_interval_minutes=run.repeat_interval_minutes,
            cadence_mode=run.cadence_mode,
            overrun_policy=run.overrun_policy,
            approval_score=run.approval_score,
            iteration_strategy=run.iteration_strategy,
            candidates_per_iteration=run.candidates_per_iteration,
            repository=run.repository,
            retry_of_run_id=run.id,
            retry_mode="restart" if restart_from_first else "resume",
        )

    def emergency_stop(self) -> list[Run]:
        stopped = []
        for run in self.runs():
            if run.status in {"queued", "running", "awaiting_approval"}:
                stopped.append(self.cancel(run.id))
        return stopped

    def invoke_remote_build(self, build_id: str, execution_mode: str = "run") -> Run:
        build = self.evaluation_build(build_id)
        executor = build.get("executor", {})
        if not build.get("enabled"):
            raise ValueError("This evaluation build is not enabled.")
        if execution_mode not in {"run", "test"}:
            raise ValueError("execution_mode must be run or test")
        prompt_source, prompt_snapshot = self._assembled_prompt(build)
        if executor.get("type") != "remote-http":
            return self.create_run(
                build["runner_id"],
                execution_mode,
                evaluation_build_id=build["id"],
                evaluation_build_name=build["name"],
                supervisor_profile_name=build.get("model_profile_name"),
                prompt_source=prompt_source,
                prompt_snapshot=prompt_snapshot,
                loop_limit=1 if execution_mode == "test" else int(build.get("run_limit", 1)),
                timezone=str(build.get("timezone", "UTC")),
                schedule_enabled=execution_mode == "run" and bool(build.get("schedule_enabled", False)),
                schedule_weekdays=list(build.get("schedule_weekdays", [])),
                schedule_start_time=str(build.get("schedule_start_time", "09:00")),
                schedule_end_time=str(build.get("schedule_end_time", "18:00")),
                repeat_interval_minutes=0
                if execution_mode == "test"
                else int(build.get("repeat_interval_minutes", 0)),
                cadence_mode=str(build.get("cadence_mode", "after_completion")),
                overrun_policy=str(build.get("overrun_policy", "wait")),
                approval_score=int(build.get("approval_score", 0)),
                iteration_strategy=str(build.get("iteration_strategy", "linear")),
                candidates_per_iteration=int(build.get("candidates_per_iteration", 2)),
                repository=build.get("repository"),
                transient=execution_mode == "test",
            )
        run = Run(
            id=uuid.uuid4().hex[:12],
            workflow_id=build["runner_id"],  # Legacy Run field: stores the direct runner ID.
            workflow_name=self._runner(build["runner_id"])["name"],
            evaluation_build_id=build["id"],
            evaluation_build_name=build["name"],
            supervisor_profile_name=build.get("model_profile_name"),
            execution_mode=execution_mode,
            execution_type="invoke",
            status="queued",
            created_at=now(),
            updated_at=now(),
            current_phase="init",
            prompt_source=prompt_source,
            prompt_snapshot=prompt_snapshot,
        )
        if execution_mode == "test":
            with self._lock:
                self._test_sessions[run.id] = run
        self._save(run)
        threading.Thread(target=self._execute_remote, args=(run.id, executor), daemon=True).start()
        return run

    def test_evaluation_build(self, build_id: str) -> Run:
        build = self.evaluation_build(build_id)
        if not build.get("enabled"):
            raise ValueError("This evaluation build is not enabled.")
        return self.invoke_remote_build(build_id, "test")

    def _execute_remote(self, run_id: str, executor: dict[str, Any]) -> None:
        run = self._load(run_id)
        with self.tracer.start_as_current_span("remote.agent.run", attributes={"run.id": run_id}) as span:
            run.status, run.current_phase, run.telemetry_trace_id, run.updated_at = (
                "running",
                "run",
                f"{span.get_span_context().trace_id:032x}",
                now(),
            )
            self._save(run)
            try:
                invocation_values = {key: value for key, value in executor.items() if key != "type"}
                # Keep an explicitly configured payload, but make the fully
                # resolved target prompt available under a stable contract.
                invocation_values["payload"] = {
                    **(invocation_values.get("payload") or {}),
                    "prompt": run.prompt_snapshot,
                    "evaluation_build_id": run.evaluation_build_id,
                    "execution_mode": run.execution_mode,
                }
                invocation = RemoteInvocation(**invocation_values)
                status_code, output = invocation.invoke()
                span.set_attribute("http.response.status_code", status_code)
                run = self._load(run_id)
                run.step_results.append({"step_id": "run", "http_status": status_code, "output": output})
                run.status = "succeeded" if 200 <= status_code < 300 else "failed"
                run.current_phase, run.updated_at, run.finished_at = "teardown", now(), now()
                self._save(run)
                if run.status == "succeeded":
                    self._complete_supervision(run_id)
            except (ValueError, requests.RequestException) as error:
                span.record_exception(error)
                self._fail(self._load(run_id), "run", str(error))
