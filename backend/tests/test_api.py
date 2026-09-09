import base64
import json
import sys

import orbit_sdk as sdk
import pytest
from app import main as main_module
from app import providers
from app import store as store_module
from app.main import app
from app.models import Run, Step, Workflow
from fastapi.testclient import TestClient
from orbit_sdk import RunnerContext


def test_health_is_available():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_generated_sdk_docs_are_served_from_the_local_app(tmp_path, monkeypatch):
    docs = tmp_path / "site" / "sdk"
    docs.mkdir(parents=True)
    (docs / "index.html").write_text("<h1>SDK reference</h1>", encoding="utf-8")
    monkeypatch.setattr(main_module, "SDK_DOCS_DIST", docs.parent)

    response = TestClient(app).get("/sdk-docs/sdk/")

    assert response.status_code == 200
    assert "SDK reference" in response.text


def test_cancelling_a_waiting_run_clears_its_current_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    store._save(
        Run(
            id="waiting-run",
            workflow_id="workflow",
            workflow_name="Workflow",
            status="running",
            created_at=timestamp,
            updated_at=timestamp,
            current_step="loop",
            current_phase="waiting",
        )
    )

    cancelled = store.cancel("waiting-run")

    assert cancelled.status == "cancelled"
    assert cancelled.current_step is None
    assert cancelled.current_phase is None


