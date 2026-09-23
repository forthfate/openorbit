import json
import threading

from app.assistant_ui import AssistantUiBroker, AssistantUiToolExecutor


def test_ui_broker_round_trips_a_tool_command_to_the_browser_session():
    broker = AssistantUiBroker()
    sent = {}
    sent_event = threading.Event()

    def send(command_id, command):
        sent.update(id=command_id, command=command)
        sent_event.set()

    broker.open("browser-1", send)
    result = {}

    def request():
        result.update(broker.request("browser-1", {"type": "get_context"}, timeout=1))

    thread = threading.Thread(target=request)
    thread.start()
    assert sent_event.wait(1)
    assert sent["command"] == {"type": "get_context"}
    assert broker.resolve("browser-1", sent["id"], {"ok": True, "revision": 3})
    thread.join(1)
    assert result == {"ok": True, "revision": 3}


def test_ui_tool_executor_returns_browser_context_as_a_tool_result():
    broker = AssistantUiBroker()
    sent = {}
    sent_event = threading.Event()

    def send(command_id, command):
        sent.update(id=command_id, command=command)
        sent_event.set()

    broker.open("browser-1", send)
    tools = AssistantUiToolExecutor(broker, "browser-1", context_enabled=True, interaction_enabled=True)
    result = {}

    def execute():
        result["value"] = json.loads(tools.execute("ui_get_context", {"component_id": "runs"}))

    thread = threading.Thread(target=execute)
    thread.start()
    assert sent_event.wait(1)
    assert sent["command"] == {"type": "get_context", "component_id": "runs"}
    broker.resolve("browser-1", sent["id"], {"ok": True, "components": []})
    thread.join(1)
    assert result["value"] == {"ok": True, "components": []}


def test_ui_context_and_interaction_tools_can_be_enabled_separately():
    broker = AssistantUiBroker()
    read_only = AssistantUiToolExecutor(broker, "browser-1", context_enabled=True, interaction_enabled=False)

    assert [tool["name"] for tool in read_only.definitions()] == ["ui_get_context"]
