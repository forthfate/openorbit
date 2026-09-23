from __future__ import annotations

import json
import subprocess
import sys
from base64 import b64encode

import orbit_sdk as sdk
import pytest


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


def test_graph_step_inherits_its_zone_from_runner_phase():
    graph = sdk.Graph()
    runner = sdk.Runner()

    @graph.step("collect")
    @runner.phase("setup")
    def collect() -> None:
        pass

    assert graph.definition()["nodes"][0]["phase"] == "before_each"


def test_graph_exports_after_supervision_only_when_enabled():
    graph = sdk.Graph()

    @graph.step("propose", phase="after_each", after_supervision=True)
    def propose() -> None:
        pass

    assert graph.definition()["nodes"][0]["after_supervision"] is True


def test_visual_node_inputs_only_returns_declared_port_bindings(tmp_path, monkeypatch):
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")
    ctx = context(tmp_path, iteration=1)
    ctx.publish_visual_node_outputs("collect", {"score": 100, "private": "no"})
    ctx.publish_visual_node_outputs("other", {"score": 1})

    assert ctx.visual_node_inputs("report", {"journey_score": ("collect", "score")}) == {"journey_score": 100}
    assert ctx.visual_node_inputs("report", {"missing": ("collect", "missing")}) == {}


def test_function_trace_emits_successful_function_evidence(tmp_path, capsys):
    ctx = context(tmp_path, iteration=1)

    with ctx.function("collect-source-evidence"):
        pass

    assert "collect-source-evidence" in capsys.readouterr().out


def test_register_evaluation_emits_an_agent_change_request(tmp_path, capsys):
    result = context(tmp_path, iteration=2).register_evaluation(
        "Updated the retry behavior after reproducing the timeout.",
        changed_files=["src/retry.py", "src/retry.py", "tests/test_retry.py"],
        validation="pytest tests/test_retry.py",
    )

    emitted = [
        json.loads(line.removeprefix("__ORBIT_RESULT__"))
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("__ORBIT_RESULT__")
    ]
    assert result["subject"] == "agent_change"
    assert result["changed_files"] == ["src/retry.py", "tests/test_retry.py"]
    assert emitted[-1]["evaluation_request"] == result


def test_register_evaluation_requires_actionable_feedback(tmp_path):
    with pytest.raises(ValueError, match="feedback"):
        context(tmp_path, iteration=1).register_evaluation("   ")


def test_run_ai_agent_uses_the_selected_cli_and_only_marker_feedback(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "Orbit Test"], cwd=project, check=True)
    (project / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True)
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")
    ctx = context(project, iteration=1)
    commands: list[list[str]] = []

    def fake_exec(command, **_kwargs):
        commands.append(command)
        if command[0] == "codex":
            return "completed work\nORBIT_AGENT_FEEDBACK: Updated retry behavior\n"
        if command[:3] == ["git", "diff", "--name-only"]:
            return "src/retry.py\n"
        if command[:3] == ["git", "diff", "--binary"]:
            return "diff --git a/src/retry.py b/src/retry.py\n"
        return ""

    monkeypatch.setattr(ctx, "exec", fake_exec)

    result = ctx.run_ai_agent("Fix the retry behavior", provider="codex", options="--model gpt-5")

    assert commands[0][:4] == ["git", "worktree", "add", "-b"]
    assert commands[0][5].startswith(str(tmp_path / "orbit-data" / "agent-worktrees"))
    assert commands[1:] == [
        [
            "codex",
            "exec",
            "--approve-for-me",
            "--model",
            "gpt-5",
            "Fix the retry behavior",
        ],
        ["git", "add", "--intent-to-add", "--all"],
        ["git", "diff", "--name-only", "--"],
        ["git", "diff", "--binary", "--"],
    ]
    assert result["feedback"] == "Updated retry behavior"
    assert result["changed_files"] == ["src/retry.py"]
    assert result["proposal"]["diff"] == "diff --git a/src/retry.py b/src/retry.py\n"
    assert result["proposal"]["base_revision"]
    assert result["proposal"]["branch"].startswith("orbit/agent-proposal/run-123/")


def test_graph_step_automatically_traces_its_execution(tmp_path, capsys):
    graph = sdk.Graph()

    @graph.step("collect-source-evidence")
    def collect(ctx) -> None:
        ctx.log("Collected source evidence")

    collect(context(tmp_path, iteration=1))

    output = capsys.readouterr().out
    assert "workflow function started: collect-source-evidence" in output
    assert "workflow function succeeded: collect-source-evidence" in output
    assert '"status": "running"' in output
    assert '"status": "succeeded"' in output


def test_graph_step_automatically_traces_failures(tmp_path, capsys):
    graph = sdk.Graph()

    @graph.step("collect-source-evidence")
    def collect(ctx) -> None:
        raise RuntimeError("evidence unavailable")

    with pytest.raises(RuntimeError, match="evidence unavailable"):
        collect(context(tmp_path, iteration=1))

    output = capsys.readouterr().out
    assert "workflow function failed: collect-source-evidence" in output
    assert '"status": "failed"' in output


