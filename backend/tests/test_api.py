import pytest
from app import store as store_module
from app.main import app
from app.models import Run
from fastapi.testclient import TestClient


def test_health_is_available():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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


def test_native_improvement_cycle_evidence_triggers_supervision():
    class RunRecord:
        step_results = [
            {
                "phase": "run",
                "result": {"improvement_cycle": {"candidate_fingerprint": "a" * 64}},
            }
        ]

    assert store_module.ConsoleStore._latest_cycle_has_persona_evidence(RunRecord()) is True


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
    assert "playwright_journey" in improvement
    assert "ORBIT_CYCLE_COMMAND" not in improvement
    assert "run_paired_improvement_cycle" not in improvement
    assert "update_prompt_from_accepted_proposals" in improvement
    assert "ctx.accept_proposal" not in improvement
    assert "ctx.update_file" in improvement
    assert "ORBIT_AGENT_COMMAND" in json_agent
    assert "ORBIT_PROBE_COMMAND" in probe_gate
    assert "Insighta" not in json_agent
    assert "Jgent" not in json_agent
    assert "Insighta" not in probe_gate
    assert "Jgent" not in probe_gate


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
    assert template == {"id": "manager-test-v1", "name": "Updated", "version": 2, "content": "new content"}


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
    expected_prompt = f"Operate with audit context.\n\n{store_module.MANAGER_PROMPT_SLOT}"
    assert store.save_application_settings({"manager_prompt_template": "Operate with audit context."}) == {
        "manager_prompt_template": expected_prompt,
        "chat_model_profile_name": "",
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
