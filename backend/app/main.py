from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .docker import preflight_docker
from .providers import AzureOpenAIProvider, BedrockProvider, ModelSettings
from .store import ConsoleStore

app = FastAPI(
    title="OpenOrbit API",
    version="0.0.4",
    summary="A local control plane API for recurring AI automations.",
    description="""\
The versioned API follows a GitLab-inspired resource model: an evaluation build
is exposed as a **project**, and every invocation is exposed as a **pipeline**.

This service is local by default and has no built-in authentication. Put it
behind an authentication and network boundary before exposing it beyond the
operator's machine.
""",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_tags=[
        {"name": "Projects", "description": "Configured evaluation builds and their assets."},
        {"name": "Pipelines", "description": "Workflow executions and approval actions."},
        {"name": "Workflows", "description": "Reusable lifecycle definitions."},
        {"name": "Runners", "description": "Executable local runner assets."},
        {"name": "Runner templates", "description": "Reusable runner-source templates."},
        {"name": "Prompt templates", "description": "Versioned manager prompt assets."},
        {"name": "Test case sets", "description": "Reusable fixed target-AI test cases."},
        {
            "name": "Model profiles",
            "description": "Provider configuration; secrets remain environment variables.",
        },
        {"name": "Application settings", "description": "Local control-room settings."},
        {"name": "Workspaces", "description": "Approved local workspace discovery."},
        {"name": "Observability", "description": "Dashboard, logs, and OpenTelemetry evidence."},
        {"name": "Improvements", "description": "Read-only supervisor feedback and analytics."},
        {"name": "System", "description": "Local service health and capabilities."},
    ],
)
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


