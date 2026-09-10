from __future__ import annotations

import json
import subprocess
import sys
from base64 import b64encode

import orbit_sdk as sdk


def test_graph_declarations_export_nodes_and_typed_edges():
    graph = sdk.Graph()

    @graph.step("collect", phase="before_each", outputs=["evidence"])
    def collect() -> None:
        pass

    graph.connect("collect", "collect", kind="loop", label="next iteration")

    assert graph.definition() == {
        "nodes": [
            {
                "id": "collect",
                "title": "Collect",
                "phase": "before_each",
                "inputs": [],
                "outputs": ["evidence"],
                "description": None,
            }
        ],
        "edges": [
            {
                "source": "collect",
                "target": "collect",
                "kind": "loop",
                "label": "next iteration",
                "source_port": None,
                "target_port": None,
            }
        ],
    }


def context(project, *, iteration: int, run_id: str = "run-123"):
    return sdk.RunnerContext(
        phase="execute",
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
    assert version["phase"] == "execute"
    assert version["run_id"] == "run-123"
    assert version["previous"]["sha256"] == sdk._sha256(b"before")
    assert version["written"]["sha256"] == sdk._sha256(b"after")
    assert version["written"]["snapshot"]
    manifest = next((tmp_path / "orbit-data").rglob("manifest.json"))
    snapshot = manifest.parent / version["previous"]["snapshot"]
    assert snapshot.read_bytes() == b"before"
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


def test_update_file_blocks_a_managed_prompt_when_human_approval_is_required(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    prompt = project / "prompt.md"
    prompt.write_text("before", encoding="utf-8")
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")
    resources = {
        "build": {
            "managed_prompt_path": "prompt.md",
            "require_human_approval_before_apply": True,
        }
    }
    ctx = sdk.RunnerContext(
        phase="before_each",
        target_repository=project,
        mode="run",
        loop_index=2,
        environment={
            "ORBIT_RUN_ID": "run-123",
            "ORBIT_RUNNER_RESOURCES": b64encode(json.dumps(resources).encode()).decode(),
        },
    )

    result = ctx.update_file("prompt.md", "after")

    assert prompt.read_text(encoding="utf-8") == "before"
    assert result["changed"] is False
    assert result["reason"] == "awaiting_human_approval"


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
    data_file = ctx.save_data_file(
        "evidence/summary.json",
        "{}",
        label="Iteration summary",
        content_type="application/json",
    )

    assert (sdk.ORBIT_APP_DATA / "runner-assets").exists()
    assert (
        sdk.ORBIT_APP_DATA / "artifacts" / "run-123" / "loop-2" / "evidence" / "report.json"
    ).read_text() == "{}"
    assert assets["files"]["scripts/gate.ps1"] == sdk._sha256(b"Write-Output ok")
    assert artifact["content_type"] == "application/json"
    assert data_file["label"] == "Iteration summary"
    assert data_file["filename"] == "summary.json"
    assert data_file["path"].endswith("evidence/summary.json")
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


def test_repository_snapshot_restores_worktree_index_and_head_without_a_commit(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Orbit test"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "orbit@example.test"], cwd=project, check=True)
    (project / ".gitignore").write_text("generated/\n", encoding="utf-8")
    (project / "tracked.txt").write_text("initial\n", encoding="utf-8")
    (project / "staged.txt").write_text("initial staged\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "Initial target"], cwd=project, check=True, capture_output=True)
    baseline_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project, check=True, capture_output=True, text=True
    ).stdout.strip()
    (project / "tracked.txt").write_text("working baseline\n", encoding="utf-8")
    (project / "staged.txt").write_text("staged baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "staged.txt"], cwd=project, check=True)
    (project / "untracked.txt").write_text("untracked baseline\n", encoding="utf-8")
    (project / "generated").mkdir()
    (project / "generated" / "state.txt").write_text("ignored baseline\n", encoding="utf-8")
    (project / "empty").mkdir()
    expected_status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=project, check=True, capture_output=True, text=True
    ).stdout
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")
    setup = sdk.RunnerContext(
        phase="before_each",
        target_repository=project,
        mode="run",
        loop_index=1,
        environment={"ORBIT_RUN_ID": "snapshot-run"},
    )

    snapshot = setup.save_setup_snapshot()

    assert setup.save_setup_snapshot()["id"] == snapshot["id"]
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project, check=True, capture_output=True, text=True
        ).stdout.strip()
        == baseline_head
    )
    assert (
        subprocess.run(
            ["git", "cat-file", "-t", snapshot["worktree_tree"]],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "tree"
    )
    assert subprocess.run(
        ["git", "show-ref", "--verify", snapshot["retention_ref"]],
        cwd=project,
        check=True,
        capture_output=True,
    )

    (project / "tracked.txt").unlink()
    (project / "staged.txt").write_text("evaluation staged\n", encoding="utf-8")
    subprocess.run(["git", "add", "staged.txt"], cwd=project, check=True)
    (project / "untracked.txt").unlink()
    (project / "generated" / "state.txt").unlink()
    (project / "generated" / "new.txt").write_text("new ignored\n", encoding="utf-8")
    (project / "new.txt").write_text("new untracked\n", encoding="utf-8")
    (project / "committed.txt").write_text("evaluation commit\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Evaluation mutation"], cwd=project, check=True, capture_output=True
    )

    finalized = sdk.RunnerContext(
        phase="after_all",
        target_repository=project,
        mode="run",
        loop_index=2,
        environment={"ORBIT_RUN_ID": "snapshot-run"},
    )
    restored = finalized.restore_setup_snapshot()

    assert restored["id"] == snapshot["id"]
    assert (project / "tracked.txt").read_text(encoding="utf-8") == "working baseline\n"
    assert (project / "staged.txt").read_text(encoding="utf-8") == "staged baseline\n"
    assert (project / "untracked.txt").read_text(encoding="utf-8") == "untracked baseline\n"
    assert (project / "generated" / "state.txt").read_text(encoding="utf-8") == "ignored baseline\n"
    assert (project / "empty").is_dir()
    assert not (project / "new.txt").exists()
    assert not (project / "generated" / "new.txt").exists()
    assert not (project / "committed.txt").exists()
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project, check=True, capture_output=True, text=True
        ).stdout.strip()
        == baseline_head
    )
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=project, check=True, capture_output=True, text=True
        ).stdout
        == expected_status
    )


