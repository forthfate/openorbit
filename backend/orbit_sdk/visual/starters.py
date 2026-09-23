"""SDK-owned starter blueprints for the visual runner editor."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .layout import initial_positions


def _node(
    suffix: str,
    kind: str,
    title_key: str,
    phase: str,
    *,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    config: dict[str, Any] | None = None,
    x: int = 100,
    y: int = 120,
) -> dict[str, Any]:
    return {
        "id": suffix,
        "kind": kind,
        "title": suffix.replace("-", " ").replace("_", " ").title(),
        "title_key": title_key,
        "phase": phase,
        "inputs": inputs or [],
        "outputs": outputs or [],
        "config": config or {},
        "script": "",
        "position": {"x": x, "y": y},
    }


def _cycle_starter(
    starter_id: str,
    *,
    title_key: str,
    description_key: str,
    action_kind: str,
    command_env: str,
    namespace: str,
    action_names: tuple[str, str, str, str],
    contract_kind: str,
    contract_config: dict[str, Any],
    payload: dict[str, Any] | None = None,
    log_source: str | None = None,
    close_message: str,
    final_message: str,
) -> dict[str, Any]:
    """Build the seven visual steps shared by the shipped external cycles."""
    names = ("validate", "preflight", "prepare", "run", "collect", "close", "finalize")
    phases = ("before_all", "before_all", "before_each", "execute", "verify", "after_each", "after_all")
    outputs = ("contract", "preflight", "prepared", "result", "evidence", "complete", "final")
    nodes = [
        _node(
            names[0],
            contract_kind,
            "visual.starters.validate",
            phases[0],
            outputs=[outputs[0]],
            config=contract_config,
        )
    ]
    result_keys = ("preflight", "prepared", "result", "evidence")
    for index, (name, phase, result_key, action) in enumerate(
        zip(names[1:5], phases[1:5], result_keys, action_names), 1
    ):
        config: dict[str, Any] = {
            "command_env": command_env,
            "action": action,
            "namespace": namespace,
            "result_key": result_key,
            "timeout": 3600,
            "log_source": log_source,
            "include_iteration": name != "preflight",
        }
        if payload is not None:
            config.update({"input_env": "ORBIT_CYCLE_INPUT", "input_data": payload})
        nodes.append(
            _node(
                name,
                action_kind,
                f"visual.starters.{name}",
                phase,
                inputs=[outputs[index - 1]],
                outputs=[outputs[index]],
                config=config,
            )
        )
    nodes.extend(
        [
            _node(
                names[5],
                "log_message",
                "visual.starters.close",
                phases[5],
                inputs=[outputs[4]],
                outputs=[outputs[5]],
                config={"message": close_message},
            ),
            _node(
                names[6],
                "log_message",
                "visual.starters.finalize",
                phases[6],
                inputs=[outputs[5]],
                outputs=[outputs[6]],
                config={"message": final_message},
            ),
        ]
    )
    for node, position in zip(nodes, initial_positions(node["phase"] for node in nodes)):
        node["position"] = position
    edges = [{"source": names[index], "target": names[index + 1], "kind": "execution"} for index in range(6)]
    edges.extend(
        [
            {"source": "close", "target": "prepare", "kind": "loop", "label": "next cycle"},
            {"source": "close", "target": "finalize", "kind": "condition", "label": "completed"},
        ]
    )
    return {
        "id": starter_id,
        "group_key": "starters",
        "title_key": title_key,
        "description_key": description_key,
        "blueprint": {"schema_version": 1, "nodes": nodes, "edges": edges},
    }


_AGENT_PAYLOAD = {
    "iteration": {"$ctx": "loop_index"},
    "build": {"$ctx": "build"},
    "test_cases": {"$ctx": "test_cases"},
}
_PROBE_PAYLOAD = {
    "iteration": {"$ctx": "loop_index"},
    "build": {"$ctx": "build"},
    "probes": {"$ctx": "test_cases"},
}


STARTERS: tuple[dict[str, Any], ...] = (
    _cycle_starter(
        "json_agent_cycle",
        title_key="visual.starters.jsonAgentCycle.title",
        description_key="visual.starters.jsonAgentCycle.description",
        action_kind="json_cycle_action",
        command_env="ORBIT_AGENT_COMMAND",
        namespace="agent_cycle",
        action_names=("status", "prepare", "run-once", "collect-evidence"),
        contract_kind="require_test_cases",
        contract_config={"label": "fixed test case"},
        payload=_AGENT_PAYLOAD,
        log_source="agent-cycle",
        close_message="Completed one bounded external agent cycle",
        final_message="Finalized the external agent",
    ),
    _cycle_starter(
        "command_adapter",
        title_key="visual.starters.commandAdapter.title",
        description_key="visual.starters.commandAdapter.description",
        action_kind="command_cycle_action",
        command_env="ORBIT_ADAPTER_COMMAND",
        namespace="external_adapter",
        action_names=("status", "prepare", "run-once", "collect-evidence"),
        contract_kind="validate_command_environment",
        contract_config={"command_env": "ORBIT_ADAPTER_COMMAND"},
        log_source="external-adapter",
        close_message="Completed one bounded external adapter cycle",
        final_message="Finalized the external automation evaluation",
    ),
    _cycle_starter(
        "evidence_gated_probe_cycle",
        title_key="visual.starters.evidenceGatedProbeCycle.title",
        description_key="visual.starters.evidenceGatedProbeCycle.description",
        action_kind="json_cycle_action",
        command_env="ORBIT_PROBE_COMMAND",
        namespace="probe_gate",
        action_names=("preflight", "prepare", "run-probes", "collect-evidence"),
        contract_kind="require_test_cases",
        contract_config={"label": "fixed probe case"},
        payload=_PROBE_PAYLOAD,
        log_source="probe-gate",
        close_message="Completed one bounded probe matrix cycle",
        final_message="Finalized the probe matrix",
    ),
    {
        "id": "browser_journey",
        "group_key": "starters",
        "title_key": "visual.starters.browserJourney.title",
        "description_key": "visual.starters.browserJourney.description",
        "blueprint": {
            "schema_version": 1,
            "nodes": [
                _node(
                    "validate",
                    "require_test_cases",
                    "visual.starters.validateBrowser",
                    "before_all",
                    outputs=["contract"],
                    config={"label": "browser journey case"},
                ),
                _node(
                    "journey",
                    "browser_journey",
                    "visual.starters.runBrowser",
                    "execute",
                    inputs=["contract"],
                    outputs=["evidence"],
                    x=390,
                    y=290,
                ),
                _node(
                    "publish",
                    "emit_evidence",
                    "visual.starters.publishBrowser",
                    "verify",
                    inputs=["evidence"],
                    config={"namespace": "browser_journey"},
                    x=680,
                ),
            ],
            "edges": [
                {"source": "validate", "target": "journey", "kind": "execution"},
                {"source": "journey", "target": "publish", "kind": "execution"},
            ],
        },
    },
    {
        "id": "user_journey_cycle",
        "group_key": "starters",
        "title_key": "visual.starters.userJourneyCycle.title",
        "description_key": "visual.starters.userJourneyCycle.description",
        "blueprint": {
            "schema_version": 1,
            "nodes": [
                _node(
                    "validate_runtime",
                    "validate_browser_runtime",
                    "visual.starters.validateBrowser",
                    "before_all",
                    outputs=["browser_runtime"],
                ),
                _node(
                    "validate_contract",
                    "require_test_cases",
                    "visual.starters.validate",
                    "before_all",
                    inputs=["browser_runtime"],
                    outputs=["journey_contract"],
                    config={"label": "fixed journey case"},
                    x=350,
                    y=290,
                ),
                _node(
                    "load_state",
                    "initialize_user_journey_state",
                    "visual.starters.loadJourney",
                    "before_each",
                    inputs=["journey_contract"],
                    outputs=["journey_state"],
                    config={"namespace": "user_journey"},
                    x=600,
                ),
                _node(
                    "plan",
                    "plan_user_journey",
                    "visual.starters.planJourney",
                    "before_each",
                    inputs=["journey_state"],
                    outputs=["journey_plan"],
                    config={"namespace": "user_journey"},
                    x=850,
                    y=290,
                ),
                _node(
                    "run",
                    "run_user_journey",
                    "visual.starters.runJourney",
                    "execute",
                    inputs=["journey_plan"],
                    outputs=["journey_evidence"],
                    config={"namespace": "user_journey"},
                    x=1100,
                ),
                _node(
                    "review",
                    "publish_user_journey_handoff",
                    "visual.starters.reviewJourney",
                    "verify",
                    inputs=["journey_evidence"],
                    outputs=["journey_handoff"],
                    config={"namespace": "user_journey"},
                    x=1350,
                    y=290,
                ),
                _node(
                    "retain",
                    "log_message",
                    "visual.starters.retainJourney",
                    "after_each",
                    inputs=["journey_handoff"],
                    outputs=["iteration_complete"],
                    config={"message": "Closed this bounded user journey"},
                    x=1600,
                ),
                _node(
                    "finalize",
                    "log_message",
                    "visual.starters.finalize",
                    "after_all",
                    inputs=["iteration_complete"],
                    outputs=["final_status"],
                    config={"message": "Finalized the user journey evaluation"},
                    x=1850,
                    y=290,
                ),
            ],
            "edges": [
                {"source": "validate_runtime", "target": "validate_contract", "kind": "execution"},
                {"source": "validate_contract", "target": "load_state", "kind": "execution"},
                {"source": "load_state", "target": "plan", "kind": "execution"},
                {"source": "plan", "target": "run", "kind": "execution"},
                {"source": "run", "target": "review", "kind": "execution"},
                {"source": "review", "target": "retain", "kind": "execution"},
                {"source": "retain", "target": "plan", "kind": "loop", "label": "next iteration"},
                {"source": "retain", "target": "finalize", "kind": "condition", "label": "completed"},
            ],
        },
    },
    {
        "id": "site_exploration",
        "group_key": "starters",
        "title_key": "visual.starters.siteExploration.title",
        "description_key": "visual.starters.siteExploration.description",
        "blueprint": {
            "schema_version": 1,
            "nodes": [
                _node(
                    "validate",
                    "validate_build_fields",
                    "visual.starters.validateSite",
                    "before_all",
                    outputs=["site_target"],
                    config={"fields": ["browser_base_url"]},
                ),
                _node(
                    "explore",
                    "explore_rendered_site",
                    "visual.starters.exploreSite",
                    "execute",
                    inputs=["site_target"],
                    outputs=["rendered_pages"],
                    config={"namespace": "site_exploration", "max_clicks": 3},
                    x=390,
                    y=290,
                ),
                _node(
                    "review",
                    "log_message",
                    "visual.starters.reviewEvidence",
                    "verify",
                    inputs=["rendered_pages"],
                    outputs=["product_review"],
                    config={"message": "Retained rendered exploration evidence for review"},
                    x=680,
                ),
                _node(
                    "finalize",
                    "log_message",
                    "visual.starters.finalize",
                    "after_all",
                    inputs=["product_review"],
                    outputs=["completed_review"],
                    config={"message": "Finalized the bounded site exploration review"},
                    x=970,
                    y=290,
                ),
            ],
            "edges": [
                {"source": "validate", "target": "explore", "kind": "execution"},
                {"source": "explore", "target": "review", "kind": "execution"},
                {"source": "review", "target": "finalize", "kind": "execution"},
            ],
        },
    },
    {
        "id": "source_aware_browser_journey",
        "group_key": "starters",
        "title_key": "visual.starters.sourceAwareBrowserJourney.title",
        "description_key": "visual.starters.sourceAwareBrowserJourney.description",
        "blueprint": {
            "schema_version": 1,
            "nodes": [
                _node(
                    "validate",
                    "validate_source_contract",
                    "visual.starters.validateSource",
                    "before_all",
                    outputs=["source_contract"],
                    config={"namespace": "source_aware_journey"},
                ),
                _node(
                    "run",
                    "run_source_aware_browser_journey",
                    "visual.starters.runBrowser",
                    "execute",
                    inputs=["source_contract"],
                    outputs=["browser_evidence"],
                    config={"namespace": "source_aware_journey"},
                    x=390,
                    y=290,
                ),
                _node(
                    "publish",
                    "log_message",
                    "visual.starters.publishBrowser",
                    "verify",
                    inputs=["browser_evidence"],
                    outputs=["review_ready"],
                    config={"message": "Published source context with rendered browser evidence"},
                    x=680,
                ),
                _node(
                    "close",
                    "log_message",
                    "visual.starters.close",
                    "after_each",
                    inputs=["review_ready"],
                    outputs=["cycle_complete"],
                    config={"message": "Completed one bounded source-aware browser journey"},
                    x=970,
                    y=290,
                ),
                _node(
                    "finalize",
                    "log_message",
                    "visual.starters.finalize",
                    "after_all",
                    inputs=["cycle_complete"],
                    outputs=["journey_complete"],
                    config={"message": "Finalized the source-aware browser evaluation"},
                    x=1260,
                ),
            ],
            "edges": [
                {"source": "validate", "target": "run", "kind": "execution"},
                {"source": "run", "target": "publish", "kind": "execution"},
                {"source": "publish", "target": "close", "kind": "execution"},
                {"source": "close", "target": "run", "kind": "loop", "label": "next iteration"},
                {"source": "close", "target": "finalize", "kind": "condition", "label": "completed"},
            ],
        },
    },
    {
        "id": "user_journey_smoke_test",
        "group_key": "starters",
        "title_key": "visual.starters.userJourneySmokeTest.title",
        "description_key": "visual.starters.userJourneySmokeTest.description",
        "blueprint": {
            "schema_version": 1,
            "nodes": [
                _node(
                    "validate_runtime",
                    "validate_browser_runtime",
                    "visual.starters.validateBrowser",
                    "before_all",
                    outputs=["browser_target"],
                ),
                _node(
                    "validate_contract",
                    "require_test_cases",
                    "visual.starters.validate",
                    "before_all",
                    inputs=["browser_target"],
                    outputs=["journey_contract"],
                    config={"label": "fixed journey case"},
                    x=350,
                    y=290,
                ),
                _node(
                    "run",
                    "run_browser_smoke",
                    "visual.starters.runBrowser",
                    "execute",
                    inputs=["journey_contract"],
                    outputs=["journey_evidence"],
                    config={"namespace": "browser_smoke", "fail_on_unpassed": True},
                    x=600,
                ),
                _node(
                    "verify",
                    "log_message",
                    "visual.starters.reviewEvidence",
                    "verify",
                    inputs=["journey_evidence"],
                    outputs=["journey_verdict"],
                    config={"message": "Quick start browser evaluation completed"},
                    x=850,
                    y=290,
                ),
                _node(
                    "finalize",
                    "log_message",
                    "visual.starters.finalize",
                    "after_all",
                    inputs=["journey_verdict"],
                    outputs=["completed_evaluation"],
                    config={"message": "Finalized the one-shot browser evaluation"},
                    x=1100,
                ),
            ],
            "edges": [
                {"source": "validate_runtime", "target": "validate_contract", "kind": "execution"},
                {"source": "validate_contract", "target": "run", "kind": "execution"},
                {"source": "run", "target": "verify", "kind": "execution"},
                {"source": "verify", "target": "finalize", "kind": "execution"},
            ],
        },
    },
)


def catalog() -> list[dict[str, Any]]:
    """Return isolated starter definitions so API consumers cannot mutate SDK data."""
    return deepcopy(list(STARTERS))
