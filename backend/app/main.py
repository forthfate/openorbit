from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .docker import preflight_docker
from .providers import AzureOpenAIProvider, BedrockProvider, ModelSettings
from .store import ConsoleStore

app = FastAPI(title="OpenOrbit", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
store = ConsoleStore()
WEB_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def safely(action):
    try:
        return action()
    except KeyError:
        raise HTTPException(404, "대상을 찾을 수 없습니다.")
    except ValueError as error:
        raise HTTPException(409, str(error))


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/workflows")
def workflows():
    return store.workflows()


@app.get("/api/tasks")
def tasks():
    """Expose executable workflows under the operator-facing task name."""
    return store.workflows()


@app.get("/api/runs")
def runs():
    return store.runs()


@app.get("/api/active-evaluations")
def active_evaluations():
    return store.active_evaluations()


@app.get("/api/runs/{run_id}")
def run(run_id: str):
    return safely(lambda: store.run(run_id))


@app.get("/api/runs/{run_id}/telemetry")
def run_telemetry(run_id: str):
    return safely(lambda: store.run_telemetry(run_id))


@app.get("/api/dashboard")
def dashboard():
    return store.dashboard()


@app.get("/api/evaluation-builds")
def evaluation_builds():
    return store.evaluation_builds()


@app.get("/api/prompt-templates")
def prompt_templates():
    return store.prompt_templates()


@app.get("/api/target-test-case-sets")
def target_test_case_sets():
    return store.target_test_case_sets()


class PromptTemplateUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1, le=10000)
    content: str = Field(min_length=1, max_length=100_000)


class PromptTemplateCreate(PromptTemplateUpdate):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")


class TargetTestCaseSetUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    cases: list[dict] = Field(min_length=1, max_length=100)


class TargetTestCaseSetCreate(TargetTestCaseSetUpdate):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")


@app.put("/api/prompt-templates/{template_id}")
def update_prompt_template(template_id: str, values: PromptTemplateUpdate):
    return safely(lambda: store.update_prompt_template(template_id, values.model_dump()))


@app.post("/api/prompt-templates")
def create_prompt_template(values: PromptTemplateCreate):
    return safely(lambda: store.create_prompt_template(values.model_dump()))


@app.post("/api/target-test-case-sets")
def create_target_test_case_set(values: TargetTestCaseSetCreate):
    return safely(lambda: store.create_target_test_case_set(values.model_dump()))


@app.delete("/api/prompt-templates/{template_id}")
def delete_prompt_template(template_id: str):
    return safely(lambda: store.delete_prompt_template(template_id))


@app.delete("/api/target-test-case-sets/{set_id}")
def delete_target_test_case_set(set_id: str):
    return safely(lambda: store.delete_target_test_case_set(set_id))


@app.put("/api/target-test-case-sets/{set_id}")
def update_target_test_case_set(set_id: str, values: TargetTestCaseSetUpdate):
    return safely(lambda: store.update_target_test_case_set(set_id, values.model_dump()))


@app.get("/api/workspaces")
def workspaces(path: str | None = None):
    return safely(lambda: store.workspaces(path))


@app.post("/api/evaluation-builds/{build_id}/runs")
def invoke_evaluation_build(build_id: str):
    return safely(lambda: store.invoke_remote_build(build_id))


@app.post("/api/evaluation-builds/{build_id}/tests")
def test_evaluation_build(build_id: str):
    return safely(lambda: store.test_evaluation_build(build_id))


class EvaluationBuildCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    workflow_id: str
    repository: str = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=500)
    criteria: str = Field(min_length=1, max_length=1_000)
    prompt_bundle: str = Field(min_length=1)
    manager_template_id: str = "manager-default-v1"
    model_profile_name: str = "Default"
    task_instruction: str = ""
    test_case_set_id: str = Field(min_length=1, max_length=64)
    browser_base_url: str = Field(default="", max_length=2_000)
    browser_executable_path: str = Field(default="", max_length=4_000)
    browser_library_path: str = Field(default="", max_length=4_000)
    timezone: str = Field(min_length=1, max_length=64)
    repeat_interval_minutes: int = Field(ge=1, le=10080)
    run_limit: int = Field(ge=1, le=10000)
    approval_score: int = Field(ge=0, le=10)
    executor_type: str = Field(pattern=r"^(local|remote-http)$")
    remote_endpoint: str = ""
    remote_method: str = Field(default="POST", pattern=r"^(GET|POST|PUT)$")
    remote_timeout_seconds: int = Field(default=60, ge=1, le=900)
    remote_headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class WorkflowCloneCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    template_workflow_id: str
    repository: str = ""
    steps: list[dict] | None = None
    workflow_yaml: str | None = Field(default=None, max_length=100_000)
    runner_id: str | None = Field(default=None, max_length=64)


class RunnerAssetUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=100_000)


class RunnerAssetCreate(RunnerAssetUpdate):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    template_id: str = Field(default="custom", max_length=64)


@app.get("/api/runner-templates")
def runner_templates():
    public_catalog = {
        "insighta-user-simulator": {
            "name": "Command lifecycle adapter",
            "description": "Runs a target project's bounded prepare, execute, and evidence commands while Orbit owns scheduling.",
            "source": '''from orbit_runner_sdk import ORBIT_PROJECT_PATH, runner

# Replace this with the target project's bounded browser-check command.
COMMAND = ["python", "-m", "runner_target", "journey"]

def execute(ctx, action):
    ctx.exec([*COMMAND, action], cwd=ORBIT_PROJECT_PATH())

@runner.phase("init")
def init(ctx): execute(ctx, "status")
@runner.phase("setup")
def setup(ctx): execute(ctx, "prepare")
@runner.phase("run")
def run(ctx): execute(ctx, "run-once")
@runner.phase("eval")
def evaluate(ctx): execute(ctx, "collect-evidence")
@runner.phase("teardown")
def teardown(ctx): ctx.log("Browser journey check finished")
@runner.phase("finalize")
def finalize(ctx): ctx.log("Evaluation finalized")

if __name__ == "__main__": runner.main()
''',
        },
        "jgent-paired-improvement": {
            "name": "Bounded improvement cycle",
            "description": "Runs one locked improvement-and-validation cycle, then returns structured evidence to Orbit.",
            "source": '''from orbit_runner_sdk import ORBIT_PROJECT_PATH, runner

# Replace this with the target project's one-cycle improvement command.
CYCLE_COMMAND = ["python", "scripts", "run_improvement_cycle.py", "--once"]

@runner.phase("init")
def init(ctx):
    ctx.log(f"Target: {ORBIT_PROJECT_PATH()}")
@runner.phase("setup")
def setup(ctx):
    ctx.log("Starting a bounded, lock-protected improvement cycle")
@runner.phase("run")
def run(ctx):
    ctx.exec(CYCLE_COMMAND, cwd=ORBIT_PROJECT_PATH(), timeout=3600)
@runner.phase("eval")
def evaluate(ctx):
    ctx.log("Read the target's cycle evidence and report it through Orbit")
@runner.phase("teardown")
def teardown(ctx): ctx.log("Improvement cycle finished")
@runner.phase("finalize")
def finalize(ctx): ctx.log("Evaluation finalized")

if __name__ == "__main__": runner.main()
''',
        },
    }
    return [{**template, **public_catalog.get(template["id"], {})} for template in store.runner_templates()]


@app.get("/api/runners")
def runners():
    return store.runners()


@app.post("/api/runners")
def create_runner(values: RunnerAssetCreate):
    return safely(lambda: store.create_runner(values.model_dump()))


@app.put("/api/runners/{runner_id}")
def update_runner(runner_id: str, values: RunnerAssetUpdate):
    return safely(lambda: store.update_runner(runner_id, values.model_dump()))


@app.delete("/api/runners/{runner_id}")
def delete_runner(runner_id: str):
    return safely(lambda: store.delete_runner(runner_id))


@app.post("/api/runners/{runner_id}/open-vscode")
def open_runner_in_vscode(runner_id: str):
    return safely(lambda: store.open_runner_in_vscode(runner_id))


@app.post("/api/workflows/clone")
def clone_workflow(values: WorkflowCloneCreate):
    return safely(lambda: store.clone_workflow(values.model_dump()))


@app.put("/api/workflows/{workflow_id}")
def update_workflow(workflow_id: str, values: WorkflowCloneCreate):
    return safely(lambda: store.update_workflow(workflow_id, values.model_dump()))