def paginated(values: list, response: Response, page: int, per_page: int) -> list:
    """Use GitLab-compatible pagination headers for collection endpoints."""
    total = len(values)
    start = (page - 1) * per_page
    pages = max(1, (total + per_page - 1) // per_page)
    response.headers["X-Total"] = str(total)
    response.headers["X-Total-Pages"] = str(pages)
    response.headers["X-Page"] = str(page)
    response.headers["X-Per-Page"] = str(per_page)
    response.headers["X-Next-Page"] = str(page + 1) if page < pages else ""
    response.headers["X-Prev-Page"] = str(page - 1) if page > 1 else ""
    return values[start : start + per_page]


def resource(values: list[dict], resource_id: str) -> dict:
    """Return an ID-addressable local asset with the same 404 behavior as v1 resources."""
    item = next((value for value in values if value.get("id") == resource_id), None)
    if item is None:
        raise KeyError(resource_id)
    return item


@app.get("/api/health", tags=["System"], summary="Get local service health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/health", tags=["System"], operation_id="getHealth", summary="Get API health")
def health_v1():
    return health()


@app.get("/api/v1", tags=["System"], operation_id="getApiInfo", summary="Get API entry-point information")
def api_info_v1():
    return {
        "name": "OpenOrbit API",
        "version": app.version,
        "openapi_url": app.openapi_url,
        "documentation_url": app.docs_url,
    }


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


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    return safely(lambda: store.delete_run(run_id))


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


@app.get("/api/execution-environments")
def execution_environments():
    return store.execution_environments()


@app.get("/api/target-environments")
def target_environments():
    return store.target_environments()


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


class ExecutionEnvironmentCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    executor_type: Literal["local", "remote-http"] = "local"
    remote_endpoint: str = ""
    remote_method: Literal["GET", "POST", "PUT"] = "POST"
    remote_timeout_seconds: int = Field(default=60, ge=1, le=900)
    remote_headers: dict[str, str] = Field(default_factory=dict)
    browser_executable_path: str = ""
    browser_library_path: str = ""


class TargetEnvironmentCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    repository: str = Field(min_length=1)
    browser_base_url: str = ""
    managed_prompt_path: str = ""


class ExecutionEnvironmentUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    executor_type: Literal["local", "remote-http"] = "local"
    remote_endpoint: str = ""
    remote_method: Literal["GET", "POST", "PUT"] = "POST"
    remote_timeout_seconds: int = Field(default=60, ge=1, le=900)
    remote_headers: dict[str, str] = Field(default_factory=dict)
    browser_executable_path: str = ""
    browser_library_path: str = ""


class TargetEnvironmentUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    repository: str = Field(min_length=1)
    browser_base_url: str = ""
    managed_prompt_path: str = ""


@app.put("/api/prompt-templates/{template_id}")
def update_prompt_template(template_id: str, values: PromptTemplateUpdate):
    return safely(lambda: store.update_prompt_template(template_id, values.model_dump()))


@app.post("/api/prompt-templates")
def create_prompt_template(values: PromptTemplateCreate):
    return safely(lambda: store.create_prompt_template(values.model_dump()))


@app.post("/api/target-test-case-sets")
def create_target_test_case_set(values: TargetTestCaseSetCreate):
    return safely(lambda: store.create_target_test_case_set(values.model_dump()))


@app.post("/api/execution-environments")
def create_execution_environment(values: ExecutionEnvironmentCreate):
    return safely(lambda: store.create_execution_environment(values.model_dump()))


@app.post("/api/target-environments")
def create_target_environment(values: TargetEnvironmentCreate):
    return safely(lambda: store.create_target_environment(values.model_dump()))


@app.put("/api/execution-environments/{environment_id}")
def update_execution_environment(environment_id: str, values: ExecutionEnvironmentUpdate):
    return safely(lambda: store.update_execution_environment(environment_id, values.model_dump()))


@app.put("/api/target-environments/{environment_id}")
def update_target_environment(environment_id: str, values: TargetEnvironmentUpdate):
    return safely(lambda: store.update_target_environment(environment_id, values.model_dump()))


@app.delete("/api/execution-environments/{environment_id}")
def delete_execution_environment(environment_id: str):
    return safely(lambda: store.delete_execution_environment(environment_id))


@app.delete("/api/target-environments/{environment_id}")
def delete_target_environment(environment_id: str):
    return safely(lambda: store.delete_target_environment(environment_id))


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
    repository: str = ""  # Legacy target-environment input.
    target_environment_id: str = ""
    execution_environment_id: str = ""
    purpose: str = Field(min_length=1, max_length=500)
    manager_template_id: str = "manager-default-v1"
    model_profile_name: str = "Default"
    test_case_set_id: str = Field(min_length=1, max_length=64)
    browser_base_url: str = Field(default="", max_length=2_000)
    browser_executable_path: str = Field(default="", max_length=4_000)
    browser_library_path: str = Field(default="", max_length=4_000)
    timezone: str = Field(min_length=1, max_length=64)
    repeat_interval_minutes: int = Field(ge=1, le=10080)
    run_limit: int = Field(ge=1, le=10000)
    approval_score: int = Field(ge=0, le=10)
    executor_type: str = Field(
        default="local", pattern=r"^(local|remote-http)$"
    )  # Legacy fallback; selected execution environment is authoritative.
    remote_endpoint: str = ""
    remote_method: str = Field(default="POST", pattern=r"^(GET|POST|PUT)$")
    remote_timeout_seconds: int = Field(default=60, ge=1, le=900)
    remote_headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class PipelineCreate(BaseModel):
    """The requested execution mode for a project pipeline."""

    execution_mode: Literal["run", "test"] = "run"


class PipelineAction(BaseModel):
    action: Literal["approve", "reject", "cancel"]


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
    template_id: str | None = Field(default=None, max_length=64)


class RunnerAssetCreate(RunnerAssetUpdate):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    template_id: str = Field(default="custom", max_length=64)


class RunnerTemplateValues(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=100_000)


class RunnerTemplateUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=100_000)


@app.get("/api/runner-templates")
def runner_templates():
    return store.available_runner_templates()


@app.post("/api/runner-templates/import")
def import_runner_template(values: RunnerTemplateValues):
    return safely(lambda: store.create_runner_template(values.model_dump()))


@app.put("/api/runner-templates/{template_id}")
def update_runner_template(template_id: str, values: RunnerTemplateUpdate):
    return safely(lambda: store.update_runner_template(template_id, values.model_dump()))


@app.delete("/api/runner-templates/{template_id}")
def delete_runner_template(template_id: str):
    return safely(lambda: store.delete_runner_template(template_id))


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


