import base64
import io
import json
import sys
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import orbit_sdk as sdk
import pytest
import yaml
from app import main as main_module
from app import providers
from app import store as store_module
from app.main import app
from app.models import Run, Step, Workflow
from fastapi.testclient import TestClient
from orbit_sdk import RunnerContext
from starlette.requests import Request


def test_health_is_available():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_bundled_directory_prefers_wheel_files_over_source_checkout(tmp_path):
    installed = tmp_path / "site-packages"
    source = tmp_path / "source"
    source_dist = source / "frontend" / "dist"
    source_dist.mkdir(parents=True)

    assert main_module.bundled_directory(Path("frontend") / "dist", (installed, source)) == source_dist

    installed_dist = installed / "frontend" / "dist"
    installed_dist.mkdir(parents=True)

    assert main_module.bundled_directory(Path("frontend") / "dist", (installed, source)) == installed_dist


def test_visual_runner_catalog_is_served_from_sdk_registry():
    response = TestClient(app).get("/api/visual-runners/catalog")

    assert response.status_code == 200
    catalog = response.json()
    assert any(node["kind"] == "custom_script" for node in catalog["nodes"])
    assert catalog["starters"] == []
    assert all(node["group_key"] != "templates" for node in catalog["nodes"])


def test_system_readiness_reports_missing_system_ai_and_git(monkeypatch):
    monkeypatch.setattr(
        main_module.store,
        "application_settings",
        lambda: {"chat_model_profile_name": ""},
    )
    monkeypatch.setattr(main_module.store, "profiles", lambda: [])
    monkeypatch.setattr(main_module.shutil, "which", lambda _: None)

    response = TestClient(app).get("/api/system/readiness")

    assert response.status_code == 200
    assert response.json() == {
        "ready": False,
        "checks": [
            {
                "id": "system_ai",
                "status": "blocked",
                "detail": "profile_not_selected",
                "settings_page": "settings",
            },
            {"id": "git", "status": "blocked", "detail": "not_installed", "settings_page": None},
        ],
    }