def test_runner_target_logs_are_retained_separately_from_runner_output(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    project = tmp_path / "target"
    project.mkdir()
    runner = project / "runner.py"
    runner.write_text(
        "from orbit_sdk import runner\n"
        "@runner.phase('run')\n"
        "def run(ctx):\n"
        "    ctx.target_log('service started', source='target-api')\n"
        "    ctx.target_log('slow response', level='warn', source='target-api')\n"
        "if __name__ == '__main__': runner.main()\n",
        encoding="utf-8",
    )
    timestamp = store_module.now()
    store = store_module.ConsoleStore()
    store._save(
        Run(
            id="target-log-run",
            workflow_id="workflow",
            workflow_name="Workflow",
            repository=str(project),
            status="running",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )

    store._execute_step(
        "target-log-run",
        Step(
            id="run",
            phase="run",
            name="Run",
            command=[sys.executable, str(runner), "--phase", "run"],
            working_directory=str(project),
        ),
        loop_index=3,
    )

    step = store._load("target-log-run").step_results[-1]
    assert "target_logs" not in (step.get("result") or {})
    assert step["output"] == ""
    assert [(entry["level"], entry["source"], entry["message"]) for entry in step["target_logs"]] == [
        ("info", "target-api", "service started"),
        ("warn", "target-api", "slow response"),
    ]
    assert all(entry["run_id"] == "target-log-run" for entry in step["target_logs"])
    assert all(entry["iteration"] == 3 and entry["phase"] == "run" for entry in step["target_logs"])


def test_runner_data_files_are_retained_for_the_iteration(tmp_path, monkeypatch):
    app_data = tmp_path / "orbit-data"
    monkeypatch.setattr(store_module, "APP_DATA", app_data)
    monkeypatch.setattr(store_module, "RUNS", app_data / "data" / "runs")
    project = tmp_path / "target"
    project.mkdir()
    runner = project / "runner.py"
    runner.write_text(
        "from orbit_sdk import runner\n"
        "@runner.phase('run')\n"
        "def run(ctx):\n"
        "    ctx.save_data_file('evidence/first.json', '{}', label='First result')\n"
        "    ctx.save_data_file('evidence/second.json', '{}', label='Second result')\n"
        "if __name__ == '__main__': runner.main()\n",
        encoding="utf-8",
    )
    timestamp = store_module.now()
    store = store_module.ConsoleStore()
    store._save(
        Run(
            id="data-file-run",
            workflow_id="workflow",
            workflow_name="Workflow",
            repository=str(project),
            status="running",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )

    store._execute_step(
        "data-file-run",
        Step(
            id="run",
            phase="run",
            name="Run",
            command=[sys.executable, str(runner), "--phase", "run"],
            working_directory=str(project),
        ),
        loop_index=3,
    )

    files = store._load("data-file-run").step_results[-1]["data_files"]
    assert [(item["label"], item["filename"]) for item in files] == [
        ("First result", "first.json"),
        ("Second result", "second.json"),
    ]
    assert all(item["path"].startswith(str(app_data)) for item in files)


def test_prompt_revisions_returns_immutable_prompt_diff(tmp_path, monkeypatch):
    app_data = tmp_path / "orbit-data"
    project = tmp_path / "project"
    project.mkdir()
    prompt = project / "prompt.md"
    prompt.write_text("before\n", encoding="utf-8")
    monkeypatch.setattr(store_module, "APP_DATA", app_data)
    monkeypatch.setattr(store_module, "RUNS", app_data / "data" / "runs")
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", app_data)
    resources = base64.b64encode(
        json.dumps({"evaluation_build": {"managed_prompt_path": "prompt.md"}}).encode()
    ).decode()
    update = RunnerContext(
        phase="setup",
        target_repository=project,
        mode="run",
        loop_index=1,
        environment={"ORBIT_RUN_ID": "prompt-run", "ORBIT_RUNNER_RESOURCES": resources},
    ).update_file("prompt.md", "after\n")
    timestamp = store_module.now()
    store = store_module.ConsoleStore()
    store._save(
        Run(
            id="prompt-run",
            workflow_id="workflow",
            workflow_name="Workflow",
            repository=str(project),
            status="succeeded",
            created_at=timestamp,
            updated_at=timestamp,
            step_results=[
                {
                    "phase": "setup",
                    "loop_index": 1,
                    "ended_at": timestamp.isoformat(),
                    "result": {"file_update": update},
                },
                {
                    "phase": "setup",
                    "loop_index": 2,
                    "ended_at": timestamp.isoformat(),
                    "result": {
                        "file_update_blocked": {
                            "path": "prompt.md",
                            "reason": "awaiting_human_approval",
                        }
                    },
                },
            ],
        )
    )

    revisions = store.prompt_revisions("prompt-run")

    assert revisions[0]["status"] == "initial"
    assert revisions[0]["after"] == "before\n"
    assert revisions[1]["status"] == "applied"
    assert revisions[1]["before"] == "before\n"
    assert revisions[1]["after"] == "after\n"
    assert revisions[2]["status"] == "blocked"
    assert revisions[2]["before"] == "after\n"
    assert revisions[2]["after"] == "after\n"


def test_commit_changes_returns_sdk_commit_range(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    store._save(
        Run(
            id="commit-run",
            workflow_id="workflow",
            workflow_name="Workflow",
            status="succeeded",
            created_at=timestamp,
            updated_at=timestamp,
            step_results=[
                {
                    "phase": "run",
                    "loop_index": 2,
                    "ended_at": timestamp.isoformat(),
                    "result": {
                        "commit_change": {
                            "before": "a" * 40,
                            "after": "b" * 40,
                            "changed_paths": ["src/agent.py"],
                            "commits": [{"sha": "b" * 40, "subject": "Improve agent"}],
                            "diff_artifact": {"relative_path": "commits/a..b.patch"},
                        }
                    },
                }
            ],
        )
    )

    changes = store.commit_changes("commit-run")

    assert changes[0]["before"] == "a" * 40
    assert changes[0]["commits"][0]["subject"] == "Improve agent"
    assert changes[0]["changed_paths"] == ["src/agent.py"]


def test_commit_changes_includes_jgent_committed_source_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    store._save(
        Run(
            id="jgent-commit-run",
            workflow_id="workflow",
            workflow_name="Jgent",
            status="succeeded",
            created_at=timestamp,
            updated_at=timestamp,
            step_results=[
                {
                    "phase": "setup",
                    "loop_index": 1,
                    "ended_at": timestamp.isoformat(),
                    "result": {
                        "jgent_paired": {
                            "committed_source_candidate": {
                                "status": "committed_source_candidate",
                                "before": "a" * 40,
                                "after": "b" * 40,
                                "changed_paths": ["src/Jgent/Agent.cs"],
                                "commits": [{"sha": "b" * 40, "subject": "Improve Jgent"}],
                            }
                        }
                    },
                }
            ],
        )
    )

    changes = store.commit_changes("jgent-commit-run")

    assert changes[0]["changed_paths"] == ["src/Jgent/Agent.cs"]
    assert changes[0]["commits"][0]["subject"] == "Improve Jgent"


@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
def test_teardown_runs_after_a_failed_or_cancelled_iteration(tmp_path, monkeypatch, terminal_status):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    run = Run(
        id=f"cleanup-{terminal_status}",
        workflow_id="cleanup-workflow",
        workflow_name="Cleanup workflow",
        execution_mode="test",
        status="queued",
        created_at=timestamp,
        updated_at=timestamp,
    )
    store._save(run)
    workflow = Workflow(
        id="cleanup-workflow",
        name="Cleanup workflow",
        description="",
        kind="simulation",
        risk="low",
        steps=[
            Step(id="setup", phase="setup", name="Setup", command=[], working_directory="."),
            Step(id="teardown", phase="teardown", name="Teardown", command=[], working_directory="."),
        ],
    )
    monkeypatch.setattr(store, "_runner_execution_plan", lambda _: workflow)
    calls = []

    def execute_step(run_id, step, loop_index=1, resources=None, *, allow_terminal=False):
        calls.append((step.phase, loop_index, allow_terminal))
        if step.phase == "setup":
            current = store._load(run_id)
            current.status = terminal_status
            store._save(current)

    monkeypatch.setattr(store, "_execute_step", execute_step)

    store._execute(run.id)

    assert calls == [("setup", 1, False), ("teardown", 1, True)]


@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
def test_finalize_runs_after_a_terminal_iteration_for_repository_recovery(
    tmp_path, monkeypatch, terminal_status
):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    run = Run(
        id=f"finalize-{terminal_status}",
        workflow_id="recovery-workflow",
        workflow_name="Recovery workflow",
        execution_mode="test",
        status="queued",
        created_at=timestamp,
        updated_at=timestamp,
    )
    store._save(run)
    workflow = Workflow(
        id="recovery-workflow",
        name="Recovery workflow",
        description="",
        kind="simulation",
        risk="low",
        steps=[
            Step(id="setup", phase="setup", name="Setup", command=[], working_directory="."),
            Step(id="finalize", phase="finalize", name="Finalize", command=[], working_directory="."),
        ],
    )
    monkeypatch.setattr(store, "_runner_execution_plan", lambda _: workflow)
    calls = []

    def execute_step(run_id, step, loop_index=1, resources=None, *, allow_terminal=False):
        calls.append((step.phase, loop_index, allow_terminal))
        if step.phase == "setup":
            current = store._load(run_id)
            current.status = terminal_status
            store._save(current)

    monkeypatch.setattr(store, "_execute_step", execute_step)

    store._execute(run.id)

    assert calls == [("setup", 1, False), ("finalize", 2, True)]


def test_native_improvement_template_uses_repository_snapshot_lifecycle():
    source = store_module.NATIVE_IMPROVEMENT_CYCLE_TEMPLATE

    assert "ctx.save_setup_snapshot()" in source
    assert "ctx.save_first_teardown_snapshot()" in source
    assert "ctx.restore_setup_snapshot()" in source


def test_score_select_retains_candidates_and_selects_highest_supervisor_score(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    run = Run(
        id="score-select",
        workflow_id="workflow",
        workflow_name="Workflow",
        execution_mode="run",
        status="queued",
        created_at=timestamp,
        updated_at=timestamp,
        loop_limit=2,
        iteration_strategy="score_select",
        candidates_per_iteration=2,
    )
    store._save(run)
    workflow = Workflow(
        id="workflow",
        name="Workflow",
        description="",
        kind="simulation",
        risk="low",
        steps=[Step(id="run", phase="run", name="Run", command=[], working_directory=".")],
    )
    monkeypatch.setattr(store, "_runner_execution_plan", lambda _: workflow)
    calls = []

    def execute_step(
        run_id,
        step,
        loop_index=1,
        resources=None,
        *,
        allow_terminal=False,
        candidate_id=None,
        base_candidate_id=None,
    ):
        calls.append((step.id, loop_index, candidate_id, base_candidate_id, allow_terminal))
        current = store._load(run_id)
        current.step_results.append(
            {"phase": step.phase, "loop_index": loop_index, "candidate_id": candidate_id}
        )
        store._save(current)

    def supervise(run_id):
        current = store._load(run_id)
        candidate_id = current.step_results[-1]["candidate_id"]
        score = 9 if candidate_id == "2-2" else 7
        current.supervisor_results.append(
            {
                "iteration": int(candidate_id.split("-")[0]),
                "candidate_id": candidate_id,
                "status": "completed",
                "response": {"evaluation": {"score": score}, "improvements": [], "reported_issues": []},
            }
        )
        store._save(current)

    monkeypatch.setattr(store, "_execute_step", execute_step)
    monkeypatch.setattr(store, "_complete_supervision", supervise)
    store._execute(run.id)
    completed = store._load(run.id)
    assert [(item["id"], item["selected"]) for item in completed.iteration_candidates] == [
        ("1", True),
        ("2-1", False),
        ("2-2", True),
    ]
    assert calls == [
        ("run", 1, "1", None, False),
        ("run", 2, "2-1", "1", False),
        ("run", 2, "2-2", "1", False),
    ]


def test_deleting_a_completed_run_removes_its_history(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    store._save(
        Run(
            id="completed-run",
            workflow_id="workflow",
            workflow_name="Workflow",
            status="succeeded",
            created_at=timestamp,
            updated_at=timestamp,
            finished_at=timestamp,
        )
    )

    store.delete_run("completed-run")

    assert not (store_module.RUNS / "completed-run.json").exists()


def test_active_evaluations_count_feedback_across_all_iterations(monkeypatch):
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    run = Run(
        id="feedback-history-run",
        workflow_id="workflow",
        workflow_name="Workflow",
        evaluation_build_id="build-one",
        execution_mode="run",
        execution_type="pipeline",
        status="succeeded",
        created_at=timestamp,
        updated_at=timestamp,
        supervisor_response={"improvements": [], "reported_issues": []},
        supervisor_results=[
            {
                "iteration": 1,
                "response": {
                    "improvements": [{"title": "Add refund intake", "status": "adopted"}],
                    "reported_issues": [{"title": "Missing refund details"}],
                },
            },
            {"iteration": 2, "response": {"improvements": [], "reported_issues": []}},
        ],
    )
    monkeypatch.setattr(store, "evaluation_builds", lambda: [{"id": "build-one", "approval_score": 8}])

    active = store.active_evaluations([run])

    assert active[0]["proposed_improvements"] == 1
    assert active[0]["approved_improvements"] == 1
    assert active[0]["reported_issues"] == 1


def test_transient_test_session_is_not_written_to_run_history(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    session = Run(
        id="test-session",
        workflow_id="workflow",
        workflow_name="Workflow",
        execution_mode="test",
        status="succeeded",
        created_at=timestamp,
        updated_at=timestamp,
        finished_at=timestamp,
    )
    store._test_sessions[session.id] = session

    store._save(session)

    assert store.test_session(session.id).id == session.id
    assert store.runs() == []
    assert not (store_module.RUNS / f"{session.id}.json").exists()

    store.discard_test_session(session.id)
    with pytest.raises(KeyError):
        store.test_session(session.id)


def test_runner_execution_plan_stops_when_its_run_phase_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNERS", tmp_path / "runners")
    store = store_module.ConsoleStore()
    store.create_runner(
        {
            "id": "failing-runner",
            "name": "Failing runner",
            "description": "A runner used to verify lifecycle failure handling.",
            "source": "from orbit_sdk import runner\n\n@runner.phase('run')\ndef run(ctx): pass\n",
        }
    )

    workflow = store._runner_execution_plan("failing-runner")

    assert workflow.steps_for("run")[0].on_failure == "stop"
    assert workflow.steps_for("test")[0].on_failure == "stop"


def test_v1_openapi_contract_documents_project_and_pipeline_resources():
    client = TestClient(app)
    schema = client.get("/api/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["version"] == "0.2.0"
    assert "/api/v1/projects" in schema.json()["paths"]
    assert "/api/v1/projects/{project_id}/pipelines" in schema.json()["paths"]
    assert "/api/v1/pipelines/{pipeline_id}/actions" in schema.json()["paths"]


def test_v1_openapi_contract_covers_control_room_assets_and_observability():
    schema = TestClient(app).get("/api/openapi.json").json()
    paths = schema["paths"]
    expected = {
        "/api/v1/runners",
        "/api/v1/runner-templates",
        "/api/v1/prompt-templates",
        "/api/v1/test-case-sets",
        "/api/v1/model-profiles",
        "/api/v1/application-settings",
        "/api/v1/workspaces",
        "/api/v1/dashboard",
        "/api/v1/logs",
        "/api/v1/improvements/analytics",
        "/api/v1/improvements/iterations",
        "/api/v1/improvements/proposals",
        "/api/v1/template-translations",
    }
    assert expected <= paths.keys()
    assert {"Projects", "Pipelines", "Observability", "Runners"} <= {tag["name"] for tag in schema["tags"]}


def test_template_translation_cache_only_accepts_display_text_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "TEMPLATE_TRANSLATIONS", tmp_path / "template-translations.json")
    store = store_module.ConsoleStore()
    source = {"name": "Browser journey validation", "description": "Checks browser journeys."}

    saved = store.save_template_translation(
        "runner-template",
        "browser-journey",
        "test-locale",
        source,
        {"name": "브라우저 여정 검증", "description": "브라우저 여정을 확인합니다."},
    )

    assert saved["name"] == "브라우저 여정 검증"
    assert (
        store.cached_template_translation("runner-template", "browser-journey", "test-locale", source)
        == saved
    )
    with pytest.raises(ValueError):
        store.save_template_translation(
            "runner-template", "browser-journey", "test-locale", source, {"name": "Only one field"}
        )


def test_v1_project_list_uses_gitlab_style_pagination_headers():
    response = TestClient(app).get("/api/v1/projects?page=1&per_page=1")
    assert response.status_code == 200
    assert response.headers["x-page"] == "1"
    assert response.headers["x-per-page"] == "1"
    assert "x-total" in response.headers
    assert "x-next-page" in response.headers
    assert "x-prev-page" in response.headers


def test_v1_read_only_control_room_resources_are_available():
    client = TestClient(app)
    for path in (
        "/api/v1/health",
        "/api/v1/runners",
        "/api/v1/prompt-templates",
        "/api/v1/test-case-sets",
        "/api/v1/model-profiles",
        "/api/v1/application-settings",
        "/api/v1/dashboard",
        "/api/v1/telemetry",
        "/api/v1/logs",
        "/api/v1/improvements",
        "/api/v1/improvements/proposals",
        "/api/v1/reported-issues",
    ):
        assert client.get(path).status_code == 200


def test_supervisor_result_requires_the_two_template_return_keys():
    assert store_module.ConsoleStore._validated_supervisor_result(
        '{"improvements": [], "reported_issues": []}'
    ) == {"improvements": [], "reported_issues": []}
    try:
        store_module.ConsoleStore._validated_supervisor_result('{"improvements": []}')
    except ValueError as error:
        assert "improvements and reported_issues" in str(error)
    else:
        raise AssertionError("invalid supervisor result was accepted")


def test_supervisor_result_normalizes_a_numeric_string_score():
    result = store_module.ConsoleStore._validated_supervisor_result(
        '{"evaluation":{"score":"8","approval":"pending","summary":"ok"},"improvements":[],"reported_issues":[]}'
    )
    assert result["evaluation"]["score"] == 8.0


def test_supervisor_result_accepts_a_structured_ai_behavior_trace():
    result = store_module.ConsoleStore._validated_supervisor_result(
        '{"evaluation":{"score":8,"approval":"pending","summary":"ok","behavior_trace":'
        '{"purpose":"Verify recovery","rationale":"The prior attempt timed out","observation":"A retry completed",'
        '"decision":"The AI retried safely","next_action":"Check the resulting output"}},'
        '"improvements":[],"reported_issues":[]}'
    )
    assert result["evaluation"]["behavior_trace"]["purpose"] == "Verify recovery"


def test_supervisor_result_rejects_an_incomplete_behavior_trace():
    try:
        store_module.ConsoleStore._validated_supervisor_result(
            '{"evaluation":{"score":8,"approval":"pending","summary":"ok",'
            '"behavior_trace":{"purpose":"Only one field"}},"improvements":[],"reported_issues":[]}'
        )
    except ValueError as error:
        assert "behavior_trace" in str(error)
    else:
        raise AssertionError("incomplete behavior trace was accepted")


def test_native_improvement_cycle_evidence_triggers_supervision():
    class RunRecord:
        step_results = [
            {
                "phase": "run",
                "result": {"improvement_cycle": {"candidate_fingerprint": "a" * 64}},
            }
        ]

    assert store_module.ConsoleStore._latest_cycle_has_persona_evidence(RunRecord()) is True


def test_supervision_includes_setup_managed_prompt_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    run = Run(
        id="managed-prompt-run",
        workflow_id="workflow",
        workflow_name="Workflow",
        supervisor_profile_name="Supervisor",
        prompt_snapshot="Evaluate the target.",
        status="running",
        created_at=timestamp,
        updated_at=timestamp,
        step_results=[
            {
                "phase": "setup",
                "loop_index": 1,
                "result": {"improvement_cycle": {"managed_prompt": {"content": "Prompt evidence"}}},
            },
            {
                "phase": "run",
                "loop_index": 1,
                "result": {"improvement_cycle": {"candidate_fingerprint": "a" * 64}},
            },
        ],
    )
    store._test_sessions[run.id] = run
    captured_prompts = []

    class FakeProvider:
        def complete(self, _settings, prompt):
            captured_prompts.append(prompt)
            return '{"improvements": [], "reported_issues": []}'

    monkeypatch.setattr(
        store,
        "profiles",
        lambda: [
            {
                "profile_name": "Supervisor",
                "provider": "azure-openai",
                "model": "test-model",
                "endpoint": "https://example.test/openai/v1",
                "region": "us-east-1",
                "secret_env": "AZURE_OPENAI_API_KEY",
                "aws_profile": "",
            }
        ],
    )
    monkeypatch.setattr(store_module, "AzureOpenAIProvider", FakeProvider)
    monkeypatch.setattr(store, "_review_cycle_improvement", lambda *_args: None)

    store._complete_supervision(run.id)

    assert len(captured_prompts) == 1
    assert '"phase": "setup"' in captured_prompts[0]
    assert "Prompt evidence" in captured_prompts[0]


def test_runner_context_uses_the_supplied_model_profile_without_exposing_its_secret(tmp_path, monkeypatch):
    resources = {
        "model_profile": {
            "profile_name": "Target AI",
            "provider": "azure-openai",
            "model": "test-model",
            "endpoint": "https://example.test/openai/v1",
            "secret_env": "TARGET_AI_KEY",
        }
    }
    context = RunnerContext(
        "run",
        tmp_path,
        "run",
        1,
        environment={
            "ORBIT_RUNNER_RESOURCES": base64.b64encode(json.dumps(resources).encode()).decode(),
            "TARGET_AI_KEY": "not-in-evidence",
        },
    )

    class FakeProvider:
        def complete(self, settings, prompt):
            assert settings.secret_env == "TARGET_AI_KEY"
            assert prompt == "Reply to this request"
            return "Observed target response"

    monkeypatch.setattr(providers, "AzureOpenAIProvider", FakeProvider)

    assert context.complete_model("Reply to this request") == {
        "profile_name": "Target AI",
        "model": "test-model",
        "response": "Observed target response",
    }


def test_direct_browser_and_site_exploration_evidence_trigger_supervision():
    class BrowserRun:
        step_results = [{"phase": "run", "result": {"browser_journey": {"results": [{"passed": True}]}}}]

    class SiteRun:
        step_results = [{"phase": "run", "result": {"site_exploration": {"evidence": {"visited": [{}]}}}}]

    assert store_module.ConsoleStore._latest_cycle_has_persona_evidence(BrowserRun()) is True
    assert store_module.ConsoleStore._latest_cycle_has_persona_evidence(SiteRun()) is True


def test_runner_templates_separate_direct_user_journeys_from_external_commands():
    templates = {item["id"]: item for item in store_module.ConsoleStore.runner_templates()}
    user_journey = templates["user-journey-cycle"]["source"]
    adapter = templates["external-command-adapter"]["source"]
    improvement = templates["native-improvement-cycle"]["source"]
    json_agent = templates["json-agent-cycle"]["source"]
    probe_gate = templates["evidence-gated-probe-cycle"]["source"]
    compile(user_journey, "user-journey-cycle.py", "exec")
    compile(adapter, "external-command-adapter.py", "exec")
    compile(improvement, "native-improvement-cycle.py", "exec")
    compile(json_agent, "json-agent-cycle.py", "exec")
    compile(probe_gate, "evidence-gated-probe-cycle.py", "exec")
    assert "playwright_journey" in user_journey
    assert "ORBIT_ADAPTER_COMMAND" not in user_journey
    assert "previous_supervisor_feedback" in user_journey
    assert "user-journey-state" in user_journey
    assert "ORBIT_ADAPTER_COMMAND" in adapter
    assert "playwright_journey" not in improvement
    assert "complete_model" in improvement
    assert "target_ai_responses" in improvement
    assert "ORBIT_CYCLE_COMMAND" not in improvement
    assert "run_paired_improvement_cycle" not in improvement
    assert "update_prompt_from_accepted_proposals" in improvement
    assert "ctx.accept_proposal" not in improvement
    assert "ctx.update_file" in improvement
    assert "managed_prompt_evidence" in improvement
    assert "record_proposal_application" in improvement
    assert "no_accepted_proposals" in improvement
    assert "ORBIT_AGENT_COMMAND" in json_agent
    assert "ORBIT_PROBE_COMMAND" in probe_gate
    assert "Insighta" not in json_agent
    assert "Jgent" not in json_agent
    assert "Insighta" not in probe_gate
    assert "Jgent" not in probe_gate


def test_site_exploration_quick_start_uses_the_langgraph_runner():
    store = store_module.ConsoleStore()
    quick_start = next(
        item for item in store._built_in_quick_starts() if item["id"] == "openorbit.site-exploration-review"
    )
    runner = quick_start["assets"]["runner"]
    assert "LangGraph" in quick_start["description"]
    assert runner["template_id"] == "site-exploration"
    assert "StateGraph" in runner["source"]
    assert "logout|signout|delete" in runner["source"]


def test_ai_slo_drift_quick_start_uses_a_recurring_evidence_gate():
    store = store_module.ConsoleStore()
    quick_start = next(
        item for item in store._built_in_quick_starts() if item["id"] == "openorbit.ai-slo-drift-monitor"
    )
    runner = quick_start["assets"]["runner"]
    execution = quick_start["assets"]["execution_environment"]

    assert quick_start["build"]["repeat_interval_minutes"] == 1440
    assert quick_start["build"]["run_limit"] == 30
    assert runner["template_id"] == "evidence-gated-probe-cycle"
    assert "playwright" not in runner["source"].lower()
    assert execution["environment_variables"] == {"ORBIT_PROBE_COMMAND": "${probe_command}"}
    assert "baseline" in quick_start["assets"]["prompt_template"]["content"]


def test_ai_slo_drift_quick_start_persists_its_evaluator_command(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "CONFIG", tmp_path)
    monkeypatch.setattr(store_module, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(store_module, "RUNNERS", tmp_path / "runners")
    monkeypatch.setattr(store_module, "RUNNER_TEMPLATES", tmp_path / "runner-templates")
    monkeypatch.setattr(store_module, "QUICK_STARTS", tmp_path / "quick-starts")
    monkeypatch.setattr(store_module, "QUICK_START_INSTANCES", tmp_path / "quick-start-instances.yaml")
    monkeypatch.setattr(store_module, "EXECUTION_ENVIRONMENTS", tmp_path / "execution-environments.yaml")
    monkeypatch.setattr(store_module, "TARGET_ENVIRONMENTS", tmp_path / "target-environments.yaml")
    monkeypatch.setattr(store_module, "TARGET_TEST_CASE_SETS", tmp_path / "target-test-case-sets.yaml")
    store = store_module.ConsoleStore()

    created = store.instantiate_quick_start(
        "openorbit.ai-slo-drift-monitor",
        {
            "repository": str(tmp_path),
            "probe_command": "uv run ai-eval",
            "model": "gpt-4o",
        },
    )

    execution = store._execution_environment(created["generated"]["execution_environment_id"])
    assert execution["environment_variables"] == {"ORBIT_PROBE_COMMAND": "uv run ai-eval"}
    assert created["build"]["repeat_interval_minutes"] == 1440
    assert store.profiles()[-1]["endpoint"] == ""


def test_runner_templates_can_be_imported_into_app_data(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNER_TEMPLATES", tmp_path / "runner-templates")
    store = store_module.ConsoleStore()
    imported = store.create_runner_template(
        {
            "id": "shared-browser-check",
            "name": "Shared browser check",
            "description": "A portable shared template.",
            "source": 'from orbit_sdk import runner\n\nif __name__ == "__main__": runner.main()\n',
        }
    )
    templates = {item["id"]: item for item in store.available_runner_templates()}
    assert imported["origin"] == "user"
    assert templates["shared-browser-check"]["source"] == imported["source"]
    assert (tmp_path / "runner-templates" / "shared-browser-check.json").exists()


def test_manager_prompt_template_can_be_updated(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "CONFIG", tmp_path)
    (tmp_path / "prompt-templates.yaml").write_text(
        "- id: manager-test-v1\n  name: Old\n  version: 1\n  content: old\n", encoding="utf-8"
    )
    template = store_module.ConsoleStore().update_prompt_template(
        "manager-test-v1", {"name": "Updated", "version": 2, "content": "new content"}
    )
    assert template == {
        "id": "manager-test-v1",
        "name": "Updated",
        "version": 2,
        "content": "new content",
        "versions": [{"version": 1, "content": "old"}, {"version": 2, "content": "new content"}],
    }


def test_target_test_case_sets_are_managed_as_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "TARGET_TEST_CASE_SETS", tmp_path / "target-ai-test-case-sets.yaml")
    store = store_module.ConsoleStore()
    values = {
        "id": "target-smoke-tests",
        "name": "Target smoke tests",
        "description": "A reusable target test set.",
        "cases": [
            {
                "id": "response-check",
                "name": "Response check",
                "prompt": "Reply with evidence.",
                "acceptance": "Evidence is present.",
            }
        ],
    }
    created = store.create_target_test_case_set(values)
    assert created["id"] == "target-smoke-tests"
    updated = store.update_target_test_case_set(
        "target-smoke-tests", {**values, "name": "Updated target tests"}
    )
    assert updated["name"] == "Updated target tests"


def test_proposal_history_is_derived_from_evaluation_run_results(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    store._save(
        Run(
            id="run-1",
            workflow_id="workflow",
            workflow_name="Workflow",
            evaluation_build_id="build-1",
            evaluation_build_name="Build 1",
            status="succeeded",
            created_at=timestamp,
            updated_at=timestamp,
            step_results=[
                {
                    "loop_index": 2,
                    "data_files": [
                        {
                            "label": "Iteration evidence",
                            "filename": "evidence.json",
                            "path": "/tmp/orbit/evidence.json",
                            "relative_path": "evidence.json",
                        }
                    ],
                }
            ],
            supervisor_results=[
                {
                    "iteration": 2,
                    "recorded_at": "2026-01-01T00:00:00+00:00",
                    "response": {
                        "improvements": [
                            {"title": "Keep evidence", "target": "prompt", "status": "adopted"},
                            {"title": "Remove noise", "target": "runner", "status": "proposed"},
                        ],
                        "reported_issues": [],
                    },
                }
            ],
        )
    )
    lifecycle = store.proposal_lifecycles("build-1")
    assert [item["status"] for item in lifecycle] == ["accepted", "proposed"]
    assert {item["title"] for item in lifecycle} == {"Keep evidence", "Remove noise"}
    assert lifecycle[0]["data_files"] == [
        {
            "label": "Iteration evidence",
            "filename": "evidence.json",
            "path": "/tmp/orbit/evidence.json",
            "relative_path": "evidence.json",
        }
    ]
    assert store.improvement_iteration_data("build-1") == [
        {
            "evaluation_build_id": "build-1",
            "evaluation_build_name": "Build 1",
            "run_id": "run-1",
            "iteration": 2,
            "recorded_at": timestamp.isoformat(),
            "data_files": [
                {
                    "label": "Iteration evidence",
                    "filename": "evidence.json",
                    "path": "/tmp/orbit/evidence.json",
                    "relative_path": "evidence.json",
                }
            ],
        }
    ]


def test_hello_accepts_unsaved_profile_settings():
    response = TestClient(app).post(
        "/api/settings/hello",
        json={
            "profile_name": "Staging Azure",
            "provider": "azure-openai",
            "model": "",
            "endpoint": "",
            "region": "us-east-1",
            "secret_env": "AZURE_OPENAI_API_KEY",
        },
    )
    assert response.status_code == 409


def test_settings_save_and_select_multiple_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SETTINGS", tmp_path / "settings.json")
    store = store_module.ConsoleStore()
    common = {
        "provider": "azure-openai",
        "model": "gpt-test",
        "endpoint": "https://example.test",
        "region": "us-east-1",
        "secret_env": "AZURE_OPENAI_API_KEY",
    }
    store.save_settings({"profile_name": "Development", **common})
    active = store.save_settings({"profile_name": "Production", **common, "region": "ap-northeast-1"})
    assert active["profile_name"] == "Production"
    assert active["region"] == "ap-northeast-1"
    assert [item["profile_name"] for item in store.profiles()][-2:] == ["Development", "Production"]


def test_application_manager_prompt_is_separate_from_model_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SETTINGS", tmp_path / "settings.json")
    store = store_module.ConsoleStore()
    expected_prompt = (
        f"Operate with audit context.\n\n{store_module.MANAGER_PROMPT_SLOT}\n\n"
        f"{store_module.MANAGER_OUTPUT_LANGUAGE_SLOT}"
    )
    assert store.save_application_settings({"manager_prompt_template": "Operate with audit context."}) == {
        "manager_prompt_template": expected_prompt,
        "manager_output_locale": "en",
        "chat_model_profile_name": "",
        "assistant_tools": {
            "workspace_root": str(store_module.ROOT),
            "file_read_enabled": True,
            "file_search_enabled": True,
            "run_process_enabled": True,
            "terminal_enabled": True,
            "terminal_visible": True,
        },
    }
    store.save_settings(
        {
            "profile_name": "Development",
            "provider": "azure-openai",
            "model": "gpt-test",
            "endpoint": "https://example.test",
            "region": "us-east-1",
            "secret_env": "AZURE_OPENAI_API_KEY",
        }
    )
    assert store.application_settings()["manager_prompt_template"] == expected_prompt
    assert (
        store.save_application_settings(
            {
                "manager_prompt_template": "Operate with audit context.",
                "chat_model_profile_name": "Development",
            }
        )["chat_model_profile_name"]
        == "Development"
    )
    with pytest.raises(ValueError, match="does not exist"):
        store.save_application_settings(
            {
                "manager_prompt_template": "Operate with audit context.",
                "chat_model_profile_name": "Missing",
            }
        )
    with pytest.raises(ValueError, match="chat assistant"):
        store.delete_profile("Development")


def test_application_manager_prompt_has_a_safe_default(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SETTINGS", tmp_path / "settings.json")
    assert (
        "approval-first operations manager"
        in store_module.ConsoleStore().application_settings()["manager_prompt_template"]
    )


def test_exact_legacy_manager_prompt_is_migrated_but_custom_prompt_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SETTINGS", tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "application_settings": {
                    "manager_prompt_template": store_module.LEGACY_OPERATIONAL_MANAGER_PROMPT
                }
            }
        ),
        encoding="utf-8",
    )
    assert (
        store_module.ConsoleStore().application_settings()["manager_prompt_template"]
        == store_module.DEFAULT_OPERATIONAL_MANAGER_PROMPT
    )
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {"application_settings": {"manager_prompt_template": "Custom\n__ORBIT_MANAGER_AI_PROMPT__"}}
        ),
        encoding="utf-8",
    )
    assert (
        store_module.ConsoleStore()
        .application_settings()["manager_prompt_template"]
        .startswith("Custom\n__ORBIT_MANAGER_AI_PROMPT__")
    )


def test_manager_output_language_is_injected_into_the_assembled_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(store_module, "CONFIG", tmp_path / "config")
    store = store_module.ConsoleStore()
    store.save_application_settings({"manager_output_locale": "ja"})
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "prompt-templates.yaml").write_text(
        "- id: manager-default-v1\n  name: Default\n  version: 1\n  content: Assess evidence.\n",
        encoding="utf-8",
    )
    _, prompt = store._assembled_prompt({"manager_template_id": "manager-default-v1", "repository": "test"})
    assert "configured application language (ja)" in prompt
    assert store_module.MANAGER_OUTPUT_LANGUAGE_SLOT not in prompt