# Public, versioned API.  The existing /api/* endpoints above remain the UI's
# internal contract; these endpoints are intentionally stable and resource-oriented.
@app.get(
    "/api/v1/projects",
    tags=["Projects"],
    operation_id="listProjects",
    summary="List projects",
    response_description="A page of evaluation-build projects.",
)
def list_projects(
    response: Response,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    return paginated(store.evaluation_builds(), response, page, per_page)


@app.get(
    "/api/v1/projects/{project_id}",
    tags=["Projects"],
    operation_id="getProject",
    summary="Get a project",
)
def get_project(project_id: str):
    return safely(lambda: store.evaluation_build(project_id))


@app.post(
    "/api/v1/projects",
    tags=["Projects"],
    operation_id="createProject",
    status_code=201,
    summary="Create a project",
)
def create_project(values: EvaluationBuildCreate):
    return safely(lambda: store.create_evaluation_build(values.model_dump()))


@app.put(
    "/api/v1/projects/{project_id}",
    tags=["Projects"],
    operation_id="updateProject",
    summary="Replace a project configuration",
)
def replace_project(project_id: str, values: EvaluationBuildCreate):
    return safely(lambda: store.update_evaluation_build(project_id, values.model_dump()))


@app.delete(
    "/api/v1/projects/{project_id}",
    tags=["Projects"],
    operation_id="deleteProject",
    status_code=204,
    summary="Delete a project",
)
def remove_project(project_id: str):
    safely(lambda: store.delete_evaluation_build(project_id))


@app.get(
    "/api/v1/projects/{project_id}/pipelines",
    tags=["Pipelines"],
    operation_id="listProjectPipelines",
    summary="List pipelines for a project",
)
def list_project_pipelines(
    project_id: str,
    response: Response,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    # Validate the parent resource even when it has not run a pipeline yet.
    safely(lambda: store.evaluation_build(project_id))
    runs = [run for run in store.runs() if run.evaluation_build_id == project_id]
    return paginated(runs, response, page, per_page)


@app.post(
    "/api/v1/projects/{project_id}/pipelines",
    tags=["Pipelines"],
    operation_id="createProjectPipeline",
    status_code=201,
    summary="Start a project pipeline",
)
def create_project_pipeline(project_id: str, values: PipelineCreate):
    return safely(lambda: store.invoke_remote_build(project_id, values.execution_mode))


@app.get(
    "/api/v1/pipelines",
    tags=["Pipelines"],
    operation_id="listPipelines",
    summary="List pipelines",
)
def list_pipelines(
    response: Response,
    project_id: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    runs = store.runs()
    if project_id:
        runs = [run for run in runs if run.evaluation_build_id == project_id]
    if status:
        runs = [run for run in runs if run.status == status]
    return paginated(runs, response, page, per_page)


@app.get(
    "/api/v1/pipelines/{pipeline_id}",
    tags=["Pipelines"],
    operation_id="getPipeline",
    summary="Get a pipeline",
)
def get_pipeline(pipeline_id: str):
    return safely(lambda: store.run(pipeline_id))


@app.post(
    "/api/v1/pipelines/{pipeline_id}/actions",
    tags=["Pipelines"],
    operation_id="actOnPipeline",
    summary="Approve, reject, or cancel a pipeline",
)
def act_on_pipeline(pipeline_id: str, values: PipelineAction):
    actions = {
        "approve": store.approve,
        "reject": store.reject,
        "cancel": store.cancel,
    }
    return safely(lambda: actions[values.action](pipeline_id))


@app.get("/api/v1/workflows", tags=["Workflows"], operation_id="listWorkflows")
def list_workflows():
    return store.workflows()


@app.get("/api/v1/workflows/{workflow_id}", tags=["Workflows"], operation_id="getWorkflow")
def get_workflow(workflow_id: str):
    return safely(lambda: store.workflow(workflow_id))


@app.post(
    "/api/v1/workflows",
    tags=["Workflows"],
    operation_id="createWorkflow",
    status_code=201,
    summary="Create a workflow from a template",
)
def create_workflow(values: WorkflowCloneCreate):
    return safely(lambda: store.clone_workflow(values.model_dump()))


@app.put("/api/v1/workflows/{workflow_id}", tags=["Workflows"], operation_id="updateWorkflow")
def replace_workflow(workflow_id: str, values: WorkflowCloneCreate):
    return safely(lambda: store.update_workflow(workflow_id, values.model_dump()))


@app.delete("/api/v1/workflows/{workflow_id}", tags=["Workflows"], status_code=204)
def remove_workflow(workflow_id: str):
    safely(lambda: store.delete_workflow(workflow_id))


@app.post(
    "/api/v1/workflows/{workflow_id}/pipelines",
    tags=["Pipelines", "Workflows"],
    operation_id="createWorkflowPipeline",
    status_code=201,
    summary="Start a standalone workflow pipeline",
)
def create_workflow_pipeline(workflow_id: str, values: PipelineCreate):
    return safely(lambda: store.create_run(workflow_id, values.execution_mode))


@app.get("/api/v1/runners", tags=["Runners"], operation_id="listRunners")
def list_runners():
    return store.runners()


@app.get("/api/v1/runners/{runner_id}", tags=["Runners"], operation_id="getRunner")
def get_runner(runner_id: str):
    return safely(lambda: resource(store.runners(), runner_id))


@app.post("/api/v1/runners", tags=["Runners"], operation_id="createRunner", status_code=201)
def create_runner_v1(values: RunnerAssetCreate):
    return safely(lambda: store.create_runner(values.model_dump()))


@app.put("/api/v1/runners/{runner_id}", tags=["Runners"], operation_id="updateRunner")
def replace_runner_v1(runner_id: str, values: RunnerAssetUpdate):
    return safely(lambda: store.update_runner(runner_id, values.model_dump()))


@app.delete("/api/v1/runners/{runner_id}", tags=["Runners"], status_code=204)
def remove_runner_v1(runner_id: str):
    safely(lambda: store.delete_runner(runner_id))


@app.post(
    "/api/v1/runners/{runner_id}/actions/open-vscode",
    tags=["Runners"],
    operation_id="openRunnerInVSCode",
    summary="Open a runner source file in the local VS Code installation",
)
def open_runner_v1(runner_id: str):
    return safely(lambda: store.open_runner_in_vscode(runner_id))


@app.get("/api/v1/runner-templates", tags=["Runner templates"], operation_id="listRunnerTemplates")
def list_runner_templates_v1():
    return store.available_runner_templates()


@app.get(
    "/api/v1/runner-templates/{template_id}", tags=["Runner templates"], operation_id="getRunnerTemplate"
)
def get_runner_template_v1(template_id: str):
    return safely(lambda: resource(store.available_runner_templates(), template_id))


@app.post(
    "/api/v1/runner-templates",
    tags=["Runner templates"],
    operation_id="createRunnerTemplate",
    status_code=201,
)
def create_runner_template_v1(values: RunnerTemplateValues):
    return safely(lambda: store.create_runner_template(values.model_dump()))


@app.put(
    "/api/v1/runner-templates/{template_id}", tags=["Runner templates"], operation_id="updateRunnerTemplate"
)
def replace_runner_template_v1(template_id: str, values: RunnerTemplateUpdate):
    return safely(lambda: store.update_runner_template(template_id, values.model_dump()))


@app.delete("/api/v1/runner-templates/{template_id}", tags=["Runner templates"], status_code=204)
def remove_runner_template_v1(template_id: str):
    safely(lambda: store.delete_runner_template(template_id))


@app.get("/api/v1/prompt-templates", tags=["Prompt templates"], operation_id="listPromptTemplates")
def list_prompt_templates_v1():
    return store.prompt_templates()


@app.get(
    "/api/v1/prompt-templates/{template_id}", tags=["Prompt templates"], operation_id="getPromptTemplate"
)
def get_prompt_template_v1(template_id: str):
    return safely(lambda: resource(store.prompt_templates(), template_id))


@app.post(
    "/api/v1/prompt-templates",
    tags=["Prompt templates"],
    operation_id="createPromptTemplate",
    status_code=201,
)
def create_prompt_template_v1(values: PromptTemplateCreate):
    return safely(lambda: store.create_prompt_template(values.model_dump()))


@app.put(
    "/api/v1/prompt-templates/{template_id}", tags=["Prompt templates"], operation_id="updatePromptTemplate"
)
def replace_prompt_template_v1(template_id: str, values: PromptTemplateUpdate):
    return safely(lambda: store.update_prompt_template(template_id, values.model_dump()))


@app.delete("/api/v1/prompt-templates/{template_id}", tags=["Prompt templates"], status_code=204)
def remove_prompt_template_v1(template_id: str):
    safely(lambda: store.delete_prompt_template(template_id))


@app.get("/api/v1/test-case-sets", tags=["Test case sets"], operation_id="listTestCaseSets")
def list_test_case_sets_v1():
    return store.target_test_case_sets()


@app.get("/api/v1/test-case-sets/{set_id}", tags=["Test case sets"], operation_id="getTestCaseSet")
def get_test_case_set_v1(set_id: str):
    return safely(lambda: resource(store.target_test_case_sets(), set_id))


@app.post(
    "/api/v1/test-case-sets", tags=["Test case sets"], operation_id="createTestCaseSet", status_code=201
)
def create_test_case_set_v1(values: TargetTestCaseSetCreate):
    return safely(lambda: store.create_target_test_case_set(values.model_dump()))


@app.put("/api/v1/test-case-sets/{set_id}", tags=["Test case sets"], operation_id="updateTestCaseSet")
def replace_test_case_set_v1(set_id: str, values: TargetTestCaseSetUpdate):
    return safely(lambda: store.update_target_test_case_set(set_id, values.model_dump()))


@app.delete("/api/v1/test-case-sets/{set_id}", tags=["Test case sets"], status_code=204)
def remove_test_case_set_v1(set_id: str):
    safely(lambda: store.delete_target_test_case_set(set_id))


@app.get("/api/improvements")
def improvements():
    return store.improvements()


@app.get("/api/proposal-decisions")
def proposal_decisions():
    return store.proposal_decisions()


@app.get("/api/cycle-interventions")
def cycle_interventions():
    return store.cycle_interventions()


@app.get("/api/improvement-analytics")
def improvement_analytics(hours: int = 24):
    return store.improvement_analytics(hours)


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
    chat_model_profile_name: str = Field(default="", max_length=200)


@app.put("/api/application-settings")
def update_application_settings(values: ApplicationSettingsUpdate):
    return store.save_application_settings(values.model_dump())


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=20_000)


class ChatMessage(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


@app.post("/api/chat")
def chat(values: ChatMessage):
    profile_name = store.application_settings()["chat_model_profile_name"]
    if not profile_name:
        raise HTTPException(409, "Select an AI model profile for the chat assistant in Settings.")
    configured = profile(store.profiles(), profile_name)
    settings = ModelSettings(**{key: value for key, value in configured.items() if key != "profile_name"})
    try:
        provider = AzureOpenAIProvider() if settings.provider == "azure-openai" else BedrockProvider()
        history = "\n".join(f"{turn.role.title()}: {turn.content}" for turn in values.history)
        prompt = (
            "You are Orbit, a concise assistant for the local OpenOrbit control room.\n"
            "The local OpenAPI contract is available at /api/openapi.json; use it as the source of truth "
            "when explaining API endpoints, parameters, and response shapes.\n"
        )
        if history:
            prompt += f"Conversation so far:\n{history}\n\n"
        prompt += f"User: {values.content}\nAssistant:"
        return {"response": provider.complete(settings, prompt), "profile_name": profile_name}
    except RuntimeError as error:
        raise HTTPException(409, str(error))


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


def profile(profiles: list[dict[str, str]], profile_name: str) -> dict[str, str]:
    item = next((value for value in profiles if value["profile_name"] == profile_name), None)
    if item is None:
        raise KeyError(profile_name)
    return item


@app.get("/api/v1/model-profiles", tags=["Model profiles"], operation_id="listModelProfiles")
def list_model_profiles_v1():
    return store.profiles()


@app.get("/api/v1/model-profiles/{profile_name}", tags=["Model profiles"], operation_id="getModelProfile")
def get_model_profile_v1(profile_name: str):
    return safely(lambda: profile(store.profiles(), profile_name))


@app.put(
    "/api/v1/model-profiles/{profile_name}",
    tags=["Model profiles"],
    operation_id="upsertModelProfile",
    summary="Create or update a model profile and select it as active",
)
def upsert_model_profile_v1(profile_name: str, values: SettingsUpdate):
    if profile_name != values.profile_name:
        raise HTTPException(409, "profile_name must match the URL")
    return store.save_settings(values.model_dump())


@app.delete("/api/v1/model-profiles/{profile_name}", tags=["Model profiles"], status_code=204)
def remove_model_profile_v1(profile_name: str):
    safely(lambda: store.delete_profile(profile_name))


@app.post(
    "/api/v1/model-profiles/test",
    tags=["Model profiles"],
    operation_id="testModelProfile",
    summary="Test unsaved or saved provider settings",
)
def test_model_profile_v1(values: SettingsUpdate):
    return hello(values)


@app.get("/api/v1/application-settings", tags=["Application settings"], operation_id="getApplicationSettings")
def get_application_settings_v1():
    return store.application_settings()


@app.put(
    "/api/v1/application-settings", tags=["Application settings"], operation_id="updateApplicationSettings"
)
def replace_application_settings_v1(values: ApplicationSettingsUpdate):
    return store.save_application_settings(values.model_dump())


@app.get("/api/v1/workspaces", tags=["Workspaces"], operation_id="listWorkspaces")
def list_workspaces_v1(path: str | None = None):
    return safely(lambda: store.workspaces(path))


@app.get("/api/v1/dashboard", tags=["Observability"], operation_id="getDashboard")
def dashboard_v1():
    return store.dashboard()


@app.get("/api/v1/active-pipelines", tags=["Pipelines"], operation_id="listActivePipelines")
def list_active_pipelines_v1():
    return store.active_evaluations()


@app.get(
    "/api/v1/pipelines/{pipeline_id}/telemetry", tags=["Observability"], operation_id="getPipelineTelemetry"
)
def get_pipeline_telemetry_v1(pipeline_id: str):
    return safely(lambda: store.run_telemetry(pipeline_id))


@app.get("/api/v1/telemetry", tags=["Observability"], operation_id="listTelemetry")
def list_telemetry_v1():
    return store.telemetry()


@app.get("/api/v1/logs", tags=["Observability"], operation_id="listLogs")
def list_logs_v1():
    return store.orbit_logs()


@app.get("/api/v1/improvements", tags=["Improvements"], operation_id="listImprovements")
def list_improvements_v1():
    return store.improvements()


@app.get(
    "/api/v1/improvements/proposal-decisions",
    tags=["Improvements"],
    operation_id="listProposalDecisions",
    summary="List SDK-recorded accepted and rejected proposals",
)
def list_proposal_decisions_v1():
    return store.proposal_decisions()


@app.get(
    "/api/v1/improvements/proposals",
    tags=["Improvements"],
    operation_id="listProposalLifecycles",
    summary="List proposal lifecycles with decisions and prompt versions",
)
def list_proposal_lifecycles_v1(
    evaluation_build_id: str | None = None,
    status: Literal["proposed", "accepted", "rejected", "applied"] | None = None,
):
    return store.proposal_lifecycles(evaluation_build_id, status)


@app.get("/api/v1/improvements/analytics", tags=["Improvements"], operation_id="getImprovementAnalytics")
def improvement_analytics_v1(hours: int = Query(default=24, ge=1, le=720)):
    return store.improvement_analytics(hours)


@app.get("/api/v1/improvements/interventions", tags=["Improvements"], operation_id="listCycleInterventions")
def list_cycle_interventions_v1():
    return store.cycle_interventions()


@app.get("/api/v1/reported-issues", tags=["Improvements"], operation_id="listReportedIssues")
def list_reported_issues_v1():
    return store.reported_issues()


@app.get("/api/v1/system/docker", tags=["System"], operation_id="getDockerStatus")
def docker_status_v1():
    return preflight_docker()


@app.post(
    "/api/v1/pipelines/actions/emergency-stop",
    tags=["Pipelines"],
    operation_id="emergencyStopPipelines",
    summary="Cancel every active local pipeline",
)
def emergency_stop_v1():
    return store.emergency_stop()


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
        raise HTTPException(404, "Frontend is not built. Run `pnpm run build`.")
    candidate = (WEB_DIST / path).resolve()
    if path and WEB_DIST not in candidate.parents:
        raise HTTPException(404, "Not found.")
    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(WEB_DIST / "index.html")
