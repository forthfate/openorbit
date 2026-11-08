from __future__ import annotations

from orbit_sdk.visual.journeys import plan_persona_action, reflect_persona_session


class PersonaContext:
    loop_index = 3

    def __init__(self):
        self.state = {
            "persona": "A careful buyer",
            "current_goal": "Check an order status",
            "feeling": "concerned",
            "next_intent": "Find my order details.",
            "learnings": [],
            "reported_issues": [],
            "history": [{"iteration": 2, "message": {"utterance": "Where is my order?"}}],
            "observation": {
                "available_actions": [
                    {"id": "link-0", "href": "https://example.test/orders", "label": "Orders"}
                ],
                "before_url": "https://example.test/",
            },
            "evidence": {"url": "https://example.test/orders"},
        }
        self.prompts: list[str] = []
        self.events: list[dict] = []
        self.responses = [
            {
                "utterance": "결제한 주문이 아직 보이지 않아요. 주문 상태를 확인해 주세요.",
                "thought": "결제 반영이 늦는지 걱정된다.",
                "rationale": "주문 내역을 찾을 수 없다.",
                "intent": "주문 상태 확인",
            },
            {
                "action_id": "link-0",
                "rationale": "주문 목록에서 상태를 확인할 수 있다.",
                "expected_signal": "주문 상태",
            },
            {
                "feeling": "안심했다",
                "learning": "주문 목록에서 상태를 확인할 수 있었다.",
                "issue": {"title": "", "evidence": "", "severity": "low"},
                "next_intent": "주문 상태를 다시 확인한다.",
            },
        ]

    def load_state(self, _namespace, _default):
        return self.state

    def save_state(self, _namespace, value):
        self.state = value

    def complete_model_json(self, prompt, *, description):
        self.prompts.append(prompt)
        return self.responses.pop(0)

    def emit_result(self, value):
        self.events.append(value)

    def log(self, _message):
        pass

    def save_data_file(self, *_args, **_kwargs):
        return {"relative_path": "autonomous-persona/iteration-3.json"}


def test_persona_message_is_generated_before_the_action_agent_and_retained_in_history():
    ctx = PersonaContext()

    plan = plan_persona_action(ctx, {"namespace": "persona"}, {})["persona_plan"]

    assert plan["message"]["utterance"].startswith("결제한 주문")
    assert plan["action"]["id"] == "link-0"
    assert "A careful buyer" not in ctx.prompts[1]
    assert "Where is my order?" not in ctx.prompts[1]
    assert plan["message"]["thought"] not in ctx.prompts[1]
    assert plan["message"]["rationale"] not in ctx.prompts[1]
    assert plan["message"]["utterance"] in ctx.prompts[1]

    reflect_persona_session(ctx, {"namespace": "persona"}, {})

    assert ctx.state["history"][-1]["message"] == plan["message"]
