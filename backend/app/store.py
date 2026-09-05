from __future__ import annotations

import base64
import json
import os
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
WORKFLOWS = APP_DATA / "workflows"
CONFIG = APP_DATA / "config"
TARGET_TEST_CASE_SETS = CONFIG / "target-ai-test-case-sets.yaml"
CYCLE_INTERVENTIONS = CONFIG / "cycle-interventions.yaml"
DEFAULT_OPERATIONAL_MANAGER_PROMPT = """You are an approval-first operations manager for recurring AI evaluations.
Use only the supplied repository context and task instruction. Preserve the
task safety boundary, collect observable evidence, and never claim success
without the stated acceptance evidence. Escalate required approvals and
stop immediately when an emergency stop is requested.
Your final response must be exactly one JSON object:
{
  \"evaluation\": {\"score\":\"number from 0 to 10\",\"approval\":\"approved|rejected|pending\",\"summary\":\"string\"},
  \"improvements\": [{\"title\":\"string\",\"status\":\"proposed|adopted|rejected\",\"rationale\":\"string\",\"acceptanceEvidence\":\"string\"}],
  \"reported_issues\": [{\"title\":\"string\",\"severity\":\"low|medium|high|critical\",\"evidence\":\"string\",\"reproduction\":\"string\",\"status\":\"open|acknowledged|resolved\"}]
}
Always include both keys, using empty arrays when there are no items."""
DATA = APP_DATA / "data"
RUNS = DATA / "runs"
TELEMETRY = DATA / "telemetry.jsonl"
SETTINGS = DATA / "settings.json"
TOOL_TIMES = DATA / "tool-times.json"
RUNNERS = APP_DATA / "runners"
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
            run.step_results.append({"step_id": "orbit-restart", "error": "OpenOrbit restarted before this local pipeline completed.", "ended_at": now()})
            temporary = path.with_suffix(".tmp")
            temporary.write_text(run.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(path)

    @staticmethod
    def _initialize_application_data() -> None:
        """Create empty, environment-local state; never seed operational assets from Git."""
        for destination in (CONFIG, WORKFLOWS, DATA):
            destination.mkdir(parents=True, exist_ok=True)
        stored = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
        document = stored if isinstance(stored, dict) else {}
        application = document.get("application_settings") if isinstance(document.get("application_settings"), dict) else {}
        if not str(application.get("manager_prompt_template", "")).strip():
            document["application_settings"] = {**application, "manager_prompt_template": DEFAULT_OPERATIONAL_MANAGER_PROMPT}
            SETTINGS.write_text(json.dumps(document, indent=2), encoding="utf-8")

    def workflows(self) -> list[Workflow]:
        values = []
        for path in sorted(WORKFLOWS.glob("*.yaml")):
            values.append(Workflow.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))))
        return values

    def _workflow_path(self, workflow_id: str) -> Path:
        for path in sorted(WORKFLOWS.glob("*.yaml")):
            if Workflow.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).id == workflow_id:
                return path
        raise KeyError(workflow_id)

    @staticmethod
    def runner_templates() -> list[dict[str, str]]:
        return [
            {"id": "playwright-browser-journey", "name": "Browser journey evaluator", "description": "Checks fixed browser journeys with Playwright, collecting screenshots and observable page evidence.", "source": '''from orbit_runner_sdk import runner

@runner.phase("init")
def init(ctx): ctx.log("Validating the bounded Playwright browser journey")
@runner.phase("setup")
def setup(ctx): ctx.log(f"Preparing {len(ctx.test_cases)} fixed browser test case(s)")
@runner.phase("run")
def run(ctx):
    evidence = ctx.playwright_journey()
    if any(not item["passed"] for item in evidence["results"]): raise SystemExit("Browser journey case failed")
@runner.phase("eval")
def evaluate(ctx): ctx.log("Browser evidence is attached to this run")
@runner.phase("teardown")
def teardown(ctx): ctx.log("Browser context closed")
@runner.phase("finalize")
def finalize(ctx): ctx.log("Browser journey evaluation finalized")

if __name__ == "__main__": runner.main()
'''},
            {"id": "scheduled-persona-cycle", "name": "Scheduled persona cycle", "description": "Adapts a persona processor that exposes status, catalog, and one-cycle commands. OpenOrbit owns every repeat, stop, log, and supervisor decision.", "source": '''import json\nimport os\nimport sys\nfrom pathlib import Path\n\nfrom orbit_runner_sdk import runner\n\n# Set ORBIT_PERSONA_ADAPTER_ROOT to the processor repository. It remains\n# separate from PROJECT_ROOT, so the evaluated product never hosts the scheduler.\ndef adapter_root():\n    configured = os.environ.get("ORBIT_PERSONA_ADAPTER_ROOT", "").strip()\n    if not configured:\n        raise SystemExit("Set ORBIT_PERSONA_ADAPTER_ROOT to the persona processor repository")\n    root = Path(configured).expanduser().resolve()\n    if not root.is_dir():\n        raise SystemExit(f"Persona processor directory does not exist: {root}")\n    return root\n\ndef processor_command():\n    root = adapter_root()\n    configured = os.environ.get("ORBIT_PERSONA_PYTHON", "").strip()\n    if configured:\n        python = configured\n    else:\n        venv = root / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")\n        python = str(venv if venv.exists() else sys.executable)\n    return [python, "-m", "insighta_user_simulator.cli"]\n\ndef processor(ctx, *args, timeout=300):\n    return ctx.exec([*processor_command(), *args], cwd=adapter_root(), timeout=timeout)\n\ndef json_output(output):\n    start = output.find("[")\n    if start < 0:\n        start = output.find("{")\n    if start < 0:\n        raise ValueError("Persona processor did not return JSON evidence")\n    return json.loads(output[start:])\n\n@runner.phase("init")\ndef init(ctx):\n    ctx.log("Validated a bounded persona processor; OpenOrbit will not start its daemon")\n    ctx.emit_result({"persona_processor": {"root": str(adapter_root()), "scheduler": "openorbit"}})\n    processor(ctx, "status")\n\n@runner.phase("setup")\ndef setup(ctx): processor(ctx, "catalog")\n\n@runner.phase("run")\ndef run(ctx):\n    ctx.log(f"Running bounded persona cycle for Orbit iteration {ctx.loop_index}")\n    processed = json_output(processor(ctx, "run-once", *(["--dry-run"] if ctx.mode == "test" else []), timeout=86400))\n    ctx.emit_result({"persona_cycle": {"iteration": ctx.loop_index, "processed_personas": processed}})\n\n@runner.phase("eval")\ndef evaluate(ctx): ctx.log("Persona-cycle evidence is ready for the OpenOrbit supervisor")\n@runner.phase("teardown")\ndef teardown(ctx): ctx.log("Completed this bounded persona cycle")\n@runner.phase("finalize")\ndef finalize(ctx): ctx.log("Finalized the scheduled persona evaluation")\n\nif __name__ == "__main__": runner.main()\n'''},
            {"id": "bounded-improvement-cycle", "name": "Bounded improvement cycle", "description": "Runs one candidate-change and validation gate per Orbit iteration. The target command must finish; OpenOrbit supplies the schedule and approval boundary.", "source": '''import json\nimport os\nimport shlex\n\nfrom orbit_runner_sdk import ORBIT_PROJECT_PATH, runner\n\n# Configure a target-specific one-cycle command in ORBIT_CYCLE_COMMAND. It can\n# be JSON (exact arguments) or a shell-like command string. The command must\n# terminate after one candidate-and-validation cycle, never start a daemon.\nDEFAULT_CYCLE_COMMAND = ["python", "scripts/operations/run_paired_improvement_cycle.py", "--once"]\n\ndef cycle_command():\n    configured = os.environ.get("ORBIT_CYCLE_COMMAND", "").strip()\n    if not configured:\n        return DEFAULT_CYCLE_COMMAND\n    if configured.startswith("["):\n        values = json.loads(configured)\n        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):\n            raise ValueError("ORBIT_CYCLE_COMMAND JSON must be an array of strings")\n        return values\n    return shlex.split(configured)\n\ndef evidence_path():\n    return ORBIT_PROJECT_PATH(".build", "paired-improvement-cycle", "scorecards.jsonl")\n\n@runner.phase("init")\ndef init(ctx):\n    command = cycle_command()\n    ctx.log(f"Target: {ORBIT_PROJECT_PATH()}")\n    ctx.log(f"Configured bounded command: {' '.join(command)}")\n    ctx.emit_result({"improvement_cycle": {"command": command, "scheduler": "openorbit"}})\n\n@runner.phase("setup")\ndef setup(ctx): ctx.log("Prepared one approval-gated candidate and validation cycle")\n\n@runner.phase("run")\ndef run(ctx): ctx.exec(cycle_command(), cwd=ORBIT_PROJECT_PATH(), timeout=3600)\n\n@runner.phase("eval")\ndef evaluate(ctx):\n    path = evidence_path()\n    if path.exists():\n        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]\n        latest = json.loads(lines[-1]) if lines else {}\n        ctx.emit_result({"improvement_cycle": {"evidence_path": str(path), "latest_scorecard": latest}})\n    else:\n        ctx.log("No scorecard file found; configure the target command or emit its evidence explicitly")\n\n@runner.phase("teardown")\ndef teardown(ctx): ctx.log("Completed the bounded improvement cycle")\n@runner.phase("finalize")\ndef finalize(ctx): ctx.log("Finalized the improvement evaluation")\n\nif __name__ == "__main__": runner.main()\n'''}]

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
        return self._write_runner(runner_id, {**existing, **values})

    def _write_runner(self, runner_id: str, values: dict[str, str]) -> dict[str, str]:
        source = str(values["source"])
        compile(source, f"{runner_id}.py", "exec")
        asset = {"id": runner_id, "name": str(values["name"]).strip(), "description": str(values["description"]).strip(), "template_id": str(values.get("template_id", "custom"))}
        if not asset["name"] or not asset["description"]:
            raise ValueError("runner requires a name and description")
        source_path, metadata_path = RUNNERS / f"{runner_id}.py", RUNNERS / f"{runner_id}.json"
        source_path.write_text(source, encoding="utf-8")
        metadata_path.write_text(json.dumps(asset, indent=2), encoding="utf-8")
        return {**asset, "source": source}

    def open_runner_in_vscode(self, runner_id: str) -> dict[str, str]:
        self._runner(runner_id)
        executable = shutil.which("code")
        if executable is None:
            raise ValueError("VS Code command-line launcher 'code' is not available")
        subprocess.Popen([executable, "--reuse-window", str(RUNNERS / f"{runner_id}.py")])
        return {"status": "opened"}

    def delete_runner(self, runner_id: str) -> None:
        self._runner(runner_id)
        if any(workflow.runner_id == runner_id for workflow in self.workflows()):
            raise ValueError("runner is used by a workflow")
        (RUNNERS / f"{runner_id}.py").unlink(missing_ok=True)
        (RUNNERS / f"{runner_id}.json").unlink(missing_ok=True)

    def evaluation_builds(self) -> list[dict[str, Any]]:
        path = CONFIG / "evaluation-builds.yaml"
        builds = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []
        fallback = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat() if path.exists() else None
        runs = self.runs()
        for build in builds:
            build.update(self._repository_metadata(str(build.get("repository", ""))))
            build.setdefault("created_at", fallback)
            dates = [run.created_at for run in runs if run.evaluation_build_id == build["id"]]
            build["last_run_at"] = max(dates).isoformat() if dates else None
        return builds

    @staticmethod
    def _repository_metadata(value: str) -> dict[str, str | bool]:
        path = Path(value).expanduser()
        if value.startswith("remote://"):
            return {"repository_name": value.removeprefix("remote://"), "repository_is_git": False, "repository_error": "A remote invocation is not a local Git working tree."}
        if not path.is_dir():
            return {"repository_name": path.name or value, "repository_is_git": False, "repository_error": "Repository folder does not exist."}
        probe = subprocess.run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return {"repository_name": path.name, "repository_is_git": False, "repository_error": "This folder is not a Git working tree."}
        remote = subprocess.run(["git", "-C", str(path), "config", "--get", "remote.origin.url"], capture_output=True, text=True).stdout.strip()
        name = remote.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1].rsplit(":", 1)[-1] if remote else path.name
        return {"repository_name": name, "repository_is_git": True, "repository_error": ""}

    @staticmethod
    def _executor_from_values(values: dict[str, Any]) -> dict[str, Any]:
        if values.get("executor_type") == "local":
            return {"type": "local"}
        headers = values.get("remote_headers", {})
        if not isinstance(headers, dict):
            raise ValueError("remote HTTP headers must be an object")
        normalized_headers = {str(name).strip(): str(value) for name, value in headers.items() if str(name).strip()}
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

    def prompt_templates(self) -> list[dict[str, Any]]:
        path = CONFIG / "prompt-templates.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []

    def target_test_case_sets(self) -> list[dict[str, Any]]:
        return yaml.safe_load(TARGET_TEST_CASE_SETS.read_text(encoding="utf-8")) if TARGET_TEST_CASE_SETS.exists() else []

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
                raise ValueError("each target-AI test case requires an ID, name, prompt, and acceptance evidence")
            path = str(item.get("path", "/")).strip() or "/"
            if not path.startswith("/"):
                raise ValueError("browser test case path must start with '/'")
            normalized.append({"id": case_id, "name": case_name, "prompt": prompt, "acceptance": acceptance, "path": path, "expected_text": str(item.get("expected_text", "")).strip()})
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
        temporary.write_text(yaml.safe_dump([item for item in sets if item.get("id") != set_id], allow_unicode=True, sort_keys=False), encoding="utf-8")
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
        temporary.write_text(yaml.safe_dump([item for item in templates if item.get("id") != template_id], allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(CONFIG / "prompt-templates.yaml")

    def _write_prompt_template(self, templates: list[dict[str, Any]], template_id: str, values: dict[str, Any]) -> dict[str, Any]:
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
        """Create the immutable three-part prompt captured by every evaluation.

        The manager template is shared and versioned, while the task instruction
        and fixed test cases belong to an individual evaluation build.  Keeping
        the resolved result on the Run makes an operator able to audit exactly
        what the supervisor/target saw even after a build is edited later.
        """
        template_id = build.get("manager_template_id", "manager-default-v1")
        template = next((item for item in self.prompt_templates() if item.get("id") == template_id), None)
        if template is None:
            raise ValueError(f"manager prompt template does not exist: {template_id}")
        repository_value = str(build["repository"])
        remote = build.get("executor", {}).get("type") == "remote-http"
        repository = Path(repository_value).resolve()
        source = (repository / build["prompt_bundle"]).resolve()
        if remote:
            source_label = build.get("prompt_bundle") or "remote contract"
            source_content = "This deployed target receives the fixed test cases below through its HTTP contract."
        elif not source.is_file() or repository not in source.parents:
            raise ValueError("prompt must be a readable file inside the evaluation repository")
        else:
            source_label = str(source.relative_to(repository))
            source_content = source.read_text(encoding="utf-8")[:50_000]
        selected_set = next((item for item in self.target_test_case_sets() if item.get("id") == build.get("test_case_set_id")), None)
        cases = selected_set.get("cases", []) if selected_set else build.get("test_cases") or []
        case_text = "\n\n".join(
            "## Fixed target-AI test case: {name}\n{prompt}\n\nAcceptance evidence:\n{acceptance}".format(
                name=item.get("name") or item.get("id") or "unnamed",
                prompt=item.get("prompt", ""),
                acceptance=item.get("acceptance", ""),
            )
            for item in cases
        ) or "## Fixed target-AI test cases\nNo fixed test cases were configured."
        assembled = "\n\n".join((
            f"# Manager template: {template['name']} (v{template.get('version', 1)})\n{template['content']}",
            f"# Repository context\nRepository: {repository_value}\nPurpose: {build.get('purpose', '')}\nEvaluation criteria: {build.get('criteria', '')}",
            f"# Task instruction\n{self.workflow(str(build['workflow_id'])).description}",
            f"# Prompt source: {source_label}\n{source_content}",
            case_text,
        ))
        return source_label if remote else str(source), assembled[:100_000]

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

    def clone_workflow(self, values: dict[str, Any]) -> Workflow:
        workflow_id = values["id"]
        if any(workflow.id == workflow_id for workflow in self.workflows()):
            raise ValueError("같은 ID의 workflow가 이미 있습니다.")
        template = self.workflow(values["template_workflow_id"])
        workflow = template.model_copy(deep=True)
        workflow.id = workflow_id
        workflow.name = values["name"]
        workflow.description = values["description"]
        workflow.runner_id = values.get("runner_id") or None
        if workflow.runner_id:
            self._runner(workflow.runner_id)
        workflow.enabled = True
        if values.get("workflow_yaml") is not None:
            workflow.steps = self._workflow_steps_from_yaml(values["workflow_yaml"])
            workflow.test_steps = deepcopy(workflow.steps)
        elif values.get("steps") is not None:
            workflow.steps = [Step.model_validate(step) for step in values["steps"]]
            workflow.test_steps = deepcopy(workflow.steps)
        if not workflow.lifecycle_is_complete() or not workflow.lifecycle_is_complete("test"):
            raise ValueError("template workflow must define the complete lifecycle")
        temporary = WORKFLOWS / f"{workflow_id}.tmp"
        destination = WORKFLOWS / f"{workflow_id}.yaml"
        serialized = yaml.safe_dump(workflow.model_dump(mode="json"), allow_unicode=True, sort_keys=False)
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(destination)
        return workflow

    def update_workflow(self, workflow_id: str, values: dict[str, Any]) -> Workflow:
        workflow = self.workflow(workflow_id)
        workflow.name = values["name"]
        workflow.description = values["description"]
        workflow.runner_id = values.get("runner_id") or None
        if workflow.runner_id:
            self._runner(workflow.runner_id)
        if values.get("workflow_yaml") is not None:
            workflow.steps = self._workflow_steps_from_yaml(values["workflow_yaml"])
            workflow.test_steps = deepcopy(workflow.steps)
        elif values.get("steps") is not None:
            workflow.steps = [Step.model_validate(step) for step in values["steps"]]
            workflow.test_steps = deepcopy(workflow.steps)
        if not workflow.lifecycle_is_complete() or not workflow.lifecycle_is_complete("test"):
            raise ValueError("workflow must define the complete lifecycle")
        destination = self._workflow_path(workflow_id)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(yaml.safe_dump(workflow.model_dump(mode="json"), allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(destination)
        return workflow

    def delete_workflow(self, workflow_id: str) -> None:
        self.workflow(workflow_id)
        if any(build.get("workflow_id") == workflow_id for build in self.evaluation_builds()):
            raise ValueError("workflow is used by an evaluation build")
        self._workflow_path(workflow_id).unlink(missing_ok=True)

    @staticmethod
    def _workflow_steps_from_yaml(source: str) -> list[Step]:
        try:
            document = yaml.safe_load(source)
        except yaml.YAMLError as error:
            raise ValueError(f"pipeline YAML is invalid: {error}") from error
        if not isinstance(document, dict):
            raise ValueError("pipeline YAML must be a mapping of lifecycle stages")
        steps: list[Step] = []
        phases = ("init", "setup", "run", "eval", "teardown", "finalize")
        for phase in phases:
            entries = document.get(phase, [])
            if not isinstance(entries, list):
                raise ValueError(f"pipeline YAML stage '{phase}' must be a list")
            for index, entry in enumerate(entries, start=1):
                if not isinstance(entry, dict):
                    raise ValueError(f"pipeline YAML stage '{phase}' entries must be objects")
                values = dict(entry)
                values.update({"id": str(values.get("id") or f"{phase}-{index}"), "phase": phase, "working_directory": str(APP_DATA)})
                steps.append(Step.model_validate(values))
        return steps

    def create_evaluation_build(self, values: dict[str, Any]) -> dict[str, Any]:
        build_id = values["id"]
        if any(build["id"] == build_id for build in self.evaluation_builds()):
            raise ValueError("같은 ID의 평가 빌드가 이미 있습니다.")
        workflow = self.workflow(values["workflow_id"])
        executor = self._executor_from_values(values)
        repository_value = str(values["repository"])
        repository = Path(repository_value).expanduser().resolve()
        approved = any(repository == root or root in repository.parents for root in ALLOWED_WORKSPACE_ROOTS)
        if executor["type"] != "remote-http" and (not repository.is_dir() or not approved):
            raise ValueError("repository must be an existing approved workspace")
        if executor["type"] == "remote-http" and not repository_value.startswith("remote://") and (not repository.is_dir() or not approved):
            raise ValueError("remote HTTP builds require an approved repository or a remote:// repository label")
        if "manager_template_id" in values and not any(item.get("id") == values.get("manager_template_id") for item in self.prompt_templates()):
            raise ValueError("manager prompt template does not exist")
        if "model_profile_name" in values and not any(item["profile_name"] == values.get("model_profile_name") for item in self.profiles()):
            raise ValueError("AI model profile does not exist")
        if not any(item.get("id") == values.get("test_case_set_id") for item in self.target_test_case_sets()):
            raise ValueError("target-AI test case set does not exist")
        build = {
            "id": build_id,
            "name": values["name"],
            "enabled": values["enabled"],
            "workflow_id": workflow.id,
            "repository": repository_value if executor["type"] == "remote-http" and repository_value.startswith("remote://") else str(repository),
            "purpose": values["purpose"],
            "criteria": values["criteria"],
            "prompt_bundle": values["prompt_bundle"],
            "manager_template_id": values.get("manager_template_id", "manager-default-v1"),
            "model_profile_name": values.get("model_profile_name", "Default"),
            "task_instruction": values.get("task_instruction", ""),
            "test_case_set_id": values["test_case_set_id"],
            "browser_base_url": str(values.get("browser_base_url", "")).strip(),
            "browser_executable_path": str(values.get("browser_executable_path", "")).strip(),
            "browser_library_path": str(values.get("browser_library_path", "")).strip(),
            "timezone": values["timezone"],
            "repeat_interval_minutes": values["repeat_interval_minutes"],
            "run_limit": values["run_limit"],
            "approval_score": values["approval_score"],
            "executor": executor,
        }
        builds = self.evaluation_builds()
        builds.append(build)
        temporary = (CONFIG / "evaluation-builds.tmp")
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
        workflow = self.workflow(values["workflow_id"])
        executor = self._executor_from_values(values)
        repository_value = str(values["repository"])
        repository = Path(repository_value).expanduser().resolve()
        approved = any(repository == root or root in repository.parents for root in ALLOWED_WORKSPACE_ROOTS)
        if executor["type"] != "remote-http" and (not repository.is_dir() or not approved):
            raise ValueError("repository must be an existing approved workspace")
        if executor["type"] == "remote-http" and not repository_value.startswith("remote://") and (not repository.is_dir() or not approved):
            raise ValueError("remote HTTP builds require an approved repository or a remote:// repository label")
        if "manager_template_id" in values and not any(item.get("id") == values.get("manager_template_id") for item in self.prompt_templates()):
            raise ValueError("manager prompt template does not exist")
        if "model_profile_name" in values and not any(item["profile_name"] == values.get("model_profile_name") for item in self.profiles()):
            raise ValueError("AI model profile does not exist")
        if not any(item.get("id") == values.get("test_case_set_id") for item in self.target_test_case_sets()):
            raise ValueError("target-AI test case set does not exist")
        build = {
            "id": build_id,
            "name": values["name"],
            "enabled": values["enabled"],
            "workflow_id": workflow.id,
            "repository": repository_value if executor["type"] == "remote-http" and repository_value.startswith("remote://") else str(repository),
            "purpose": values["purpose"],
            "criteria": values["criteria"],
            "prompt_bundle": values["prompt_bundle"],
            "manager_template_id": values.get("manager_template_id", "manager-default-v1"),
            "model_profile_name": values.get("model_profile_name", "Default"),
            "task_instruction": values.get("task_instruction", ""),
            "test_case_set_id": values["test_case_set_id"],
            "browser_base_url": str(values.get("browser_base_url", "")).strip(),
            "browser_executable_path": str(values.get("browser_executable_path", "")).strip(),
            "browser_library_path": str(values.get("browser_library_path", "")).strip(),
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
        return yaml.safe_load(CYCLE_INTERVENTIONS.read_text(encoding="utf-8")) if CYCLE_INTERVENTIONS.exists() else []

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
        missing_parents = {str(span["parentSpanId"]) for span in spans if span.get("parentSpanId") and span["parentSpanId"] not in known_span_ids}
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
                message = next((str(event.get("attributes", {}).get("exception.message", "")) for event in events if event.get("attributes", {}).get("exception.message")), "")
                entries.append({"time": str(record.get("exportedAt", "")), "name": str(span.get("name", "orbit")), "status": str(span.get("status", "UNSET")), "message": message})
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
                run.model_dump(mode="json") for run in runs
                if run.execution_type == "pipeline" and run.execution_mode == "run"
                and run.evaluation_build_id in build_ids
                and run.status in {"queued", "running", "awaiting_approval"}
            ],
            "recent_runs": recent_runs,
            "improvements": self.improvements(),
            "metrics": {
                "evaluation_builds": len(builds),
                "completed_evaluations": len([
                    run for run in runs
                    if run.evaluation_build_id in build_ids
                    and run.status in {"succeeded", "failed", "cancelled"}
                ]),
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

        def parse_timestamp(value: object) -> datetime | None:
            if not isinstance(value, str):
                return None
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None

        pipeline_runs = [
            run for run in self.runs()
            if run.execution_type == "pipeline" and run.evaluation_build_id
        ]
        for run in pipeline_runs:
            build_id = str(run.evaluation_build_id)
            name = run.evaluation_build_name or build_id
            feedback = feedback_by_build.setdefault(build_id, {"build_id": build_id, "name": name, "feedback_count": 0})
            trend = trends_by_build.setdefault(build_id, {"build_id": build_id, "name": name, "points": []})
            status_counts = feedback_status_by_build.setdefault(build_id, {"build_id": build_id, "name": name, "proposed": 0, "adopted": 0, "rejected": 0})
            for record in run.supervisor_results:
                recorded_at = parse_timestamp(record.get("recorded_at"))
                if recorded_at is None or recorded_at < start or recorded_at > end:
                    continue
                response = record.get("response") if isinstance(record.get("response"), dict) else {}
                improvements = response.get("improvements", []) if isinstance(response.get("improvements"), list) else []
                issues = response.get("reported_issues", []) if isinstance(response.get("reported_issues"), list) else []
                feedback["feedback_count"] += len(improvements) + len(issues)
                for improvement in improvements:
                    if isinstance(improvement, dict) and improvement.get("status") in {"proposed", "adopted", "rejected"}:
                        status_counts[str(improvement["status"])] += 1
                for issue in issues:
                    if not isinstance(issue, dict) or issue.get("severity") not in {"low", "medium", "high", "critical"}:
                        continue
                    issue_time = parse_timestamp(issue.get("reported_at")) or recorded_at
                    bucket = min(bucket_count, max(0, int((issue_time - start) / interval)))
                    issue_severity[bucket][str(issue["severity"])] += 1
                evaluation = response.get("evaluation") if isinstance(response.get("evaluation"), dict) else {}
                score = evaluation.get("score") if isinstance(evaluation.get("score"), (int, float)) else None
                trend["points"].append({
                    "run_id": run.id,
                    "iteration": record.get("iteration", 0),
                    "recorded_at": recorded_at.isoformat(),
                    "accepted_count": len([item for item in improvements if isinstance(item, dict) and item.get("status") == "adopted"]),
                    "feedback_count": len(improvements) + len(issues),
                    "score": score,
                })

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
            item = health_by_build.setdefault(build_id, {"build_id": build_id, "name": run.evaluation_build_name or build_id, "succeeded": 0, "failed": 0, "cancelled": 0, "running": 0})
            item[run.status if run.status in item else "running"] += 1
        for trend in trends_by_build.values():
            trend["points"].sort(key=lambda point: point["recorded_at"])
        return {
            "window_hours": hours,
            "feedback_by_build": sorted(feedback_by_build.values(), key=lambda item: item["feedback_count"], reverse=True),
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
        for run in sorted(runs if runs is not None else self.runs(), key=lambda item: item.created_at, reverse=True):
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
            item["approved_improvements"] = len([item for item in improvements if item.get("status") == "adopted"])
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

    def create_run(
        self,
        workflow_id: str,
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
        workflow = self.workflow(workflow_id)
        if not workflow.lifecycle_is_complete(execution_mode):
            raise ValueError("Workflow는 init, setup, run, eval, teardown 단계를 순서대로 정의해야 합니다.")
        if not workflow.enabled:
            raise ValueError("이 workflow는 아직 활성화되지 않았습니다.")
        needs_approval = execution_mode == "run" and any(step.approval == "required" for step in workflow.steps)
        run = Run(
            id=uuid.uuid4().hex[:12],
            workflow_id=workflow.id,
            workflow_name=workflow.name,
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
            return {"manager_prompt_template": DEFAULT_OPERATIONAL_MANAGER_PROMPT}
        stored = json.loads(SETTINGS.read_text(encoding="utf-8"))
        values = stored.get("application_settings", {}) if isinstance(stored, dict) else {}
        if not isinstance(values, dict):
            return {"manager_prompt_template": DEFAULT_OPERATIONAL_MANAGER_PROMPT}
        prompt = str(values.get("manager_prompt_template", "")).strip()
        return {"manager_prompt_template": prompt or DEFAULT_OPERATIONAL_MANAGER_PROMPT}

    def save_application_settings(self, values: dict[str, str]) -> dict[str, str]:
        stored = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
        document = stored if isinstance(stored, dict) else {}
        document["application_settings"] = {"manager_prompt_template": str(values.get("manager_prompt_template", "")).strip()}
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
        workflow = self.workflow(run.workflow_id).model_copy(deep=True)
        resources: dict[str, Any] = {"workflow": workflow.model_dump(mode="json"), "evaluation_build": {}, "test_cases": []}
        if run.evaluation_build_id:
            build = self.evaluation_build(run.evaluation_build_id)
            resources["evaluation_build"] = {key: value for key, value in build.items() if key not in {"executor"}}
            selected = next((item for item in self.target_test_case_sets() if item.get("id") == build.get("test_case_set_id")), None)
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
                if loop_index < run.loop_limit and run.repeat_interval_minutes and run.execution_mode == "run" and self._load(run_id).status == "running":
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
                run.current_step, run.current_phase, run.updated_at, run.finished_at = None, None, now(), now()
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
            cycle = result.get("persona_cycle")
            return isinstance(cycle, dict) and bool(cycle.get("processed_personas"))
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
        if set(result) not in ({"improvements", "reported_issues"}, {"evaluation", "improvements", "reported_issues"}):
            raise ValueError("supervisor JSON contains unsupported result fields")
        if not all(isinstance(result[key], list) and all(isinstance(item, dict) for item in result[key]) for key in ("improvements", "reported_issues")):
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
            if evaluation["approval"] not in {"approved", "rejected", "pending"} or not isinstance(evaluation["summary"], str):
                raise ValueError("supervisor evaluation approval or summary is invalid")
        return result

    def _complete_supervision(self, run_id: str) -> None:
        """Ask the configured manager model and retain its validated JSON per Run.

        A missing profile is observable but never turns a successfully completed
        target pipeline into a failed pipeline.
        """
        run = self._load(run_id)
        iteration = max((int(item.get("loop_index", 0)) for item in run.step_results), default=0)
        configured = next((item for item in self.profiles() if item["profile_name"] == run.supervisor_profile_name), self.settings())
        if not configured.get("model"):
            run.supervisor_status, run.supervisor_error, run.updated_at = "not_configured", "No AI model profile is configured.", now()
            run.supervisor_results.append({"iteration": iteration, "status": "not_configured", "error": run.supervisor_error, "recorded_at": now().isoformat()})
            self._save(run)
            return
        settings = ModelSettings(**{key: value for key, value in configured.items() if key != "profile_name"})
        provider = AzureOpenAIProvider() if settings.provider == "azure-openai" else BedrockProvider()
        cycle_evidence = [
            {
                "phase": item.get("phase"),
                "iteration": item.get("loop_index"),
                "exit_code": item.get("exit_code"),
                "result": item.get("result"),
                "output": str(item.get("output", ""))[-4_000:],
            }
            for item in run.step_results
            if item.get("phase") in {"run", "eval"} and item.get("loop_index") == iteration
        ]
        supervisor_prompt = run.prompt_snapshot or ""
        if cycle_evidence:
            supervisor_prompt += "\n\n# OpenOrbit cycle evidence\n"
            supervisor_prompt += json.dumps(cycle_evidence, ensure_ascii=False, default=str)
        with self.tracer.start_as_current_span(
            "supervisor.evaluate",
            attributes={
                "run.id": run_id,
                "gen_ai.provider.name": settings.provider,
                "gen_ai.request.model": settings.model,
                "orbit.manager.template": (self.evaluation_build(run.evaluation_build_id).get("manager_template_id") if run.evaluation_build_id else ""),
                "orbit.iteration": iteration,
            },
        ) as span:
            try:
                result = self._validated_supervisor_result(provider.complete(settings, supervisor_prompt))
                evaluation = result.get("evaluation")
                if evaluation is not None:
                    threshold = run.approval_score if run.approval_score is not None else int(self.evaluation_build(run.evaluation_build_id).get("approval_score", 0))
                    evaluation["approval"] = "approved" if evaluation["score"] >= threshold else "rejected"
                reported_at = now().isoformat()
                for improvement in result["improvements"]:
                    improvement.setdefault("reported_at", reported_at)
                    improvement.setdefault("effect_score", (result.get("evaluation") or {}).get("score"))
                    improvement.setdefault("attempted", improvement.get("status") in {"adopted", "rejected"})
                for issue in result["reported_issues"]:
                    issue.setdefault("reported_at", reported_at)
                run = self._load(run_id)
                run.supervisor_status, run.supervisor_response, run.supervisor_error, run.updated_at = "completed", result, None, now()
                run.supervisor_results.append({"iteration": iteration, "status": "completed", "prompt": supervisor_prompt, "response": result, "recorded_at": now().isoformat()})
                self._save(run)
                self._review_cycle_improvement(run, iteration, result, settings, provider)
                span.set_attribute("orbit.supervisor.improvements", len(result["improvements"]))
                span.set_attribute("orbit.supervisor.reported_issues", len(result["reported_issues"]))
                span.add_event("supervisor.response.validated")
            except ValueError as error:
                run = self._load(run_id)
                run.supervisor_status, run.supervisor_error, run.updated_at = "invalid_response", str(error), now()
                run.supervisor_results.append({"iteration": iteration, "status": "invalid_response", "prompt": supervisor_prompt, "error": str(error), "recorded_at": now().isoformat()})
                self._save(run)
                span.record_exception(error)
                span.add_event("supervisor.response.invalid", {"reason": str(error)})
            except (RuntimeError, requests.RequestException) as error:
                run = self._load(run_id)
                run.supervisor_status, run.supervisor_error, run.updated_at = "failed", str(error), now()
                run.supervisor_results.append({"iteration": iteration, "status": "failed", "prompt": supervisor_prompt, "error": str(error), "recorded_at": now().isoformat()})
                self._save(run)
                span.record_exception(error)
                span.add_event("supervisor.request.failed", {"reason": str(error)})

    def _review_cycle_improvement(self, run: Run, iteration: int, result: dict[str, Any], settings: ModelSettings, provider: Any) -> None:
        """Let a second AI pass improve the operating cycle, not the target."""
        prompt = """You improve an OpenOrbit evaluation cycle, not the evaluated product.\nReturn exactly JSON: {\"diagnosis\":\"string\",\"interventions\":[{\"target\":\"runner|workflow|test_case_set|manager_prompt|schedule\",\"title\":\"string\",\"rationale\":\"string\",\"proposed_change\":\"string\",\"risk\":\"low|medium|high\",\"validation\":\"string\",\"rollback\":\"string\"}]}.\nOnly propose evidence-backed changes. Do not propose target repository code changes.\n\n""" + json.dumps({"evaluation_build": run.evaluation_build_name, "iteration": iteration, "supervisor_result": result}, ensure_ascii=False)
        try:
            reviewed = json.loads(provider.complete(settings, prompt))
            interventions = reviewed.get("interventions", []) if isinstance(reviewed, dict) else []
            if not isinstance(interventions, list):
                return
            stored = self.cycle_interventions()
            for intervention in interventions:
                if not isinstance(intervention, dict) or not isinstance(intervention.get("title"), str):
                    continue
                stored.append({"id": f"ci-{uuid.uuid4().hex[:10]}", "evaluation_build_id": run.evaluation_build_id, "evaluation_build_name": run.evaluation_build_name, "run_id": run.id, "iteration": iteration, "diagnosis": str(reviewed.get("diagnosis", "")), "status": "proposed", "created_at": now().isoformat(), **intervention})
            self._save_cycle_interventions(stored)
        except (ValueError, RuntimeError, requests.RequestException, json.JSONDecodeError):
            return

    def _execute_step(self, run_id: str, step, loop_index: int = 1, resources: dict[str, Any] | None = None) -> None:  # type: ignore[no-untyped-def]
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
                environment["PYTHONPATH"] = str(ROOT / "backend") + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
                environment["ORBIT_TARGET_REPOSITORY"] = run.repository or step.working_directory
                environment["ORBIT_APP_DATA"] = str(APP_DATA)
                environment["ORBIT_EXECUTION_MODE"] = run.execution_mode
                environment["ORBIT_LOOP_INDEX"] = str(loop_index)
                environment["ORBIT_RUN_ID"] = run_id
                environment["ORBIT_RUNNER_RESOURCES"] = base64.b64encode(json.dumps(resources or {}, ensure_ascii=False).encode("utf-8")).decode("ascii")
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
                            structured_result = json.loads(line.removeprefix("__ORBIT_RESULT__"))
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
        run.status, run.pid, run.updated_at, run.finished_at = "cancelled", None, now(), now()
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
                build["workflow_id"], execution_mode,
                evaluation_build_id=build["id"],
                evaluation_build_name=build["name"],
                supervisor_profile_name=build.get("model_profile_name"),
                prompt_source=prompt_source,
                prompt_snapshot=prompt_snapshot,
                loop_limit=1 if execution_mode == "test" else int(build.get("run_limit", 1)),
                repeat_interval_minutes=0 if execution_mode == "test" else int(build.get("repeat_interval_minutes", 0)),
                approval_score=int(build.get("approval_score", 0)),
                repository=build.get("repository"),
            )
        run = Run(
            id=uuid.uuid4().hex[:12],
            workflow_id=build["workflow_id"],
            workflow_name=build["name"],
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
