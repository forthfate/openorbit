from app.assistant_graph import DEFAULT_MCP_URL, OrbitAssistantGraph, build_assistant_prompt
from app.providers import ModelSettings


class FakeProvider:
    def complete(self, settings, prompt):
        return f"plain:{prompt}"

    def complete_with_tools(self, settings, prompt, tools, execute):
        assert tools == [{"name": "get_status", "description": "status", "parameters": {}}]
        return f"tools:{execute('get_status', {})}"


class FakeLocalTools:
    def definitions(self):
        return []

    def execute(self, name, arguments):
        raise AssertionError("local tools should not receive an MCP tool call")


class FakeMcpTools:
    def definitions(self):
        return [{"name": "get_status", "description": "status", "parameters": {}}]

    def execute(self, name, arguments):
        assert (name, arguments) == ("get_status", {})
        return '{"health":"ok"}'


def test_assistant_graph_routes_mcp_tools_through_the_langgraph_model_node():
    activity = []
    graph = OrbitAssistantGraph(
        FakeProvider(),
        ModelSettings(),
        FakeLocalTools(),
        FakeMcpTools(),
        on_activity=lambda phase, tool=None: activity.append((phase, tool)),
    )

    assert graph.invoke("status") == 'tools:{"health":"ok"}'
    assert activity == [("thinking", None), ("working", "get_status"), ("thinking", None)]


def test_assistant_prompt_uses_local_mcp_as_the_control_room_source_of_truth():
    prompt = build_assistant_prompt("What changed?", [("assistant", "Earlier answer")], "ko-KR")

    assert DEFAULT_MCP_URL == "http://127.0.0.1:3000/mcp/"
    assert "OpenOrbit MCP tools as the source of truth" in prompt
    assert "Execution environment:" in prompt
    assert "- OS: " in prompt
    assert "- Default shell: " in prompt
    assert "- Current working directory: " in prompt
    assert "- Current local time: " in prompt
    assert "Respond in BCP 47 locale 'ko-KR'." in prompt
    assert "Assistant: Earlier answer" in prompt


def test_assistant_prompt_prioritizes_ui_tools_for_browser_ui_requests():
    prompt = build_assistant_prompt("What screen is open?", [], "en", ui_enabled=True)

    assert "first call ui_get_context" in prompt
    assert "Do not use file tools to infer browser UI state" in prompt