def test_mcp_server_exposes_openapi_backed_control_room_tools():
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "openorbit-test", "version": "1"},
        },
    }
    with TestClient(app, base_url="http://localhost:3000") as client:
        connected = client.post("/mcp/", headers=headers, json=initialize)
        assert connected.status_code == 200
        session_id = connected.headers["mcp-session-id"]
        session_headers = {**headers, "mcp-session-id": session_id}

        tools = client.post(
            "/mcp/",
            headers=session_headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        resources = client.post(
            "/mcp/",
            headers=session_headers,
            json={"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
        )

    assert tools.status_code == 200
    assert '"name":"get_status"' in tools.text
    assert '"name":"start_pipeline"' in tools.text
    assert '"name":"act_on_pipeline"' in tools.text
    assert resources.status_code == 200
    assert "openorbit://openapi" in resources.text


def test_request_locale_prefers_the_browser_accept_language_priority():
    request = Request(
        {
            "type": "http",
            "headers": [(b"accept-language", b"ja;q=0.6, ko-KR;q=0.9, en;q=0.8")],
        }
    )

    assert main_module.request_locale(request) == "ko-KR"


def test_generated_sdk_docs_are_served_from_the_local_app(tmp_path, monkeypatch):
    docs = tmp_path / "site" / "sdk"
    docs.mkdir(parents=True)
    (docs / "index.html").write_text("<h1>SDK reference</h1>", encoding="utf-8")
    monkeypatch.setattr(main_module, "SDK_DOCS_DIST", docs.parent)

    response = TestClient(app).get("/sdk-docs/sdk/")

    assert response.status_code == 200
    assert "SDK reference" in response.text


def test_diagnostic_store_does_not_recover_an_active_pipeline(tmp_path, monkeypatch):
    """A second store process must not cancel the API server's live run."""
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    timestamp = store_module.now()
    owner = store_module.ConsoleStore()
    owner._save(
        Run(
            id="active-run",
            workflow_id="workflow",
            workflow_name="Workflow",
            status="running",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )

    diagnostic = store_module.ConsoleStore()

    assert diagnostic.run("active-run").status == "running"

    recovering_server = store_module.ConsoleStore(recover_interrupted_runs=True)

    assert recovering_server.run("active-run").status == "cancelled"
    assert recovering_server.run("active-run").step_results[-1]["step_id"] == "orbit-restart"


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
        "@runner.phase('execute')\n"
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
            phase="execute",
            name="Run",
            command=[sys.executable, str(runner), "--phase", "execute"],
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
    assert all(entry["iteration"] == 3 and entry["phase"] == "execute" for entry in step["target_logs"])


def test_runner_exec_can_forward_child_output_to_target_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    project = tmp_path / "target"
    project.mkdir()
    runner = project / "runner.py"
    runner.write_text(
        "import sys\n"
        "from orbit_sdk import runner\n"
        "@runner.phase('execute')\n"
        "def run(ctx):\n"
        "    ctx.exec([sys.executable, '-c', \"import sys; print(sys.stdin.read()); print('adapter ready'); print('__ORBIT_ADAPTER_RESULT__{\\\"ok\\\": true}')\"], input='adapter input', target_log_source='test-adapter', target_log_exclude_prefixes=('__ORBIT_ADAPTER_RESULT__',))\n"
        "if __name__ == '__main__': runner.main()\n",
        encoding="utf-8",
    )
    timestamp = store_module.now()
    store = store_module.ConsoleStore()
    store._save(
        Run(
            id="forwarded-target-log-run",
            workflow_id="workflow",
            workflow_name="Workflow",
            repository=str(project),
            status="running",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )

    store._execute_step(
        "forwarded-target-log-run",
        Step(
            id="run",
            phase="execute",
            name="Run",
            command=[sys.executable, str(runner), "--phase", "execute"],
            working_directory=str(project),
        ),
        loop_index=1,
    )

    step = store._load("forwarded-target-log-run").step_results[-1]
    assert "adapter ready" in step["output"]
    assert [(entry["source"], entry["message"]) for entry in step["target_logs"]] == [
        ("test-adapter", "adapter input"),
        ("test-adapter", "adapter ready"),
    ]
    assert "__ORBIT_ADAPTER_RESULT__" in step["output"]
    assert "adapter input" in step["output"]


def test_running_workflow_function_is_retained_before_its_step_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    project = tmp_path / "target"
    project.mkdir()
    runner = project / "runner.py"
    runner.write_text(
        "import time\n"
        "from orbit_sdk import runner\n"
        "@runner.phase('execute')\n"
        "def run(ctx):\n"
        "    with ctx.function('collect-source-evidence'):\n"
        "        time.sleep(1)\n"
        "if __name__ == '__main__': runner.main()\n",
        encoding="utf-8",
    )
    timestamp = store_module.now()
    store = store_module.ConsoleStore()
    store._save(
        Run(
            id="live-function-run",
            workflow_id="workflow",
            workflow_name="Workflow",
            repository=str(project),
            status="running",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    step = Step(
        id="run",
        phase="execute",
        name="Run",
        command=[sys.executable, str(runner), "--phase", "execute"],
        working_directory=str(project),
    )

    thread = threading.Thread(target=store._execute_step, args=("live-function-run", step, 1))
    thread.start()
    for _ in range(20):
        results = store._load("live-function-run").step_results
        if results and results[-1].get("result", {}).get("workflow_functions"):
            break
        time.sleep(0.1)
    thread.join()

    assert results[-1]["result"]["workflow_functions"][0]["status"] == "running"


def test_runner_data_files_are_retained_for_the_iteration(tmp_path, monkeypatch):
    app_data = tmp_path / "orbit-data"
    monkeypatch.setattr(store_module, "APP_DATA", app_data)
    monkeypatch.setattr(store_module, "RUNS", app_data / "data" / "runs")
    project = tmp_path / "target"
    project.mkdir()
    runner = project / "runner.py"
    runner.write_text(
        "from orbit_sdk import runner\n"
        "@runner.phase('execute')\n"
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
            phase="execute",
            name="Run",
            command=[sys.executable, str(runner), "--phase", "execute"],
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
        json.dumps({"build": {"managed_prompt_path": "prompt.md"}}).encode()
    ).decode()
    update = RunnerContext(
        phase="before_each",
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
                    "phase": "before_each",
                    "loop_index": 1,
                    "ended_at": timestamp.isoformat(),
                    "result": {"file_update": update},
                },
                {
                    "phase": "before_each",
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
            Step(id="setup", phase="before_each", name="Setup", command=[], working_directory="."),
            Step(id="teardown", phase="after_each", name="Teardown", command=[], working_directory="."),
        ],
    )
    monkeypatch.setattr(store, "_runner_execution_plan", lambda _: workflow)
    calls = []

    def execute_step(run_id, step, loop_index=1, resources=None, *, allow_terminal=False):
        calls.append((step.phase, loop_index, allow_terminal))
        if step.phase == "before_each":
            current = store._load(run_id)
            current.status = terminal_status
            store._save(current)

    monkeypatch.setattr(store, "_execute_step", execute_step)

    store._execute(run.id)

    assert calls == [("before_each", 1, False), ("after_each", 1, True)]


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
            Step(id="setup", phase="before_each", name="Setup", command=[], working_directory="."),
            Step(id="finalize", phase="after_all", name="Finalize", command=[], working_directory="."),
        ],
    )
    monkeypatch.setattr(store, "_runner_execution_plan", lambda _: workflow)
    calls = []

    def execute_step(run_id, step, loop_index=1, resources=None, *, allow_terminal=False):
        calls.append((step.phase, loop_index, allow_terminal))
        if step.phase == "before_each":
            current = store._load(run_id)
            current.status = terminal_status
            store._save(current)

    monkeypatch.setattr(store, "_execute_step", execute_step)

    store._execute(run.id)

    assert calls == [("before_each", 1, False), ("after_all", 2, True)]


def test_native_improvement_template_uses_repository_snapshot_lifecycle():
    source = next(
        item["source"]
        for item in store_module.ConsoleStore.runner_templates()
        if item["id"] == "native-improvement-cycle"
    )

    from orbit_sdk.visual.builtin_templates import templates

    canonical = templates()["runner-templates:native-improvement-cycle"].source.read_text(encoding="utf-8")
    assert "template_runner_templates_native_improvement_cycle_" in source
    assert "ctx.save_before_each_snapshot()" in canonical
    assert "ctx.save_first_after_each_snapshot()" in canonical
    assert "ctx.restore_before_each_snapshot()" in canonical


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
        steps=[Step(id="run", phase="execute", name="Run", command=[], working_directory=".")],
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


def test_linear_runs_complete_supervision_after_each_iteration(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    run = Run(
        id="linear-supervision",
        workflow_id="workflow",
        workflow_name="Workflow",
        execution_mode="run",
        status="queued",
        created_at=timestamp,
        updated_at=timestamp,
        loop_limit=2,
        iteration_strategy="linear",
    )
    store._save(run)
    workflow = Workflow(
        id="workflow",
        name="Workflow",
        description="",
        kind="simulation",
        risk="low",
        steps=[Step(id="verify", phase="verify", name="Verify", command=[], working_directory=".")],
    )
    monkeypatch.setattr(store, "_runner_execution_plan", lambda _: workflow)
    completed_iterations = []

    def execute_step(run_id, step, loop_index=1, resources=None, **_kwargs):
        current = store._load(run_id)
        current.step_results.append({"phase": step.phase, "loop_index": loop_index})
        store._save(current)

    def supervise(run_id):
        completed_iterations.append(store._load(run_id).step_results[-1]["loop_index"])

    monkeypatch.setattr(store, "_execute_step", execute_step)
    monkeypatch.setattr(store, "_complete_supervision", supervise)

    store._execute(run.id)

    assert completed_iterations == [1, 2]


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


def test_completed_pipeline_run_can_be_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    store._save(
        Run(
            id="completed-run",
            workflow_id="workflow",
            workflow_name="Workflow",
            execution_type="pipeline",
            status="succeeded",
            created_at=timestamp,
            updated_at=timestamp,
            finished_at=timestamp,
            step_results=[{"step_id": "execute", "loop_index": 1, "output": "previous output"}],
            supervisor_results=[{"iteration": 1, "response": {"evaluation": {"score": 8}}}],
            runner_output="previous runner output",
        )
    )
    monkeypatch.setattr(
        store, "_runner_execution_plan", lambda runner_id: SimpleNamespace(id=runner_id, name="Workflow")
    )
    monkeypatch.setattr(store, "_runner_graph_definition", lambda *_: None)
    monkeypatch.setattr(store, "_start", lambda _: None)

    retried = store.retry("completed-run", restart_from_first=True)

    assert retried.id == "completed-run"
    assert retried.retry_of_run_id is None
    assert retried.retry_mode == "restart"
    assert retried.status == "queued"
    assert retried.step_results == []
    assert retried.supervisor_results == []
    assert retried.runner_output == ""


def test_active_evaluations_count_feedback_across_all_iterations(monkeypatch):
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    run = Run(
        id="feedback-history-run",
        workflow_id="workflow",
        workflow_name="Workflow",
        build_id="build-one",
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
                    "improvements": [{"title": "Add refund intake", "status": "accepted"}],
                    "reported_issues": [{"title": "Missing refund details"}],
                },
            },
            {"iteration": 2, "response": {"improvements": [], "reported_issues": []}},
        ],
    )
    monkeypatch.setattr(store, "builds", lambda: [{"id": "build-one", "approval_score": 8}])

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
            "source": "from orbit_sdk import runner\n\n@runner.phase('execute')\ndef run(ctx): pass\n",
        }
    )

    workflow = store._runner_execution_plan("failing-runner")

    assert workflow.steps_for("run")[0].on_failure == "stop"
    assert workflow.steps_for("test")[0].on_failure == "stop"


