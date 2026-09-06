from __future__ import annotations

import json
import sys

import orbit_sdk as sdk


def context(project, *, iteration: int, run_id: str = "run-123"):
    return sdk.RunnerContext(
        phase="run",
        target_repository=project,
        mode="run",
        loop_index=iteration,
        environment={"ORBIT_RUN_ID": run_id},
    )


def test_update_file_retains_previous_contents_and_metadata(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "config.txt"
    target.write_text("before", encoding="utf-8")
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")

    result = context(project, iteration=7).update_file("config.txt", "after")

    assert target.read_text(encoding="utf-8") == "after"
    version = result["version"]
    assert result["changed"] is True
    assert version["iteration"] == 7
    assert version["phase"] == "run"
    assert version["run_id"] == "run-123"
    assert version["previous"]["sha256"] == sdk._sha256(b"before")
    assert version["written"]["sha256"] == sdk._sha256(b"after")
    snapshot = next((tmp_path / "orbit-data").rglob("*.bin"))
    assert snapshot.read_bytes() == b"before"
    manifest = next((tmp_path / "orbit-data").rglob("manifest.json"))
    assert json.loads(manifest.read_text(encoding="utf-8"))["history"][0]["id"] == version["id"]


def test_rollback_file_restores_a_version_and_can_be_undone(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "config.txt"
    target.write_text("first", encoding="utf-8")
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")

    first = context(project, iteration=1).update_file("config.txt", "second")
    context(project, iteration=2).update_file("config.txt", "third")
    restored = context(project, iteration=3).rollback_file("config.txt", first["version"]["id"])

    assert target.read_text(encoding="utf-8") == "first"
    assert restored["version"]["operation"] == "rollback"
    assert restored["version"]["rollback_of"] == first["version"]["id"]

    context(project, iteration=4).rollback_file("config.txt", restored["version"]["id"])
    assert target.read_text(encoding="utf-8") == "third"


def test_update_file_can_rollback_a_file_created_by_the_runner(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")

    created = context(project, iteration=1).update_file("new.txt", "new content")
    context(project, iteration=2).rollback_file("new.txt", created["version"]["id"])

    assert not (project / "new.txt").exists()


def test_proposal_decisions_are_a_deduplicated_auditable_event_stream(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")
    proposal = {"title": "Use direct evidence", "rationale": "The last run was incomplete."}

    accepted = context(project, iteration=3).accept_proposal(
        proposal, proposal_id="proposal-evidence", rationale="Validated in run evidence."
    )
    repeated = context(project, iteration=4).accept_proposal(proposal, proposal_id="proposal-evidence")
    rejected = context(project, iteration=5).reject_proposal(proposal, proposal_id="proposal-evidence")

    assert accepted["recorded"] is True
    assert repeated["recorded"] is False
    assert rejected["recorded"] is True
    decisions = context(project, iteration=6).proposal_decisions()
    assert [item["decision"] for item in decisions] == ["rejected", "accepted"]
    assert decisions[0]["iteration"] == 5
    assert decisions[0]["proposal_id"] == "proposal-evidence"


def test_proposal_application_links_an_accepted_proposal_to_a_prompt_version(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "prompt.md").write_text("before", encoding="utf-8")
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")
    ctx = context(project, iteration=2)
    ctx.accept_proposal({"title": "Keep evidence"}, proposal_id="proposal-evidence")
    update = ctx.update_file("prompt.md", "after")

    applications = ctx.record_proposal_application(["proposal-evidence"], update)

    assert applications[0]["event_type"] == "prompt_updated"
    assert applications[0]["prompt_version"]["id"] == update["version"]["id"]


def test_managed_assets_and_artifacts_stay_outside_the_target(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")
    ctx = context(project, iteration=2)

    assets = ctx.materialize_assets("paired-gate", {"scripts/gate.ps1": "Write-Output ok"})
    artifact = ctx.write_artifact("evidence/report.json", "{}", content_type="application/json")

    assert (sdk.ORBIT_APP_DATA / "runner-assets").exists()
    assert (
        sdk.ORBIT_APP_DATA / "artifacts" / "run-123" / "loop-2" / "evidence" / "report.json"
    ).read_text() == "{}"
    assert assets["files"]["scripts/gate.ps1"] == sdk._sha256(b"Write-Output ok")
    assert artifact["content_type"] == "application/json"
    assert not any(project.rglob("gate.ps1"))


def test_exec_env_override(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")
    output = context(project, iteration=1).exec(
        [sys.executable, "-c", "import os; print(os.environ['RUNNER_TEST_VALUE'])"],
        env={"RUNNER_TEST_VALUE": "set"},
    )

    assert output.strip() == "set"
