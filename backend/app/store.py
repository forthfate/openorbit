from __future__ import annotations

import base64
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

import requests
import yaml

from orbit import load_bundle

from .models import Run, Step, Workflow
from .observability import configure_telemetry
from .providers import AzureOpenAIProvider, BedrockProvider, ModelSettings
from .remote import RemoteInvocation

ROOT = Path(__file__).resolve().parents[2]


def _application_data_dir() -> Path:
    """Return Orbit's writable per-user state directory on every platform."""
    override = os.environ.get("ORBIT_APP_DATA")
    if override:
        return Path(override).expanduser()
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

Your final response must be exactly one JSON object:
{
  \"evaluation\": {\"score\":\"number from 0 to 10\",\"approval\":\"approved|rejected|pending\",\"summary\":\"string\"},
  \"improvements\": [{\"title\":\"string\",\"status\":\"proposed|adopted|rejected\",\"rationale\":\"string\",\"acceptanceEvidence\":\"string\"}],
  \"reported_issues\": [{\"title\":\"string\",\"severity\":\"low|medium|high|critical\",\"evidence\":\"string\",\"reproduction\":\"string\",\"status\":\"open|acknowledged|resolved\"}]
}
Always include both keys, using empty arrays when there are no items."""
MANAGER_PROMPT_SLOT = "__ORBIT_MANAGER_AI_PROMPT__"
NATIVE_IMPROVEMENT_CYCLE_TEMPLATE = r"""# Requirements
# - PROJECT_ROOT is a Git repository.
# - The evaluation build selects fixed browser test cases, a browser base URL,
#   and, when this native runner is selected, a readable managed_prompt_path
#   configured on its Target Environment.
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


def proposal_id(proposal):
    '''Prefer a supplied proposal ID; otherwise derive a stable content ID.'''
    explicit = str(proposal.get("id") or "").strip()
    if explicit:
        return explicit
    source = json.dumps(proposal, ensure_ascii=False, sort_keys=True)
    return f"supervisor-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]}"


def record_feedback_decisions(ctx):
    '''Record only explicit supervisor decisions; undecided feedback remains pending.'''
    feedback = ctx.previous_supervisor_feedback
    decisions = []
    for proposal in feedback.get("improvements", []):
        if not isinstance(proposal, dict):
            continue
        status = str(proposal.get("status") or "").lower()
        rationale = str(proposal.get("rationale") or proposal.get("acceptanceEvidence") or "")
        if status in {"adopted", "accepted"}:
            outcome = ctx.accept_proposal(proposal, proposal_id=proposal_id(proposal), rationale=rationale)
        elif status == "rejected":
            outcome = ctx.reject_proposal(proposal, proposal_id=proposal_id(proposal), rationale=rationale)
        else:
            continue
        decisions.append({"proposal_id": proposal_id(proposal), "status": status, **outcome})
    return decisions


def accepted_proposals(ctx):
    # Keep accepted proposals from prior iterations until a later decision
    # explicitly rejects the same proposal ID.
    latest = {}
    for decision in reversed(ctx.proposal_decisions()):
        proposal = decision.get("proposal")
        proposal_key = decision.get("proposal_id")
        if isinstance(proposal, dict) and proposal_key:
            latest[str(proposal_key)] = decision
    return {
        proposal_id: item["proposal"]
        for proposal_id, item in latest.items()
        if item.get("decision") == "accepted"
    }


def update_prompt_from_accepted_proposals(ctx, proposals):
    '''Replace only OpenOrbit's managed prompt block and retain a rollback version.'''
    prompt_path = str(ctx.evaluation_build.get("managed_prompt_path") or ctx.evaluation_build.get("prompt_bundle") or "").strip()
    if not prompt_path:
        raise ValueError("native improvement cycle requires target_environment.managed_prompt_path")
    target = ctx.project_path(prompt_path)
    current = target.read_text(encoding="utf-8")
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


@runner.phase("init")
def init(ctx):
    # Process-level validation runs once before the iteration loop begins.
    git(ctx, "rev-parse", "--show-toplevel")
    if not ctx.evaluation_build.get("browser_base_url") or not ctx.test_cases:
        raise ValueError("Select a browser base URL and fixed test cases for a native improvement cycle")
    ctx.log("Validated an OpenOrbit-native prompt improvement cycle")