def test_builtin_runner_template_creation_persists_its_visual_definition(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNERS", tmp_path / "runners")
    store = store_module.ConsoleStore()

    runner = store.create_runner(
        {
            "id": "json-cycle",
            "name": "JSON cycle",
            "description": "Template-backed visual runner.",
            "template_id": "json-agent-cycle",
            "source": "# source is replaced by the authoritative template definition\n",
        }
    )

    assert runner["visual_template_id"] == "runner-templates:json-agent-cycle"
    assert runner["visual_blueprint"]["nodes"]
    assert "ctx.run_visual_node('json_cycle_action'" in runner["source"]
    assert "ctx.run_visual_node('template_" not in runner["source"]

    detached = store.update_runner(
        runner["id"],
        {
            "name": runner["name"],
            "description": runner["description"],
            "source": "from orbit_sdk import runner\n@runner.phase('execute')\ndef run(ctx): pass\n",
        },
    )
    assert "visual_blueprint" not in detached
    assert "visual_template_id" not in detached


def test_runner_saves_immutable_versions_and_can_resolve_an_older_version(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNERS", tmp_path / "runners")
    store = store_module.ConsoleStore()
    initial = store.create_runner(
        {
            "id": "versioned-runner",
            "name": "Versioned runner",
            "description": "Keeps runner source revisions.",
            "source": "from orbit_sdk import runner\n@runner.phase('execute')\ndef run(ctx): pass\n",
        }
    )
    updated = store.update_runner(
        "versioned-runner",
        {
            "name": initial["name"],
            "description": initial["description"],
            "source": "from orbit_sdk import runner\n@runner.phase('verify')\ndef verify(ctx): ctx.log('v2')\n",
        },
    )

    assert initial["version"] == 1
    assert [item["version"] for item in initial["versions"]] == [1]
    assert [item["version"] for item in updated["versions"]] == [1, 2]
    assert store._runner_entry_path("versioned-runner", 1).read_text(encoding="utf-8") == initial["source"]
    assert "v2" in store._runner_entry_path("versioned-runner", 2).read_text(encoding="utf-8")
    assert [step.phase for step in store._runner_execution_plan("versioned-runner", 1).steps] == ["execute"]
    assert [step.phase for step in store._runner_execution_plan("versioned-runner", 2).steps] == ["verify"]


def test_direct_code_update_detaches_a_visual_runner_without_erasing_history(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNERS", tmp_path / "runners")
    store = store_module.ConsoleStore()
    blueprint = {
        "schema_version": 1,
        "nodes": [
            {
                "id": "collect",
                "kind": "custom_script",
                "title": "Collect",
                "phase": "execute",
                "inputs": [],
                "outputs": ["result"],
                "config": {},
                "script": "outputs['result'] = True",
                "position": {"x": 0, "y": 0},
            }
        ],
        "edges": [],
    }
    visual = store.create_runner(
        {
            "id": "visual-runner",
            "name": "Visual runner",
            "description": "A generated visual runner.",
            "source": "placeholder",
            "visual_blueprint": blueprint,
        }
    )
    updated = store.update_runner(
        "visual-runner",
        {
            "name": visual["name"],
            "description": visual["description"],
            "source": "from orbit_sdk import runner\n@runner.phase('execute')\ndef run(ctx): pass\n",
        },
    )

    assert visual["versions"][0]["visual_blueprint"]["schema_version"] == 1
    assert "visual_blueprint" not in updated
    assert "visual_blueprint" not in updated["versions"][-1]
    assert updated["versions"][0]["visual_blueprint"]["nodes"][0]["id"] == "collect"


def test_bundle_runner_updates_in_place_and_keeps_immutable_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNERS", tmp_path / "runners")
    bundle = store_module.RUNNERS / "bundle-runner"
    bundle.mkdir(parents=True)
    initial_source = "from orbit_sdk import runner\n@runner.phase('execute')\ndef run(ctx): pass\n"
    (bundle / "runner.py").write_text(initial_source, encoding="utf-8")
    (bundle / "runner.json").write_text(
        json.dumps({"id": "bundle-runner", "name": "Bundle", "description": "Versioned bundle."}),
        encoding="utf-8",
    )
    store = store_module.ConsoleStore()

    updated = store.update_runner(
        "bundle-runner",
        {
            "name": "Bundle",
            "description": "Versioned bundle.",
            "source": "from orbit_sdk import runner\n@runner.phase('verify')\ndef run(ctx): pass\n",
        },
    )

    assert updated["version"] == 2
    assert [item["version"] for item in updated["versions"]] == [1, 2]
    assert (bundle / "runner.py").read_text(encoding="utf-8") == updated["source"]
    assert not (store_module.RUNNERS / "bundle-runner.py").exists()
    assert [step.phase for step in store._runner_execution_plan("bundle-runner", 1).steps] == ["execute"]
    assert [step.phase for step in store._runner_execution_plan("bundle-runner", 2).steps] == ["verify"]


def test_legacy_external_runners_and_templates_migrate_target_log_forwarding(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNERS", tmp_path / "runners")
    monkeypatch.setattr(store_module, "RUNNER_TEMPLATES", tmp_path / "runner-templates")
    store_module.RUNNERS.mkdir()
    store_module.RUNNER_TEMPLATES.mkdir()

    legacy_adapter = (
        "from orbit_sdk import runner\n"
        "def invoke(ctx):\n"
        "    return ctx.exec(['adapter'], timeout=3600)\n"
        "@runner.phase('execute')\n"
        "def run(ctx): invoke(ctx)\n"
        "# ORBIT_ADAPTER_COMMAND\n"
    )
    legacy_probe = legacy_adapter.replace(
        "return ctx.exec(['adapter'], timeout=3600)",
        "return ctx.exec(\n        ['probe'],\n        timeout=3600,\n        env={},\n    )",
    ).replace("ORBIT_ADAPTER_COMMAND", "ORBIT_PROBE_COMMAND")
    internal_runner = (
        "from orbit_sdk import runner\n"
        "@runner.phase('execute')\n"
        "def run(ctx):\n"
        "    ctx.exec(['git', 'status'], timeout=3600)\n"
    )
    for runner_id, template_id, source in (
        ("legacy-adapter", "external-command-adapter", legacy_adapter),
        ("quick-start-probe", "evidence-gated-probe-cycle", legacy_probe),
        ("native-runner", "native-improvement-cycle", internal_runner),
    ):
        (store_module.RUNNERS / f"{runner_id}.py").write_text(source, encoding="utf-8")
        (store_module.RUNNERS / f"{runner_id}.json").write_text(
            json.dumps(
                {
                    "id": runner_id,
                    "name": runner_id,
                    "description": "Legacy runner.",
                    "template_id": template_id,
                    "version": 1,
                }
            ),
            encoding="utf-8",
        )
    template_source = legacy_adapter.replace("ORBIT_ADAPTER_COMMAND", "ORBIT_SELENIUM_COMMAND")
    (store_module.RUNNER_TEMPLATES / "selenium-external-journey.py").write_text(
        template_source, encoding="utf-8"
    )
    (store_module.RUNNER_TEMPLATES / "selenium-external-journey.json").write_text(
        json.dumps(
            {
                "id": "selenium-external-journey",
                "name": "Selenium",
                "description": "Legacy Selenium template.",
            }
        ),
        encoding="utf-8",
    )

    store = store_module.ConsoleStore()

    adapter = store._runner("legacy-adapter")
    probe = store._runner("quick-start-probe")
    assert adapter["version"] == 2
    assert [item["version"] for item in adapter["versions"]] == [1, 2]
    assert 'target_log_source="external-adapter"' in adapter["source"]
    assert 'target_log_source="evidence-probe"' in probe["source"]
    assert store._runner("native-runner")["version"] == 1
    assert "target_log_source" not in store._runner("native-runner")["source"]
    assert 'target_log_source="selenium-adapter"' in (
        store_module.RUNNER_TEMPLATES / "selenium-external-journey.py"
    ).read_text(encoding="utf-8")


def test_deleting_issue_management_items_hides_them_without_deleting_run_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "ISSUE_MANAGEMENT", tmp_path / "issue-management.yaml")
    store = store_module.ConsoleStore()
    proposal = {
        "proposal_id": "run-1:1:0",
        "title": "Retain evidence",
        "target": "prompt",
        "events": [],
    }
    monkeypatch.setattr(store, "proposal_lifecycles", lambda: [proposal])

    assert store.issue_management_items()[0]["proposal_id"] == proposal["proposal_id"]
    assert store.delete_issue_management_items([proposal["proposal_id"]]) == {"deleted": 1}
    assert store.issue_management_items() == []

    records = yaml.safe_load(store_module.ISSUE_MANAGEMENT.read_text(encoding="utf-8"))["items"]
    assert records[proposal["proposal_id"]]["status"] == "deleted"
    assert records[proposal["proposal_id"]]["events"][-1]["type"] == "deleted"
    assert store.delete_issue_management_items([proposal["proposal_id"]]) == {"deleted": 0}


def test_issue_management_exposes_an_agent_worktree_diff(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "ISSUE_MANAGEMENT", tmp_path / "issue-management.yaml")
    store = store_module.ConsoleStore()
    proposal = {
        "proposal_id": "run-1:1:agent",
        "proposal": {
            "kind": "agent_change",
            "changed_files": ["prompt.md"],
            "base_revision": "abc123",
            "diff": "diff --git a/prompt.md b/prompt.md\n",
        },
    }
    monkeypatch.setattr(store, "proposal_lifecycles", lambda: [proposal])

    assert store.issue_management_diff(proposal["proposal_id"]) == {
        "diff": "diff --git a/prompt.md b/prompt.md\n",
        "changed_files": ["prompt.md"],
        "base_revision": "abc123",
    }


def test_legacy_saved_runner_is_planned_with_canonical_phases(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNERS", tmp_path / "runners")
    store_module.RUNNERS.mkdir()
    (store_module.RUNNERS / "legacy.py").write_text(
        "from orbit_sdk import runner\n@runner.phase('run')\ndef run(ctx): pass\n",
        encoding="utf-8",
    )
    (store_module.RUNNERS / "legacy.json").write_text(
        json.dumps({"id": "legacy", "name": "Legacy", "description": "Pre-generic lifecycle runner"}),
        encoding="utf-8",
    )

    workflow = store_module.ConsoleStore()._runner_execution_plan("legacy")

    assert [step.phase for step in workflow.steps] == ["execute"]
    assert workflow.steps[0].command[-1] == "execute"


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


def test_cached_template_translation_endpoint_returns_only_existing_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "TEMPLATE_TRANSLATIONS", tmp_path / "template-translations.json")
    quick_start_id = "openorbit.user-journey-smoke-test"
    source = main_module.store.template_translation_input("quick-start", quick_start_id)
    main_module.store.save_template_translation("quick-start", quick_start_id, "ko", source, source)

    cached = TestClient(app).post(
        "/api/template-translations/cached",
        json={"kind": "quick-start", "template_id": quick_start_id, "locale": "ko"},
    )
    missing = TestClient(app).post(
        "/api/template-translations/cached",
        json={"kind": "quick-start", "template_id": quick_start_id, "locale": "ja"},
    )

    assert cached.status_code == 200
    assert cached.json() == {"content": source}
    assert missing.status_code == 200
    assert missing.json() == {"content": None}


def test_quick_start_translation_includes_placeholders_and_tooltips(monkeypatch):
    store = store_module.ConsoleStore()
    manifest = {
        "id": "example.translated-quick-start",
        "name": "Translated quick start",
        "description": "Checks translated form help.",
        "parameters": [
            {
                "key": "repository",
                "label": "Repository",
                "placeholder": "/absolute/path/to/repository",
                "tooltip": "The workspace that OpenOrbit inspects.",
            }
        ],
    }
    monkeypatch.setattr(store, "quick_starts", lambda: [manifest])

    source = store.template_translation_input("quick-start", manifest["id"])
    translated = store.validate_template_translation(
        source,
        {
            "name": "번역된 퀵스타트",
            "description": "번역된 폼 도움말을 확인합니다.",
            "parameters": [
                {
                    "label": "저장소",
                    "placeholder": "/절대/경로/저장소",
                    "tooltip": "OpenOrbit이 검사할 작업공간입니다.",
                }
            ],
        },
    )

    assert source["parameters"][0]["placeholder"] == "/absolute/path/to/repository"
    assert source["parameters"][0]["tooltip"] == "The workspace that OpenOrbit inspects."
    assert translated["parameters"][0]["placeholder"] == "/절대/경로/저장소"
    assert translated["parameters"][0]["tooltip"] == "OpenOrbit이 검사할 작업공간입니다."


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


def test_registered_agent_result_requires_a_supervisor_evaluation():
    with pytest.raises(ValueError, match="registered agent result"):
        store_module.ConsoleStore._validated_supervisor_result(
            '{"improvements": [], "reported_issues": []}', require_evaluation=True
        )


def test_evaluation_request_is_limited_to_the_matching_iteration_and_candidate():
    run = SimpleNamespace(
        step_results=[
            {
                "loop_index": 1,
                "candidate_id": "1-1",
                "result": {"evaluation_request": {"subject": "agent_change", "feedback": "Updated retry"}},
            },
            {
                "loop_index": 2,
                "candidate_id": "2-1",
                "result": {"evaluation_request": {"subject": "agent_change", "feedback": "Updated parser"}},
            },
        ]
    )

    assert store_module.ConsoleStore._evaluation_request_for_iteration(run, 2, "2-1") == {
        "subject": "agent_change",
        "feedback": "Updated parser",
        "changed_files": [],
        "validation": "",
    }
    assert store_module.ConsoleStore._evaluation_request_for_iteration(run, 2, "2-2") is None


def test_supervisor_result_normalizes_a_numeric_string_score():
    result = store_module.ConsoleStore._validated_supervisor_result(
        '{"evaluation":{"score":"8","approval":"pending","summary":"ok"},"improvements":[],"reported_issues":[]}'
    )
    assert result["evaluation"]["score"] == 8.0


def test_supervisor_result_accepts_supervisor_observed_persona_journeys():
    result = store_module.ConsoleStore._validated_supervisor_result(
        '{"persona_journeys":[{"persona_id":"jp_nisa_beginner","behavior_trace":'
        '{"persona_goal":"Understand my NISA portfolio",'
        '"current_action":"I checked the rendered holdings",'
        '"decision":"I did not record a trade while the values disagree",'
        '"next_action":"I will verify the displayed allocation",'
        '"evidence":"The visible ACWI holding is zero"}}],'
        '"improvements":[],"reported_issues":[]}'
    )
    assert result["persona_journeys"][0]["persona_id"] == "jp_nisa_beginner"


def test_supervisor_result_accepts_a_persona_journey_trace():
    result = store_module.ConsoleStore._validated_supervisor_result(
        '{"evaluation":{"score":8,"approval":"pending","summary":"ok","behavior_trace":'
        '{"persona_goal":"I want to confirm my account is usable",'
        '"current_action":"I checked whether my balance and holdings agree",'
        '"decision":"I decided not to make a change while they disagree",'
        '"next_action":"I will wait for the balance, then check my holdings",'
        '"evidence":"The visible balance is still loading"}},'
        '"improvements":[],"reported_issues":[]}'
    )
    assert (
        result["evaluation"]["behavior_trace"]["current_action"]
        == "I checked whether my balance and holdings agree"
    )


def test_supervisor_result_accepts_a_compact_persona_trace_for_existing_runs():
    result = store_module.ConsoleStore._validated_supervisor_result(
        '{"evaluation":{"score":8,"approval":"pending","summary":"ok","behavior_trace":'
        '{"persona_goal":"I want to confirm my account is usable",'
        '"current_action":"I decided to wait for the balance",'
        '"next_action":"I will check my holdings",'
        '"evidence":"The visible balance is still loading"}},'
        '"improvements":[],"reported_issues":[]}'
    )
    assert result["evaluation"]["behavior_trace"]["current_action"] == "I decided to wait for the balance"


def test_supervisor_result_accepts_an_expanded_persona_trace_for_existing_runs():
    result = store_module.ConsoleStore._validated_supervisor_result(
        '{"evaluation":{"score":8,"approval":"pending","summary":"ok","behavior_trace":'
        '{"persona_goal":"Confirm the account is usable","expectation":"A visible balance",'
        '"interpretation":"I cannot confirm my balance yet","evidence":"The balance is still loading",'
        '"impact":"I cannot safely continue","next_step":"Wait for the balance, then check the holdings"}},'
        '"improvements":[],"reported_issues":[]}'
    )
    assert result["evaluation"]["behavior_trace"]["interpretation"] == "I cannot confirm my balance yet"


def test_supervisor_result_accepts_a_legacy_behavior_trace_for_existing_runs():
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
                "phase": "execute",
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
                "phase": "before_each",
                "loop_index": 1,
                "result": {"improvement_cycle": {"managed_prompt": {"content": "Prompt evidence"}}},
            },
            {
                "phase": "execute",
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
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(store_module, "AzureOpenAIProvider", FakeProvider)
    monkeypatch.setattr(store, "_review_cycle_improvement", lambda *_args: None)

    store._complete_supervision(run.id)

    assert len(captured_prompts) == 1
    assert '"phase": "before_each"' in captured_prompts[0]
    assert "Prompt evidence" in captured_prompts[0]


def test_supervision_reuses_known_unresolved_issue_without_creating_another_row(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    run = Run(
        id="known-issue-run",
        workflow_id="workflow",
        workflow_name="Workflow",
        supervisor_profile_name="Supervisor",
        prompt_snapshot="Evaluate the target.",
        status="running",
        created_at=timestamp,
        updated_at=timestamp,
        step_results=[{"phase": "execute", "loop_index": 2, "result": {"persona_cycle": {}}}],
        supervisor_results=[
            {
                "iteration": 1,
                "stage": "issue_assessment",
                "response": {
                    "improvements": [
                        {
                            "title": "Portfolio calculation basis is unclear",
                            "rationale": "Users cannot verify the displayed value.",
                            "status": "proposed",
                        }
                    ],
                    "reported_issues": [],
                },
            }
        ],
    )
    store._save(run)
    captured_prompts = []

    class FakeProvider:
        def complete(self, _settings, prompt):
            captured_prompts.append(prompt)
            return json.dumps(
                {
                    "improvements": [
                        {
                            "known_issue_id": "known-issue-run:1:0",
                            "evidence": "The basis is still absent in this iteration.",
                            "evaluation": {"score": 7, "approval": "pending", "summary": "Known issue."},
                        }
                    ],
                    "reported_issues": [],
                }
            )

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
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(store_module, "AzureOpenAIProvider", FakeProvider)
    monkeypatch.setattr(store, "_review_cycle_improvement", lambda *_args: None)

    store._complete_supervision(run.id)

    assert "# Known unresolved issues" in captured_prompts[0]
    assert "known-issue-run:1:0" in captured_prompts[0]
    assert [item["title"] for item in store.proposal_lifecycles()] == [
        "Portfolio calculation basis is unclear"
    ]


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
        step_results = [{"phase": "execute", "result": {"browser_journey": {"results": [{"passed": True}]}}}]

    class SiteRun:
        step_results = [{"phase": "execute", "result": {"site_exploration": {"evidence": {"visited": [{}]}}}}]

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
    assert "@runner.phase" in user_journey
    assert "orbit_runner_kit" not in user_journey
    assert "ORBIT_ADAPTER_COMMAND" not in user_journey
    from orbit_sdk.visual.builtin_templates import templates as canonical_templates

    canonical = canonical_templates()
    adapter_source = canonical["runner-templates:external-command-adapter"].source.read_text(encoding="utf-8")
    improvement_source = canonical["runner-templates:native-improvement-cycle"].source.read_text(
        encoding="utf-8"
    )
    assert "template_runner_templates_external_command_adapter_" in adapter
    assert "ORBIT_ADAPTER_COMMAND" in adapter_source
    assert "playwright_journey" not in improvement_source
    assert "complete_model" in improvement_source
    assert "target_ai_responses" in improvement_source
    assert "ORBIT_CYCLE_COMMAND" not in improvement_source
    assert "run_paired_improvement_cycle" not in improvement_source
    assert "update_prompt_from_accepted_proposals" in improvement_source
    assert "ctx.accept_proposal" not in improvement_source
    assert "ctx.update_file" in improvement_source
    assert "managed_prompt_evidence" in improvement_source
    assert "record_proposal_application" in improvement_source
    assert "no_accepted_proposals" in improvement_source
    assert "ORBIT_AGENT_COMMAND" in canonical["runner-templates:json-agent-cycle"].source.read_text(
        encoding="utf-8"
    )
    assert "ORBIT_PROBE_COMMAND" in canonical["runner-templates:evidence-gated-probe-cycle"].source.read_text(
        encoding="utf-8"
    )
    assert "Insighta" not in json_agent
    assert "Jgent" not in json_agent
    assert "Insighta" not in probe_gate
    assert "Jgent" not in probe_gate


def test_site_exploration_quick_start_declares_its_lifecycle():
    store = store_module.ConsoleStore()
    quick_start = next(
        item for item in store._built_in_quick_starts() if item["id"] == "openorbit.site-exploration-review"
    )
    runner = quick_start["assets"]["runner"]
    assert "LangGraph" in quick_start["description"]
    assert runner["template_id"] == "site-exploration"
    assert "@runner.phase" in runner["source"]
    assert "orbit_runner_kit" not in runner["source"]
    from orbit_sdk.visual.builtin_templates import templates

    assert "template_quick_starts_openorbit_site_exploration_review_" in runner["source"]
    assert "logout|signout|delete" in templates()[
        "quick-starts:openorbit.site-exploration-review"
    ].source.read_text(encoding="utf-8")


def test_quick_start_workflow_graph_can_be_previewed_before_creation(monkeypatch):
    store = store_module.ConsoleStore()
    captured = {}
    expected = {"nodes": [{"id": "start"}], "edges": []}

    def preview(source):
        captured["source"] = source
        return expected

    monkeypatch.setattr(store, "preview_runner_graph", preview)

    assert store.preview_quick_start_graph("openorbit.agent-self-improvement") == expected
    assert "@runner.phase" in captured["source"]


def test_shipped_template_graphs_are_previewable_with_unique_nodes():
    """Every shipped template publishes a valid graph for node-based execution."""
    store = store_module.ConsoleStore()
    sources = [item["source"] for item in store.runner_templates()]
    sources.extend(item["assets"]["runner"]["source"] for item in store._built_in_quick_starts())

    for source in sources:
        definition = store.preview_runner_graph(source)
        assert definition is not None
        nodes = definition["nodes"]
        assert nodes
        assert len({node["id"] for node in nodes}) == len(nodes)
        assert all(node["phase"] for node in nodes)


def test_saved_runner_graph_preview_uses_the_selected_version(monkeypatch):
    store = store_module.ConsoleStore()
    expected = {"nodes": [{"id": "start"}], "edges": []}
    captured = {}

    def preview(runner_id, repository, runner_version=None):
        captured.update(runner_id=runner_id, repository=repository, runner_version=runner_version)
        return expected

    monkeypatch.setattr(store, "_runner_graph_definition", preview)

    assert store.runner_graph_preview("runner-id", 5) == expected
    assert captured == {"runner_id": "runner-id", "repository": None, "runner_version": 5}


def test_runner_graph_draft_is_previewed_by_id(monkeypatch):
    store = store_module.ConsoleStore()
    captured = {}
    expected = {"nodes": [{"id": "draft"}], "edges": []}

    def preview(source):
        captured["source"] = source
        return expected

    monkeypatch.setattr(store, "preview_runner_graph", preview)
    draft = store.create_runner_graph_draft("from orbit_sdk import runner\n")

    assert store.preview_runner_graph_draft(draft["id"]) == expected
    assert captured["source"] == "from orbit_sdk import runner\n"


@pytest.mark.parametrize(
    ("quick_start_id", "phases"),
    [
        (
            "openorbit.user-journey-smoke-test",
            ["before_all", "before_all", "execute", "verify", "after_all"],
        ),
        ("openorbit.site-exploration-review", ["before_all", "execute", "verify", "after_all"]),
        (
            "openorbit.agent-self-improvement",
            [
                "before_all",
                "before_all",
                "before_each",
                "execute",
                "after_each",
                "after_each",
            ],
        ),
        (
            "openorbit.ai-slo-drift-monitor",
            ["before_all", "before_all", "before_each", "execute", "verify", "after_each", "after_all"],
        ),
    ],
)
def test_quick_start_runner_graph_matches_its_execution_purpose(monkeypatch, quick_start_id, phases):
    store = store_module.ConsoleStore()
    quick_start = next(item for item in store._built_in_quick_starts() if item["id"] == quick_start_id)
    monkeypatch.setattr(sdk, "graph", sdk.Graph())

    exec(
        compile(quick_start["assets"]["runner"]["source"], quick_start_id, "exec"),
        {"__name__": quick_start_id},
    )

    definition = sdk.graph.definition()
    assert [node["phase"] for node in definition["nodes"]] == phases
    assert definition["edges"]


@pytest.mark.parametrize(
    ("template_id", "phases"),
    [
        (
            "user-journey-cycle",
            [
                "before_all",
                "before_all",
                "before_each",
                "before_each",
                "execute",
                "verify",
                "after_each",
                "after_all",
            ],
        ),
        (
            "external-command-adapter",
            ["before_all", "before_all", "before_each", "execute", "verify", "after_each", "after_all"],
        ),
        (
            "native-improvement-cycle",
            [
                "before_all",
                "before_all",
                "before_each",
                "before_each",
                "execute",
                "verify",
                "after_each",
                "after_all",
            ],
        ),
        ("site-exploration", ["before_all", "execute", "verify", "after_all"]),
        (
            "source-aware-browser-journey",
            ["before_all", "execute", "verify", "after_each", "after_all"],
        ),
        (
            "json-agent-cycle",
            ["before_all", "before_all", "before_each", "execute", "verify", "after_each", "after_all"],
        ),
        (
            "evidence-gated-probe-cycle",
            ["before_all", "before_all", "before_each", "execute", "verify", "after_each", "after_all"],
        ),
    ],
)
def test_runner_templates_publish_a_lifecycle_graph(monkeypatch, template_id, phases):
    source = next(
        template["source"]
        for template in store_module.ConsoleStore.runner_templates()
        if template["id"] == template_id
    )
    monkeypatch.setattr(sdk, "graph", sdk.Graph())

    exec(compile(source, template_id, "exec"), {"__name__": template_id})

    definition = sdk.graph.definition()
    assert [node["phase"] for node in definition["nodes"]] == phases
    assert definition["edges"]


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


def test_agent_self_improvement_quick_start_embeds_agent_parameters_in_its_runner():
    store = store_module.ConsoleStore()
    quick_start = next(
        item for item in store._built_in_quick_starts() if item["id"] == "openorbit.agent-self-improvement"
    )

    from orbit_sdk.visual.builtin_templates import templates

    resolved = store._substitute(
        templates()["quick-starts:openorbit.agent-self-improvement"].source.read_text(encoding="utf-8"),
        {"agent_provider": "claude-code", "agent_options": "--model sonnet"},
    )

    assert 'AGENT_PROVIDER = "claude-code"' in resolved
    assert 'AGENT_OPTIONS = "--model sonnet"' in resolved
    assert "agent_provider" not in quick_start["build"]


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
            "model_profile_name": "Default",
        },
    )

    execution = store._execution_environment(created["generated"]["execution_environment_id"])
    runner = store._runner(created["generated"]["runner_id"])
    assert execution["environment_variables"] == {"ORBIT_PROBE_COMMAND": "uv run ai-eval"}
    assert created["build"]["repeat_interval_minutes"] == 1440
    assert store.profiles()[-1]["endpoint"] == ""
    assert runner["visual_template_id"] == "quick-starts:openorbit.ai-slo-drift-monitor"
    assert runner["visual_blueprint"]["parameters"]["probe_command"] == "uv run ai-eval"


def test_browser_quick_starts_create_an_internal_workspace_without_a_repository(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "APP_DATA", tmp_path / "app-data")
    monkeypatch.setattr(store_module, "CONFIG", tmp_path / "config")
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
        "openorbit.user-journey-smoke-test",
        {
            "base_url": "http://localhost:3000",
            "journey_prompt": "Open the home page.",
            "acceptance": "The page loads.",
            "model_profile_name": "Default",
        },
    )

    quick_starts = {item["id"]: item for item in store._built_in_quick_starts()}
    target = store._target_environment(created["generated"]["target_environment_id"])
    for quick_start_id in {
        "openorbit.continuous-user-journey",
        "openorbit.critical-flow-proof",
        "openorbit.site-exploration-review",
        "openorbit.user-journey-smoke-test",
    }:
        assert "repository" not in {
            parameter["key"] for parameter in quick_starts[quick_start_id]["parameters"]
        }
    assert "base_url" not in {
        parameter["key"] for parameter in quick_starts["openorbit.agent-self-improvement"]["parameters"]
    }
    assert target["repository"] == str(
        tmp_path / "app-data" / "quick-start-workspaces" / created["build"]["id"]
    )
    assert Path(target["repository"]).is_dir()


def test_quick_start_required_errors_include_the_display_label():
    store = store_module.ConsoleStore()

    with pytest.raises(ValueError, match=r"User actions \(journey_prompt\) is required"):
        store.instantiate_quick_start(
            "openorbit.user-journey-smoke-test", {"base_url": "http://localhost:3000"}
        )


def test_quick_start_can_create_and_assign_a_model_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "CONFIG", tmp_path)
    monkeypatch.setattr(store_module, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(store_module, "RUNNERS", tmp_path / "runners")
    monkeypatch.setattr(store_module, "QUICK_STARTS", tmp_path / "quick-starts")
    monkeypatch.setattr(store_module, "QUICK_START_INSTANCES", tmp_path / "quick-start-instances.yaml")
    monkeypatch.setattr(store_module, "EXECUTION_ENVIRONMENTS", tmp_path / "execution-environments.yaml")
    monkeypatch.setattr(store_module, "TARGET_ENVIRONMENTS", tmp_path / "target-environments.yaml")
    monkeypatch.setattr(store_module, "TARGET_TEST_CASE_SETS", tmp_path / "target-test-case-sets.yaml")
    store = store_module.ConsoleStore()

    created = store.instantiate_quick_start(
        "openorbit.user-journey-smoke-test",
        {
            "base_url": "http://localhost:3000",
            "journey_prompt": "Open the home page.",
            "acceptance": "The page loads.",
            "model_profile_name": "Quick Start model",
            "__model_profile_mode": "create",
            "__model_profile_provider": "azure-openai",
            "__model_profile_model": "gpt-4o",
            "__model_profile_endpoint": "https://example.openai.azure.com",
            "__model_profile_secret_env": "AZURE_OPENAI_API_KEY",
        },
    )

    assert created["build"]["model_profile_name"] == "Quick Start model"
    assert any(profile["profile_name"] == "Quick Start model" for profile in store.profiles())


def test_builtin_quick_starts_only_declare_a_model_profile_selector():
    store = store_module.ConsoleStore()
    legacy_keys = {"profile_name", "provider", "model", "endpoint", "region", "secret_env"}

    for quick_start in store._built_in_quick_starts():
        parameters = quick_start["parameters"]
        profile_parameters = [
            parameter for parameter in parameters if parameter["key"] == "model_profile_name"
        ]
        assert profile_parameters == [
            {
                "key": "model_profile_name",
                "label": "AI model profile",
                "type": "model_profile",
                "required": True,
                "tooltip": "Select an existing AI model profile, or create one for this build.",
            }
        ]
        assert not legacy_keys & {parameter["key"] for parameter in parameters}
        assert "model_profile" not in quick_start["assets"]


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
    package = tmp_path / "runner-templates" / "shared-browser-check"
    assert (package / "template.json").exists()
    assert (package / "runner.py").exists()


def test_folder_template_packages_keep_documentation_and_external_runner_source(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNER_TEMPLATES", tmp_path / "runner-templates")
    monkeypatch.setattr(store_module, "QUICK_STARTS", tmp_path / "quick-starts")
    runner_package = store_module.RUNNER_TEMPLATES / "documented-runner"
    runner_package.mkdir(parents=True)
    (runner_package / "template.json").write_text(
        json.dumps({"id": "documented-runner", "name": "Documented", "description": "Folder package."}),
        encoding="utf-8",
    )
    (runner_package / "runner.py").write_text("from orbit_sdk import runner\n", encoding="utf-8")
    (runner_package / "README.md").write_text("# Runner docs\n", encoding="utf-8")
    (runner_package / "LICENSE").write_text("MIT\n", encoding="utf-8")
    store = store_module.ConsoleStore()

    template = next(item for item in store.available_runner_templates() if item["id"] == "documented-runner")

    assert template["readme"] == "# Runner docs\n"
    assert template["license"] == "MIT\n"
    assert template["package_path"] == str(runner_package)


def _template_zip(files: dict[str, str]) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return archive.getvalue()


def test_runner_template_zip_import_preserves_the_complete_package(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNER_TEMPLATES", tmp_path / "runner-templates")
    store = store_module.ConsoleStore()
    imported = store.import_runner_template_package_zip(
        _template_zip(
            {
                "portable-runner/template.json": json.dumps(
                    {"id": "portable-runner", "name": "Portable", "description": "ZIP package."}
                ),
                "portable-runner/runner.py": "from orbit_sdk import runner\n",
                "portable-runner/README.md": "# Portable runner\n",
                "portable-runner/LICENSE": "OpenOrbit License\n",
                "portable-runner/support/example.txt": "kept\n",
            }
        ),
        "portable-runner.zip",
    )

    package = store_module.RUNNER_TEMPLATES / "portable-runner"
    assert imported["id"] == "portable-runner"
    assert (package / "README.md").read_text(encoding="utf-8") == "# Portable runner\n"
    assert (package / "support" / "example.txt").read_text(encoding="utf-8") == "kept\n"
    assert next(item for item in store.available_runner_templates() if item["id"] == "portable-runner")[
        "readme"
    ]


def test_quick_start_zip_import_preserves_the_complete_package(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "QUICK_STARTS", tmp_path / "quick-starts")
    source = store_module.ROOT / "templates" / "quick-starts" / "openorbit.ai-experience-improvement"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["id"] = "example.portable-ai-journey"
    archive = _template_zip(
        {
            "portable-quick-start/manifest.json": json.dumps(manifest),
            "portable-quick-start/runner.py": (source / "runner.py").read_text(encoding="utf-8"),
            "portable-quick-start/README.md": "# Portable quick start\n",
            "portable-quick-start/LICENSE": "OpenOrbit License\n",
            "portable-quick-start/assets/notes.txt": "kept\n",
        }
    )
    store = store_module.ConsoleStore()

    imported = store.import_quick_start_package_zip(archive, "portable-quick-start.zip")

    package = store_module.QUICK_STARTS / "example.portable-ai-journey"
    assert imported["id"] == "example.portable-ai-journey"
    assert (package / "LICENSE").read_text(encoding="utf-8") == "OpenOrbit License\n"
    assert (package / "assets" / "notes.txt").read_text(encoding="utf-8") == "kept\n"
    assert any(item["id"] == "example.portable-ai-journey" for item in store.quick_starts())


def test_template_zip_import_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNER_TEMPLATES", tmp_path / "runner-templates")
    store = store_module.ConsoleStore()

    with pytest.raises(ValueError, match="unsafe file path"):
        store.import_runner_template_package_zip(
            _template_zip(
                {
                    "bad/template.json": json.dumps(
                        {"id": "bad-template", "name": "Bad", "description": "Bad ZIP."}
                    ),
                    "bad/runner.py": "pass\n",
                    "../outside.txt": "nope\n",
                }
            ),
            "bad.zip",
        )

    assert not (tmp_path / "outside.txt").exists()
    assert not (store_module.RUNNER_TEMPLATES / "bad-template").exists()


def test_runner_template_package_upload_api_accepts_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNNER_TEMPLATES", tmp_path / "runner-templates")
    monkeypatch.setattr(main_module, "store", store_module.ConsoleStore())
    response = TestClient(app).post(
        "/api/runner-templates/import-package",
        files={
            "file": (
                "api-runner.zip",
                _template_zip(
                    {
                        "api-runner/template.json": json.dumps(
                            {"id": "api-runner", "name": "API runner", "description": "Uploaded package."}
                        ),
                        "api-runner/runner.py": "from orbit_sdk import runner\n",
                    }
                ),
                "application/zip",
            )
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == "api-runner"


def test_build_star_is_persisted_without_changing_other_build_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "CONFIG", tmp_path)
    (tmp_path / "builds.yaml").write_text(
        "- id: starred-build\n  name: Starred build\n  enabled: true\n  repository: ''\n",
        encoding="utf-8",
    )

    updated = store_module.ConsoleStore().set_build_star("starred-build", True)

    assert updated["starred"] is True
    saved = yaml.safe_load((tmp_path / "builds.yaml").read_text(encoding="utf-8"))[0]
    assert saved["starred"] is True
    assert saved["name"] == "Starred build"
    assert saved["enabled"] is True


def test_build_state_exposes_sdk_managed_state(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "CONFIG", tmp_path / "config")
    monkeypatch.setattr(store_module, "APP_DATA", tmp_path / "app-data")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "builds.yaml").write_text(
        "- id: persona-quality\n  name: Persona quality\n  enabled: true\n  repository: ''\n",
        encoding="utf-8",
    )
    state_dir = (
        tmp_path / "app-data" / "runner-state" / "persona-quality" / "runners" / "persona-journey-runner"
    )
    state_dir.mkdir(parents=True)
    (state_dir / "persona-journey.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-09-14T00:00:00+00:00",
                "run_id": "run-1",
                "iteration": 2,
                "value": {"personas": {"haruka": {"stage": 2}}},
            }
        ),
        encoding="utf-8",
    )

    assert store_module.ConsoleStore().build_state("persona-quality") == [
        {
            "name": "persona-journey",
            "scope": "runner",
            "runner_id": "persona-journey-runner",
            "updated_at": "2026-09-14T00:00:00+00:00",
            "run_id": "run-1",
            "iteration": 2,
            "value": {"personas": {"haruka": {"stage": 2}}},
        }
    ]


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


def test_personas_are_managed_as_reusable_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "PERSONAS", tmp_path / "personas.yaml")
    store = store_module.ConsoleStore()
    values = {
        "id": "careful-investor",
        "name": "Careful investor",
        "locale": "en-US",
        "timezone": "America/New_York",
        "activity_windows": [{"days": ["mon"], "start": "08:00", "end": "18:00"}],
        "definition": "# Goals\n\n- Understand the portfolio safely.\n\n# Constraints\n\n- Never place a real order.",
        "context": {"plan": "free"},
    }
    created = store.create_persona(values)
    assert created["context"] == {"plan": "free"}
    assert created["definition"].startswith("# Goals")
    updated = store.update_persona("careful-investor", {**values, "name": "Cautious investor"})
    assert updated["name"] == "Cautious investor"


