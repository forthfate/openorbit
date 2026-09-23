"""Curated SDK operations available to visual runner blueprints."""

from __future__ import annotations

from typing import Any, Mapping

from ..decorators.visual import visual_node
from .registry import VisualNodeDefinition, visual_nodes

visual_nodes.register(
    VisualNodeDefinition(
        kind="custom_script",
        group_key="advanced",
        display_name="Custom Script",
        title_key="visual.nodes.customScript.title",
        description_key="visual.nodes.customScript.description",
        is_custom_script=True,
    )
)


def _result(value: object) -> dict[str, object]:
    return {"result": value}


def _validate_snapshot(config: Mapping[str, Any]) -> None:
    if config.get("operation") not in {"save_before_each", "save_first_after_each", "restore_before_each"}:
        raise ValueError("has an unsupported snapshot operation")


def _validate_evidence(config: Mapping[str, Any]) -> None:
    if not isinstance(config.get("namespace", "visual_runner"), str):
        raise ValueError("requires a text evidence namespace")


def _validate_fields(config: Mapping[str, Any]) -> None:
    fields = config.get("fields")
    if (
        not isinstance(fields, list)
        or not fields
        or not all(isinstance(field, str) and field for field in fields)
    ):
        raise ValueError("requires one or more build field names")


@visual_node(
    kind="external_json_action",
    group_key="actions",
    display_name="External JSON action",
    default_config={"command_env": "ORBIT_AGENT_COMMAND", "action": "run-once", "input_data": {}},
    title_key="visual.nodes.externalJsonAction.title",
    description_key="visual.nodes.externalJsonAction.description",
    default_outputs=("result",),
    required_config=("command_env", "action"),
)
def external_json_action(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    return _result(
        ctx.run_json_action(
            command_env=config["command_env"],
            action=config["action"],
            input_env=config.get("input_env", "ORBIT_CYCLE_INPUT"),
            input_data=config.get("input_data", {}),
            timeout=config.get("timeout"),
            log_source=config.get("log_source"),
        )
    )


@visual_node(
    kind="command_action",
    group_key="actions",
    display_name="Command action",
    default_config={"command_env": "ORBIT_COMMAND", "action": "run"},
    title_key="visual.nodes.commandAction.title",
    description_key="visual.nodes.commandAction.description",
    default_outputs=("result",),
    required_config=("command_env", "action"),
)
def command_action(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    return _result(
        ctx.run_command_action(
            command_env=config["command_env"],
            action=config["action"],
            timeout=config.get("timeout"),
            log_source=config.get("log_source"),
        )
    )


@visual_node(
    kind="browser_journey",
    group_key="actions",
    display_name="Browser journey",
    default_config={},
    title_key="visual.nodes.browserJourney.title",
    description_key="visual.nodes.browserJourney.description",
    default_outputs=("evidence",),
)
def browser_journey(ctx: Any, _: Mapping[str, Any], __: Mapping[str, object]) -> dict[str, object]:
    return {"evidence": ctx.playwright_journey()}


@visual_node(
    kind="state_load",
    group_key="state",
    display_name="Load runner state",
    default_config={"name": "runner_state", "default": {}, "scope": "runner"},
    title_key="visual.nodes.stateLoad.title",
    description_key="visual.nodes.stateLoad.description",
    default_outputs=("state",),
    required_config=("name",),
)
def state_load(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    return {
        "state": ctx.load_state(config["name"], config.get("default"), scope=config.get("scope", "runner"))
    }


@visual_node(
    kind="state_save",
    group_key="state",
    display_name="Save runner state",
    default_config={"name": "runner_state", "value_input": "value", "scope": "runner"},
    title_key="visual.nodes.stateSave.title",
    description_key="visual.nodes.stateSave.description",
    default_inputs=("value",),
    default_outputs=("state",),
    required_config=("name",),
)
def state_save(ctx: Any, config: Mapping[str, Any], inputs: Mapping[str, object]) -> dict[str, object]:
    return {
        "state": ctx.save_state(
            config["name"],
            inputs.get(config.get("value_input", "value"), config.get("default")),
            scope=config.get("scope", "runner"),
        )
    }


@visual_node(
    kind="model_prompt",
    group_key="ai",
    display_name="Model prompt",
    default_config={"prompt": ""},
    title_key="visual.nodes.modelPrompt.title",
    description_key="visual.nodes.modelPrompt.description",
    default_outputs=("result",),
    required_config=("prompt",),
)
def model_prompt(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    return _result(ctx.complete_model(config["prompt"]))


@visual_node(
    kind="model_json",
    group_key="ai",
    display_name="Structured model prompt",
    default_config={"prompt": "", "description": "model response"},
    title_key="visual.nodes.modelJson.title",
    description_key="visual.nodes.modelJson.description",
    default_outputs=("result",),
    required_config=("prompt",),
)
def model_json(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    return _result(
        ctx.complete_model_json(config["prompt"], description=config.get("description", "model response"))
    )


@visual_node(
    kind="ai_agent",
    group_key="ai",
    display_name="AI agent",
    default_config={"prompt": "", "provider": "codex", "options": ""},
    title_key="visual.nodes.aiAgent.title",
    description_key="visual.nodes.aiAgent.description",
    default_outputs=("result",),
    required_config=("prompt", "provider"),
)
def ai_agent(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    return _result(
        ctx.run_ai_agent(
            config["prompt"],
            provider=config["provider"],
            options=config.get("options", ""),
            timeout=config.get("timeout", 1800),
        )
    )


@visual_node(
    kind="require_test_cases",
    group_key="state",
    display_name="Require test cases",
    default_config={"label": "fixed test case"},
    title_key="visual.nodes.requireTestCases.title",
    description_key="visual.nodes.requireTestCases.description",
    default_outputs=("contract",),
)
def require_test_cases(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    ctx.require_test_cases(label=config.get("label", "fixed test case"))
    return {"contract": True}


@visual_node(
    kind="snapshot",
    group_key="state",
    display_name="Snapshot",
    default_config={"operation": "save_before_each"},
    title_key="visual.nodes.snapshot.title",
    description_key="visual.nodes.snapshot.description",
    default_outputs=("snapshot",),
    required_config=("operation",),
    config_validator=_validate_snapshot,
)
def snapshot(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    operations = {
        "save_before_each": ctx.save_before_each_snapshot,
        "save_first_after_each": ctx.save_first_after_each_snapshot,
        "restore_before_each": ctx.restore_before_each_snapshot,
    }
    try:
        return {"snapshot": operations[config["operation"]]()}
    except KeyError as error:
        raise ValueError("unsupported snapshot operation") from error


@visual_node(
    kind="emit_evidence",
    group_key="evidence",
    display_name="Emit evidence",
    default_config={"namespace": "visual_runner"},
    title_key="visual.nodes.emitEvidence.title",
    description_key="visual.nodes.emitEvidence.description",
    config_validator=_validate_evidence,
)
def emit_evidence(ctx: Any, config: Mapping[str, Any], inputs: Mapping[str, object]) -> dict[str, object]:
    ctx.emit_result({config.get("namespace", "visual_runner"): dict(inputs)})
    return {}


@visual_node(
    kind="validate_command_environment",
    group_key="contracts",
    display_name="Validate command environment",
    title_key="visual.nodes.validateCommandEnvironment.title",
    description_key="visual.nodes.validateCommandEnvironment.description",
    default_config={"command_env": "ORBIT_COMMAND"},
    required_config=("command_env",),
    default_outputs=("command",),
)
def validate_command_environment(
    ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]
) -> dict[str, object]:
    """Validate an external command exactly once before a cycle begins."""
    return {"command": ctx.command_from_env(config["command_env"])}


@visual_node(
    kind="validate_build_fields",
    group_key="contracts",
    display_name="Validate build fields",
    title_key="visual.nodes.validateBuildFields.title",
    description_key="visual.nodes.validateBuildFields.description",
    default_config={"fields": ["browser_base_url"]},
    config_validator=_validate_fields,
    default_outputs=("contract",),
)
def validate_build_fields(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Require named build fields without exposing arbitrary context access."""
    missing = [field for field in config["fields"] if not ctx.build.get(field)]
    if missing:
        raise ValueError(f"Set required build field(s): {', '.join(missing)}")
    return {"contract": True}


@visual_node(
    kind="log_message",
    group_key="evidence",
    display_name="Log message",
    title_key="visual.nodes.logMessage.title",
    description_key="visual.nodes.logMessage.description",
    default_config={"message": ""},
    required_config=("message",),
)
def log_message(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Publish one explicit lifecycle log message."""
    ctx.log(config["message"])
    return {}


def _emit_cycle_result(ctx: Any, config: Mapping[str, Any], result: object) -> dict[str, object]:
    namespace = config.get("namespace", "visual_runner")
    result_key = config.get("result_key", "result")
    evidence = {str(result_key): result}
    if config.get("include_iteration", True):
        evidence = {"iteration": ctx.loop_index, **evidence}
    ctx.emit_result({str(namespace): evidence})
    return {"result": result, "evidence": evidence}


@visual_node(
    kind="command_cycle_action",
    group_key="actions",
    display_name="Command cycle action",
    title_key="visual.nodes.commandCycleAction.title",
    description_key="visual.nodes.commandCycleAction.description",
    default_config={
        "command_env": "ORBIT_COMMAND",
        "action": "run",
        "namespace": "external_adapter",
        "result_key": "result",
    },
    required_config=("command_env", "action", "namespace", "result_key"),
    default_outputs=("result", "evidence"),
)
def command_cycle_action(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Run a command action and emit the standard per-iteration evidence envelope."""
    result = ctx.run_command_action(
        command_env=config["command_env"],
        action=config["action"],
        timeout=config.get("timeout"),
        log_source=config.get("log_source"),
    )
    return _emit_cycle_result(ctx, config, result)


@visual_node(
    kind="json_cycle_action",
    group_key="actions",
    display_name="JSON cycle action",
    title_key="visual.nodes.jsonCycleAction.title",
    description_key="visual.nodes.jsonCycleAction.description",
    default_config={
        "command_env": "ORBIT_AGENT_COMMAND",
        "action": "run-once",
        "namespace": "agent_cycle",
        "result_key": "result",
        "input_data": {},
    },
    required_config=("command_env", "action", "namespace", "result_key"),
    default_outputs=("result", "evidence"),
)
def json_cycle_action(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Run a JSON evaluator action and emit the standard per-iteration evidence envelope."""
    result = ctx.run_json_action(
        command_env=config["command_env"],
        action=config["action"],
        input_env=config.get("input_env", "ORBIT_CYCLE_INPUT"),
        input_data=config.get("input_data", {}),
        timeout=config.get("timeout"),
        log_source=config.get("log_source"),
    )
    return _emit_cycle_result(ctx, config, result)