@runner.phase("setup")
def setup(ctx):
    # Apply already accepted feedback before validating the next candidate.
    decisions = record_feedback_decisions(ctx)
    active_proposals = accepted_proposals(ctx)
    prompt_update = update_prompt_from_accepted_proposals(ctx, list(active_proposals.values()))
    prompt_applications = ctx.record_proposal_application(list(active_proposals), prompt_update)
    fingerprint, changed = candidate(ctx)
    ctx.emit_result(
        {
            "improvement_cycle": {
                "iteration": ctx.loop_index,
                "candidate_fingerprint": fingerprint,
                "changed_paths": changed,
                "prompt_update": prompt_update,
                "prompt_applications": prompt_applications,
                "proposal_decisions": decisions,
            }
        }
    )
    ctx.log("Recorded proposal decisions and refreshed the rollback-protected prompt")


@runner.phase("run")
def run(ctx):
    # Browser evidence is the acceptance input; no target change is made here.
    evidence = ctx.playwright_journey()
    results = evidence["results"]
    passed = all(item["passed"] for item in results)
    fingerprint, changed = candidate(ctx)
    ctx.emit_result(
        {
            "improvement_cycle": {
                "iteration": ctx.loop_index,
                "candidate_fingerprint": fingerprint,
                "changed_paths": changed,
                "passed": passed,
                "evidence": evidence,
            }
        }
    )
    if not passed:
        raise SystemExit("A fixed validation journey failed")


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
    # Per-iteration evidence remains available for supervisor review.
    ctx.log("Retained prompt versions, decisions, and validation evidence")


@runner.phase("finalize")
def finalize(ctx):
    # Process-level finalization intentionally leaves the target repository uncommitted.
    ctx.log("Finalized the native improvement cycle without committing changes")


if __name__ == "__main__":
    runner.main()
"""
DATA = APP_DATA / "data"
RUNS = DATA / "runs"
TELEMETRY = DATA / "telemetry.jsonl"
SETTINGS = DATA / "settings.json"
TOOL_TIMES = DATA / "tool-times.json"
RUNNERS = APP_DATA / "runners"
RUNNER_TEMPLATES = APP_DATA / "runner-templates"
# Workflow files are trusted, versioned operator configuration. The API itself
# never accepts an executable or directory from a browser request.
ALLOWED_WORKSPACE_ROOTS = (ROOT.parent.resolve(), Path("/mnt/c/users/forth/projects").resolve())


def now() -> datetime:
    return datetime.now(UTC)


class ConsoleStore:
    """File-backed local state. Commands are always executed without a shell."""

    def __init__(self) -> None:
        self._initialize_application_data()
        RUNS.mkdir(parents=True, exist_ok=True)
        RUNNERS.mkdir(parents=True, exist_ok=True)
        RUNNER_TEMPLATES.mkdir(parents=True, exist_ok=True)
        self._migrate_evaluation_environments()
        self._processes: dict[str, subprocess.Popen[str]] = {}
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
        if not str(application.get("manager_prompt_template", "")).strip():
            document["application_settings"] = {
                **application,
                "manager_prompt_template": DEFAULT_OPERATIONAL_MANAGER_PROMPT,
                "chat_model_profile_name": str(application.get("chat_model_profile_name", "")).strip(),
            }
            SETTINGS.write_text(json.dumps(document, indent=2), encoding="utf-8")

    @staticmethod
    def runner_templates() -> list[dict[str, str]]:
        templates = [
            {
                "id": "user-journey-cycle",
                "name": "User journey cycle",
                "description": "Runs fixed browser journeys directly through OpenOrbit, retaining page evidence and screenshots for every bounded iteration.",
                "source": """# Requirements