@app.delete("/api/workflows/{workflow_id}")
def delete_workflow(workflow_id: str):
    return safely(lambda: store.delete_workflow(workflow_id))


@app.post("/api/evaluation-builds")
def create_evaluation_build(values: EvaluationBuildCreate):
    return safely(lambda: store.create_evaluation_build(values.model_dump()))


@app.put("/api/evaluation-builds/{build_id}")
def update_evaluation_build(build_id: str, values: EvaluationBuildCreate):
    return safely(lambda: store.update_evaluation_build(build_id, values.model_dump()))


@app.delete("/api/evaluation-builds/{build_id}")
def delete_evaluation_build(build_id: str):
    return safely(lambda: store.delete_evaluation_build(build_id))


@app.get("/api/improvements")
def improvements():
    return store.improvements()


@app.get("/api/reported-issues")
def reported_issues():
    return store.reported_issues()


@app.get("/api/telemetry")
def telemetry():
    return store.telemetry()


@app.get("/api/orbit-logs")
def orbit_logs():
    return store.orbit_logs()


@app.get("/api/docker/status")
def docker_status():
    return preflight_docker()


@app.get("/api/settings")
def settings():
    return store.settings()


@app.get("/api/settings/profiles")
def settings_profiles():
    return store.profiles()


@app.delete("/api/settings/profiles/{profile_name}")
def delete_profile(profile_name: str):
    return safely(lambda: store.delete_profile(profile_name))


@app.get("/api/application-settings")
def application_settings():
    return store.application_settings()


class ApplicationSettingsUpdate(BaseModel):
    manager_prompt_template: str = Field(default="", max_length=100_000)


@app.put("/api/application-settings")
def update_application_settings(values: ApplicationSettingsUpdate):
    return store.save_application_settings(values.model_dump())


class SettingsUpdate(BaseModel):
    profile_name: str = "Default"
    provider: str
    model: str = ""
    endpoint: str = ""
    region: str = "us-east-1"
    secret_env: str
    aws_profile: str = ""


@app.put("/api/settings")
def update_settings(values: SettingsUpdate):
    return store.save_settings(values.model_dump())


@app.post("/api/settings/hello")
def hello(values: SettingsUpdate | None = None):
    configured = values.model_dump() if values else store.settings()
    settings = ModelSettings(**{key: value for key, value in configured.items() if key != "profile_name"})
    try:
        provider = AzureOpenAIProvider() if settings.provider == "azure-openai" else BedrockProvider()
        with store.tracer.start_as_current_span(
            "model.hello",
            attributes={
                "gen_ai.provider.name": settings.provider,
                "gen_ai.request.model": settings.model,
            },
        ) as span:
            text = provider.complete(settings, "Reply with exactly: orbit hello")
            span.set_attribute("gen_ai.response.preview", text[:120])
            return {"ok": True, "response": text}
    except RuntimeError as error:
        raise HTTPException(409, str(error))


@app.post("/api/workflows/{workflow_id}/runs")
def create_run(workflow_id: str):
    return safely(lambda: store.create_run(workflow_id))


@app.post("/api/tasks/{task_id}/runs")
def run_task(task_id: str):
    return safely(lambda: store.create_run(task_id, "run"))


@app.post("/api/tasks/{task_id}/tests")
def test_task(task_id: str):
    return safely(lambda: store.create_run(task_id, "test"))


@app.post("/api/runs/{run_id}/approve")
def approve(run_id: str):
    return safely(lambda: store.approve(run_id))


@app.post("/api/runs/{run_id}/reject")
def reject(run_id: str):
    return safely(lambda: store.reject(run_id))


@app.post("/api/runs/{run_id}/cancel")
def cancel(run_id: str):
    return safely(lambda: store.cancel(run_id))


@app.post("/api/runs/emergency-stop")
def emergency_stop():
    return store.emergency_stop()


@app.get("/{path:path}", include_in_schema=False)
def local_web_app(path: str):
    """Serve the built React application for `orbit-agent-console run`."""
    if not WEB_DIST.exists():
        raise HTTPException(404, "Frontend is not built. Run `npm run build`.")
    candidate = (WEB_DIST / path).resolve()
    if path and WEB_DIST not in candidate.parents:
        raise HTTPException(404, "Not found.")
    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(WEB_DIST / "index.html")
