from app import store as store_module
from app.main import app
from fastapi.testclient import TestClient


def test_health_is_available():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
        "cases": [{"id": "response-check", "name": "Response check", "prompt": "Reply with evidence.", "acceptance": "Evidence is present."}],
    }
    created = store.create_target_test_case_set(values)
    assert created["id"] == "target-smoke-tests"
    updated = store.update_target_test_case_set("target-smoke-tests", {**values, "name": "Updated target tests"})
    assert updated["name"] == "Updated target tests"


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
    assert store.save_application_settings({"manager_prompt_template": "Operate with audit context."}) == {
        "manager_prompt_template": "Operate with audit context."
    }
    store.save_settings({"profile_name": "Development", "provider": "azure-openai", "model": "gpt-test", "endpoint": "https://example.test", "region": "us-east-1", "secret_env": "AZURE_OPENAI_API_KEY"})
    assert store.application_settings()["manager_prompt_template"] == "Operate with audit context."


def test_application_manager_prompt_has_a_safe_default(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SETTINGS", tmp_path / "settings.json")
    assert "approval-first operations manager" in store_module.ConsoleStore().application_settings()["manager_prompt_template"]
