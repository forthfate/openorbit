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


def test_disabled_tools_are_not_advertised(tmp_path):
    assert AssistantToolExecutor(tool_settings(tmp_path)).definitions() == []


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