# - The target application is running at the evaluation build's browser base URL.
# - The evaluation build selects at least one fixed test case.
# - OpenOrbit's bundled Playwright dependency and browser are available.
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
                "name": "External command adapter",
                "description": "Connects a tool that follows a bounded status, prepare, run-once, and evidence command contract. OpenOrbit retains scheduling and supervision.",
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
            "name": "Native improvement cycle",
            "description": "Updates the configured prompt from accepted supervisor proposals, retains every prior prompt version, validates fixed browser journeys, and records accepted/rejected proposal decisions for review.",
            "source": NATIVE_IMPROVEMENT_CYCLE_TEMPLATE,
        }
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
                on_failure="continue" if phase == "run" else "stop",
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
        return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []

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
        version = int(values.get("version", 0))
        if not name or not content or version < 1:
            raise ValueError("prompt template requires a name, version, and content")
        template = {"id": template_id, "name": name, "version": version, "content": content}
        templates[index] = template
        temporary = CONFIG / "prompt-templates.tmp"
        temporary.write_text(yaml.safe_dump(templates, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(CONFIG / "prompt-templates.yaml")
        return template

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
        version = int(values.get("version", 0))
        if not name or not content or version < 1:
            raise ValueError("prompt template requires a name, version, and content")
        template = {"id": template_id, "name": name, "version": version, "content": content}
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
                operational.replace(MANAGER_PROMPT_SLOT, manager_policy),
                f"# Evaluation context\nRepository: {build.get('repository', '')}\n{legacy_context}",
                case_text,
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
            roots = [root for root in ALLOWED_WORKSPACE_ROOTS if root.is_dir()]
            return {"path": "", "directories": [{"name": root.name, "path": str(root)} for root in roots]}
        directory = Path(path).expanduser().resolve()
        approved = any(directory == root or root in directory.parents for root in ALLOWED_WORKSPACE_ROOTS)
        if not directory.is_dir() or not approved:
            raise ValueError("workspace path must be an approved directory")
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
        approved = any(repository == root or root in repository.parents for root in ALLOWED_WORKSPACE_ROOTS)
        if executor["type"] != "remote-http" and (not repository.is_dir() or not approved):
            raise ValueError("repository must be an existing approved workspace")
        if (
            executor["type"] == "remote-http"
            and not repository_value.startswith("remote://")
            and (not repository.is_dir() or not approved)
        ):
            raise ValueError(
                "remote HTTP builds require an approved repository or a remote:// repository label"
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
            "run_limit": values["run_limit"],
            "approval_score": values["approval_score"],
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
        approved = any(repository == root or root in repository.parents for root in ALLOWED_WORKSPACE_ROOTS)
        if executor["type"] != "remote-http" and (not repository.is_dir() or not approved):
            raise ValueError("repository must be an existing approved workspace")
        if (
            executor["type"] == "remote-http"
            and not repository_value.startswith("remote://")
            and (not repository.is_dir() or not approved)
        ):
            raise ValueError(
                "remote HTTP builds require an approved repository or a remote:// repository label"
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
            "run_limit": values["run_limit"],
            "approval_score": values["approval_score"],
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

    def proposal_decisions(self) -> list[dict[str, Any]]:
        """Read SDK-recorded proposal choices for a future visual review surface.

        Runner SDKs write one ledger per target repository in AppData.  Invalid
        or interrupted ledger files are ignored here so an individual runner's
        local history cannot prevent the control room from loading.
        """
        values: list[dict[str, Any]] = []
        directory = APP_DATA / "proposal-history"
        for path in directory.glob("*/decisions.json") if directory.exists() else []:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
                decisions = document.get("decisions", []) if isinstance(document, dict) else []
                values.extend(item for item in decisions if isinstance(item, dict))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return sorted(values, key=lambda item: str(item.get("recorded_at", "")), reverse=True)

    def proposal_lifecycles(
        self, evaluation_build_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Group append-only SDK events into reviewable proposal lifecycles."""
        grouped: dict[str, dict[str, Any]] = {}
        for event in sorted(self.proposal_decisions(), key=lambda item: str(item.get("recorded_at", ""))):
            build_id = event.get("evaluation_build_id")
            if evaluation_build_id and build_id != evaluation_build_id:
                continue
            proposal_id = str(event.get("proposal_id") or "")
            if not proposal_id:
                continue
            lifecycle = grouped.setdefault(
                proposal_id,
                {
                    "proposal_id": proposal_id,
                    "title": "Untitled proposal",
                    "target": "prompt",
                    "proposal": {},
                    "decision": "pending",
                    "decision_rationale": "",
                    "status": "proposed",
                    "evaluation_build_id": build_id,
                    "evaluation_build_name": event.get("evaluation_build_name"),
                    "run_id": event.get("run_id"),
                    "iteration": event.get("iteration"),
                    "recorded_at": event.get("recorded_at"),
                    "prompt_version": None,
                    "events": [],
                },
            )
            lifecycle["events"].append(event)
            lifecycle["recorded_at"] = event.get("recorded_at") or lifecycle["recorded_at"]
            lifecycle["run_id"] = event.get("run_id") or lifecycle["run_id"]
            lifecycle["iteration"] = event.get("iteration") or lifecycle["iteration"]
            if event.get("evaluation_build_id"):
                lifecycle["evaluation_build_id"] = event["evaluation_build_id"]
                lifecycle["evaluation_build_name"] = event.get("evaluation_build_name")
            if event.get("event_type", "decision") == "decision":
                proposal = event.get("proposal") if isinstance(event.get("proposal"), dict) else {}
                lifecycle["proposal"] = proposal
                lifecycle["title"] = str(proposal.get("title") or lifecycle["title"])
                lifecycle["target"] = str(proposal.get("target") or lifecycle["target"])
                lifecycle["decision"] = str(event.get("decision") or "pending")
                lifecycle["decision_rationale"] = str(event.get("rationale") or "")
                lifecycle["status"] = lifecycle["decision"]
            elif event.get("event_type") == "prompt_updated":
                prompt_version = event.get("prompt_version")
                if isinstance(prompt_version, dict):
                    lifecycle["prompt_version"] = prompt_version
                    if lifecycle["decision"] == "accepted":
                        lifecycle["status"] = "applied"
        values = list(grouped.values())
        if status:
            values = [item for item in values if item["status"] == status or item["decision"] == status]
        return sorted(values, key=lambda item: str(item.get("recorded_at", "")), reverse=True)

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
            count = 0
            for run in pipeline_runs:
                # Older records can predate finished_at. A terminal status is
                # authoritative in that case and must never inflate the live
                # active-evaluation graph.
                if run.status in {"succeeded", "failed", "cancelled"} and run.finished_at is None:
                    continue
                if run.created_at > timestamp:
                    continue
                if run.finished_at is None or run.finished_at > timestamp:
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
            response = run.supervisor_response or {"improvements": [], "reported_issues": []}
            improvements = response["improvements"]
            item["proposed_improvements"] = len(improvements)
            item["approved_improvements"] = len(
                [item for item in improvements if item.get("status") == "adopted"]
            )
            item["reported_issues"] = len(response["reported_issues"])
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
        temporary = self._path(run.id).with_suffix(".tmp")
        temporary.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self._path(run.id))

    def _load(self, run_id: str) -> Run:
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
        repeat_interval_minutes: int = 0,
        approval_score: int | None = None,
        repository: str | None = None,
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
            repeat_interval_minutes=max(0, repeat_interval_minutes),
            approval_score=approval_score,
            status="awaiting_approval" if needs_approval else "queued",
            created_at=now(),
            updated_at=now(),
            approval_reason="변경 적용 또는 고위험 단계가 포함되어 있습니다." if needs_approval else None,
        )
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

    def application_settings(self) -> dict[str, str]:
        """Settings for operating this console, separate from build assets."""
        if not SETTINGS.exists():
            return {
                "manager_prompt_template": DEFAULT_OPERATIONAL_MANAGER_PROMPT,
                "chat_model_profile_name": "",
            }
        stored = json.loads(SETTINGS.read_text(encoding="utf-8"))
        values = stored.get("application_settings", {}) if isinstance(stored, dict) else {}
        if not isinstance(values, dict):
            return {
                "manager_prompt_template": DEFAULT_OPERATIONAL_MANAGER_PROMPT,
                "chat_model_profile_name": "",
            }
        prompt = str(values.get("manager_prompt_template", "")).strip()
        if MANAGER_PROMPT_SLOT not in prompt:
            prompt = f"{prompt}\n\n{MANAGER_PROMPT_SLOT}".strip()
        return {
            "manager_prompt_template": prompt or DEFAULT_OPERATIONAL_MANAGER_PROMPT,
            "chat_model_profile_name": str(values.get("chat_model_profile_name", "")).strip(),
        }

    def save_application_settings(self, values: dict[str, str]) -> dict[str, str]:
        chat_profile_name = str(values.get("chat_model_profile_name", "")).strip()
        if chat_profile_name and not any(
            item["profile_name"] == chat_profile_name for item in self.profiles()
        ):
            raise ValueError("AI model profile does not exist")
        stored = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
        document = stored if isinstance(stored, dict) else {}
        document["application_settings"] = {
            "manager_prompt_template": str(values.get("manager_prompt_template", "")).strip(),
            "chat_model_profile_name": chat_profile_name,
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
        profile = dict(self._default_settings())
        profile.update(stored)
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
            selected = next(
                (
                    item
                    for item in self.target_test_case_sets()
                    if item.get("id") == build.get("test_case_set_id")
                ),
                None,
            )
            resources["test_cases"] = selected.get("cases", []) if selected else build.get("test_cases", [])
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
            loop_steps = [step for step in steps if step.phase in {"setup", "run", "eval", "teardown"}]
            finalize = [step for step in steps if step.phase == "finalize"]
            for step in init:
                self._execute_step(run_id, step, 0, resources)
                if self._load(run_id).status in {"failed", "cancelled"}:
                    break
            for loop_index in range(1, run.loop_limit + 1):
                if self._load(run_id).status in {"failed", "cancelled"}:
                    break
                for step in loop_steps:
                    self._execute_step(run_id, step, loop_index, resources)
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
                    for _ in range(run.repeat_interval_minutes * 60):
                        if self._load(run_id).status != "running":
                            break
                        time.sleep(1)
            for step in finalize:
                if self._load(run_id).status != "cancelled":
                    self._execute_step(run_id, step, run.loop_limit + 1, resources)
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
            if not isinstance(evaluation, dict) or set(evaluation) != {"score", "approval", "summary"}:
                raise ValueError("supervisor evaluation must contain score, approval, and summary")
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
            if item.get("phase") in {"run", "eval"} and item.get("loop_index") == iteration
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
        self, run_id: str, step, loop_index: int = 1, resources: dict[str, Any] | None = None
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
            if run.status == "cancelled":
                return
            run.current_step, run.current_phase, run.updated_at = step.id, step.phase, now()
            self._save(run)
            directory = (ROOT / step.working_directory).resolve()
            is_approved = any(
                directory == root or root in directory.parents for root in ALLOWED_WORKSPACE_ROOTS
            )
            if not directory.is_dir() or not is_approved:
                self._fail(run, step.id, "working_directory is outside an approved workspace or missing")
                return
            started = now()
            try:
                self._wait_for_tool_interval(step.id, step.minimum_interval_seconds)
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                environment = os.environ.copy()
                environment["PYTHONPATH"] = str(ROOT / "backend") + (
                    os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
                )
                environment["ORBIT_TARGET_REPOSITORY"] = run.repository or step.working_directory
                environment["ORBIT_APP_DATA"] = str(APP_DATA)
                environment["ORBIT_EXECUTION_MODE"] = run.execution_mode
                environment["ORBIT_LOOP_INDEX"] = str(loop_index)
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
                with self._lock:
                    self._processes[run_id] = process
                run = self._load(run_id)
                run.pid, run.last_pid, run.updated_at = process.pid, process.pid, now()
                self._save(run)
                span.set_attribute("process.pid", process.pid)
                output, _ = process.communicate(timeout=step.timeout_seconds)
                structured_result: dict[str, Any] | None = None
                visible_lines = []
                for line in output.splitlines():
                    if line.startswith("__ORBIT_RESULT__"):
                        try:
                            emitted = json.loads(line.removeprefix("__ORBIT_RESULT__"))
                            if not isinstance(emitted, dict):
                                raise ValueError("structured runner result must be an object")
                            structured_result = {**(structured_result or {}), **emitted}
                        except json.JSONDecodeError:
                            visible_lines.append(line)
                    else:
                        visible_lines.append(line)
                result: dict[str, Any] = {
                    "step_id": step.id,
                    "phase": step.phase,
                    "loop_index": loop_index,
                    "name": step.name,
                    "command": step.command,
                    "working_directory": str(directory),
                    "started_at": started,
                    "ended_at": now(),
                    "exit_code": process.returncode,
                    "output": "\n".join(visible_lines)[-12_000:],
                }
                if structured_result is not None:
                    result["result"] = structured_result
                run = self._load(run_id)
                run.step_results.append(result)
                run.pid, run.updated_at = None, now()
                self._save(run)
                span.add_event("process.completed", {"process.exit_code": process.returncode})
                if process.returncode and step.on_failure == "stop":
                    self._fail(run, step.id, f"exit code {process.returncode}")
                    return
            except subprocess.TimeoutExpired:
                process.kill()
                span.add_event("process.timeout", {"timeout.seconds": step.timeout_seconds})
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
                repeat_interval_minutes=0
                if execution_mode == "test"
                else int(build.get("repeat_interval_minutes", 0)),
                approval_score=int(build.get("approval_score", 0)),
                repository=build.get("repository"),
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