def test_proposal_history_is_derived_from_evaluation_run_results(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    store._save(
        Run(
            id="run-1",
            workflow_id="workflow",
            workflow_name="Workflow",
            build_id="build-1",
            build_name="Build 1",
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
                            {"title": "Keep evidence", "target": "prompt", "status": "acceptable"},
                            {"title": "Remove noise", "target": "runner", "status": "proposed"},
                        ],
                        "reported_issues": [],
                    },
                }
            ],
        )
    )
    lifecycle = store.proposal_lifecycles("build-1")
    assert [item["status"] for item in lifecycle] == ["acceptable", "proposed"]
    assert {item["title"] for item in lifecycle} == {"Keep evidence", "Remove noise"}
    assert lifecycle[0]["data_files"] == [
        {
            "label": "Iteration evidence",
            "filename": "evidence.json",
            "path": "/tmp/orbit/evidence.json",
            "relative_path": "evidence.json",
        }
    ]


def test_issue_management_excludes_agent_assessment_feedback_from_issue_rationales(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(store_module, "ISSUE_MANAGEMENT", tmp_path / "issue-management.yaml")
    store = store_module.ConsoleStore()
    timestamp = store_module.now()
    issue = {
        "title": "Observed policy claim",
        "evaluation": {"approval": "approved", "score": 6, "summary": "Observed in the response."},
    }
    store._save(
        Run(
            id="run-agent-review",
            workflow_id="workflow",
            workflow_name="Workflow",
            status="succeeded",
            created_at=timestamp,
            updated_at=timestamp,
            step_results=[
                {
                    "loop_index": 1,
                    "result": {
                        "agent_run": {
                            "feedback": "Added a policy guardrail.",
                            "changed_files": ["prompt.md"],
                            "proposal": {"fingerprint": "a" * 64},
                        },
                        "agent_proposal": {"issue": issue},
                    },
                }
            ],
            supervisor_results=[
                {
                    "iteration": 1,
                    "stage": "issue_assessment",
                    "response": {
                        "improvements": [
                            {"title": "Issue proposal", "status": "proposed", "rationale": "Issue reason."}
                        ],
                        "reported_issues": [issue],
                    },
                },
                {
                    "iteration": 1,
                    "stage": "agent_proposal_assessment",
                    "response": {
                        "evaluation": {
                            "approval": "rejected",
                            "score": 2,
                            "summary": "Agent review summary.",
                        },
                        "improvements": [
                            {
                                "title": "Do not expose this as an Issue",
                                "status": "proposed",
                                "rationale": "Agent feedback.",
                            }
                        ],
                        "reported_issues": [],
                    },
                },
            ],
        )
    )

    lifecycle = store.proposal_lifecycles()

    assert [item["title"] for item in lifecycle] == ["Issue proposal"]
    assessed_issue = lifecycle[0]
    assert assessed_issue["proposal"]["agent_change"]["feedback"] == "Added a policy guardrail."
    assert assessed_issue["proposal"]["agent_change"]["review"]["summary"] == "Agent review summary."
    assert lifecycle[0]["decision_rationale"] == "Issue reason."
    assert all(item["category"] == "other" for item in lifecycle)
    managed_issue = next(item for item in store.issue_management_items() if item["title"] == "Issue proposal")
    assert managed_issue["comments"][0]["body"] == "Agent review summary."
    assert managed_issue["comments"][0]["assigner"] == "AI supervisor"


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
        "coding_agent_provider": "none",
        "assistant_tools": {
            "workspace_root": str(store_module.ROOT),
            "file_read_enabled": True,
            "file_search_enabled": True,
            "run_process_enabled": True,
            "coding_agent_enabled": True,
            "ui_context_enabled": True,
            "ui_interaction_enabled": True,
            "terminal_enabled": True,
            "terminal_visible": True,
            "mcp_server_url": "http://127.0.0.1:3000/mcp/",
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
        store.save_application_settings({"coding_agent_provider": "kiro"})["coding_agent_provider"] == "kiro"
    )
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


def test_assistant_mcp_configuration_uses_a_valid_default_and_persists_json(tmp_path, monkeypatch):
    mcp_config = tmp_path / "config" / "assistant-mcp.json"
    monkeypatch.setattr(store_module, "ASSISTANT_MCP_CONFIG", mcp_config)
    store = store_module.ConsoleStore()

    assert store.assistant_mcp_config()["content"] == (
        '{\n  "mcpServers": {\n    "openorbit": {\n      "url": "http://127.0.0.1:3000/mcp/"\n    }\n  }\n}\n'
    )
    saved = store.save_assistant_mcp_config('{"mcpServers": {"orbit": {"command": "uv"}}}')

    assert saved["content"] == '{\n  "mcpServers": {\n    "orbit": {\n      "command": "uv"\n    }\n  }\n}\n'
    with pytest.raises(ValueError, match="valid JSON"):
        store.save_assistant_mcp_config("not json")


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
    assert "Japanese (ja)" in prompt
    assert store_module.MANAGER_OUTPUT_LANGUAGE_SLOT not in prompt


def test_run_output_language_overrides_the_shared_application_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(store_module, "CONFIG", tmp_path / "config")
    store = store_module.ConsoleStore()
    store.save_application_settings({"manager_output_locale": "en"})
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "prompt-templates.yaml").write_text(
        "- id: manager-default-v1\n  name: Default\n  version: 1\n  content: Assess evidence.\n",
        encoding="utf-8",
    )
    _, prompt = store._assembled_prompt(
        {"manager_template_id": "manager-default-v1", "repository": "test"}, "ko"
    )
    assert "Korean (ko)" in prompt
    assert "do not switch to the persona's language" in prompt
    assert "facts and severity rather than its source-language wording" in prompt