def test_nested_function_trace_for_the_same_node_is_emitted_once(tmp_path, capsys):
    ctx = context(tmp_path, iteration=1)

    with ctx.function("collect-source-evidence"):
        with ctx.function("collect-source-evidence"):
            pass

    output = capsys.readouterr().out
    assert output.count('"status": "running"') == 1
    assert output.count('"status": "succeeded"') == 1


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


def test_runner_state_is_scoped_and_retained_between_invocations(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(sdk, "ORBIT_APP_DATA", tmp_path / "orbit-data")
    resources = {"build": {"id": "persona-quality", "runner_id": "persona-journey-runner"}}
    encoded = b64encode(json.dumps(resources).encode()).decode()

    saved = sdk.RunnerContext(
        phase="execute",
        target_repository=project,
        mode="run",
        loop_index=2,
        environment={"ORBIT_RUNNER_RESOURCES": encoded, "ORBIT_RUN_ID": "run-456"},
    ).save_state("persona-journey", {"personas": {"haruka": {"stage": 2}}})
    shared = sdk.RunnerContext(
        phase="execute",
        target_repository=project,
        mode="run",
        loop_index=2,
        environment={"ORBIT_RUNNER_RESOURCES": encoded, "ORBIT_RUN_ID": "run-456"},
    ).save_state("shared-settings", {"enabled": True}, scope="build")

    next_context = sdk.RunnerContext(
        phase="execute",
        target_repository=project,
        mode="run",
        loop_index=3,
        environment={"ORBIT_RUNNER_RESOURCES": encoded},
    )
    assert saved["name"] == "persona-journey"
    assert saved["scope"] == "runner"
    assert shared["scope"] == "build"
    assert next_context.load_state("persona-journey") == {"personas": {"haruka": {"stage": 2}}}
    assert next_context.load_state("shared-settings", scope="build") == {"enabled": True}
    assert next_context.load_state("missing", default={}) == {}
    assert (
        tmp_path
        / "orbit-data"
        / "runner-state"
        / "persona-quality"
        / "runners"
        / "persona-journey-runner"
        / "persona-journey.json"
    ).exists()
    assert (
        tmp_path / "orbit-data" / "runner-state" / "persona-quality" / "build" / "shared-settings.json"
    ).exists()


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


def test_run_json_action_uses_stdout_without_stderr_and_passes_cycle_input(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    script = (
        "import json, os, sys; "
        "print(json.dumps({'action': sys.argv[1], 'input': json.loads(os.environ['RUNNER_CYCLE_INPUT'])})); "
        "print('diagnostic output', file=sys.stderr)"
    )
    ctx = sdk.RunnerContext(
        phase="execute",
        target_repository=project,
        mode="run",
        loop_index=1,
        environment={
            "ORBIT_RUN_ID": "run-123",
            "RUNNER_COMMAND": json.dumps([sys.executable, "-c", script]),
        },
    )

    result = ctx.run_json_action(
        command_env="RUNNER_COMMAND",
        action="collect",
        input_env="RUNNER_CYCLE_INPUT",
        input_data={"iteration": 1},
        log_source="test-command",
    )

    assert result == {"action": "collect", "input": {"iteration": 1, "action": "collect"}}
    assert "diagnostic output" in capsys.readouterr().out


@pytest.mark.parametrize("value", ["[]", '[""]'])
def test_command_from_env_rejects_an_empty_executable(tmp_path, value):
    with pytest.raises(ValueError, match="non-empty"):
        sdk.RunnerContext(
            phase="execute",
            target_repository=tmp_path,
            mode="run",
            loop_index=1,
            environment={"RUNNER_COMMAND": value},
        ).command_from_env("RUNNER_COMMAND")


def test_complete_model_json_requires_a_json_object(tmp_path, monkeypatch):
    ctx = context(tmp_path, iteration=1)
    monkeypatch.setattr(ctx, "complete_model", lambda _prompt: {"response": '{"next": "visit"}'})

    assert ctx.complete_model_json("Choose an action") == {"next": "visit"}

    monkeypatch.setattr(ctx, "complete_model", lambda _prompt: {"response": "[]"})
    with pytest.raises(RuntimeError, match="must return a JSON object"):
        ctx.complete_model_json("Choose an action")


def test_require_test_case_ids_reports_missing_cases(tmp_path):
    resources = {"test_cases": [{"id": "included"}]}
    ctx = sdk.RunnerContext(
        phase="execute",
        target_repository=tmp_path,
        mode="run",
        loop_index=1,
        environment={
            "ORBIT_RUNNER_RESOURCES": b64encode(json.dumps(resources).encode()).decode(),
        },
    )

    ctx.require_test_case_ids({"included"})
    with pytest.raises(ValueError, match="Missing required test case: absent"):
        ctx.require_test_case_ids({"included", "absent"})


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
