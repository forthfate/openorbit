import json

from app.assistant_tools import AssistantToolExecutor


def tool_settings(workspace, **overrides):
    return {
        "workspace_root": str(workspace),
        "file_read_enabled": False,
        "file_search_enabled": False,
        "run_process_enabled": False,
        **overrides,
    }


def test_coding_agent_is_advertised_even_without_a_selected_provider(tmp_path):
    tools = AssistantToolExecutor(tool_settings(tmp_path))

    assert [definition["name"] for definition in tools.definitions()] == ["coding_agent"]
    result = json.loads(tools.execute("coding_agent", {"task": "inspect this project"}))
    assert result["error_code"] == "coding_agent_not_configured"
    assert result["settings_page"] == "settings"


def test_coding_agent_can_be_disabled_in_assistant_tool_settings(tmp_path):
    tools = AssistantToolExecutor(tool_settings(tmp_path, coding_agent_enabled=False))

    assert tools.definitions() == []


def test_coding_agent_passes_workspace_environment_to_selected_cli(tmp_path, monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return type("Result", (), {"stdout": "done", "stderr": "", "returncode": 0})()

    monkeypatch.setattr("app.assistant_tools.shutil.which", lambda _: "/usr/bin/kiro-cli")
    monkeypatch.setattr("app.assistant_tools.subprocess.run", fake_run)
    tools = AssistantToolExecutor(tool_settings(tmp_path), coding_agent_provider="kiro")

    result = json.loads(tools.execute("coding_agent", {"task": "Update the README"}))

    assert captured["command"][:2] == ["kiro-cli", "chat"]
    assert f"- Current working directory: {tmp_path}" in captured["command"][-1]
    assert "- OS: " in captured["command"][-1]
    assert captured["cwd"] == tmp_path
    assert result["provider"] == "kiro"


def test_file_read_is_bounded_to_workspace_and_line_range(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    tools = AssistantToolExecutor(tool_settings(tmp_path, file_read_enabled=True))

    result = json.loads(tools.execute("file_read", {"path": "notes.txt", "start_line": 2, "end_line": 3}))

    assert result["content"] == "two\nthree"
    assert result["total_lines"] == 3
    denied = json.loads(
        tools.execute("file_read", {"path": "../outside.txt", "start_line": 1, "end_line": 1})
    )
    assert "error" in denied


def test_file_search_returns_bounded_workspace_matches(tmp_path):
    (tmp_path / "app.py").write_text("def orbit_status(): pass\n", encoding="utf-8")
    tools = AssistantToolExecutor(tool_settings(tmp_path, file_search_enabled=True))

    result = json.loads(tools.execute("file_search", {"query": "orbit_status"}))

    assert result["matches"] == [
        {"path": "app.py", "line": 1, "content": "def orbit_status(): pass", "match_kind": "content"}
    ]


def test_run_process_uses_argument_array_without_shell(tmp_path):
    tools = AssistantToolExecutor(tool_settings(tmp_path, run_process_enabled=True))

    result = json.loads(tools.execute("run_process", {"executable": "printf", "arguments": ["ok"]}))

    assert result["exit_code"] == 0
    assert result["output"] == "ok"
    denied = json.loads(tools.execute("run_process", {"executable": "sh", "arguments": ["-c", "echo no"]}))
    assert "error" in denied