def test_first_teardown_snapshot_is_linked_to_its_iteration(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Orbit test"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "orbit@example.test"], cwd=project, check=True)
    (project / "target.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "Initial target"], cwd=project, check=True, capture_output=True)
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")

    first = sdk.RunnerContext(
        phase="after_each",
        target_repository=project,
        mode="run",
        loop_index=1,
        environment={"ORBIT_RUN_ID": "checkpoint-run"},
    ).save_first_teardown_snapshot()
    later = sdk.RunnerContext(
        phase="after_each",
        target_repository=project,
        mode="run",
        loop_index=2,
        environment={"ORBIT_RUN_ID": "checkpoint-run"},
    ).save_first_teardown_snapshot()

    assert first is not None
    assert first["label"] == "iteration-1"
    assert first["iteration"] == 1
    assert first["phase"] == "after_each"
    assert later is None


def test_runner_records_a_commit_range_after_a_phase(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Orbit test"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "orbit@example.test"], cwd=project, check=True)
    target = project / "agent.txt"
    target.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "agent.txt"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "Initial agent"], cwd=project, check=True, capture_output=True)
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")
    monkeypatch.setenv("ORBIT_TARGET_REPOSITORY", str(project))
    monkeypatch.setenv("ORBIT_RUN_ID", "commit-run")
    monkeypatch.setattr(sys, "argv", ["runner", "--phase", "execute"])
    phase_runner = sdk.Runner()

    @phase_runner.phase("run")
    def commit_change(ctx):
        target.write_text("after\n", encoding="utf-8")
        subprocess.run(["git", "add", "agent.txt"], cwd=ctx.project_root, check=True)
        subprocess.run(["git", "commit", "-m", "Improve agent"], cwd=ctx.project_root, check=True)

    phase_runner.main()

    events = [
        json.loads(line.removeprefix("__ORBIT_RESULT__"))
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("__ORBIT_RESULT__")
    ]
    recorded_change = next(event["commit_change"] for event in events if "commit_change" in event)
    assert recorded_change["changed_paths"] == ["agent.txt"]
    assert [item["subject"] for item in recorded_change["commits"]] == ["Improve agent"]
    assert recorded_change["diff_artifact"]["content_type"] == "text/x-diff"
