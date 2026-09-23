"""Trusted built-in runner templates exposed as faithful visual blueprints.

Unlike user-authored code, these sources ship with OpenOrbit.  Their graph
annotations are read as data and each visual node delegates to the canonical
step function.  This keeps Visual Mode and the original template behavior in
lockstep without attempting to parse arbitrary Python back into a graph.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .layout import initial_positions

_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE_ROOT = _ROOT / "templates"
_CANONICAL_ROOT = Path(__file__).resolve().parent / "canonical"


@dataclass(frozen=True)
class TemplateStep:
    """One graph-declared function from a trusted built-in runner."""

    id: str
    function_name: str
    title: str
    phase: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    description: str | None


@dataclass(frozen=True)
class BuiltinTemplate:
    """Parsed graph data plus the canonical source path for one runner."""

    id: str
    display_name: str
    source: Path
    steps: tuple[TemplateStep, ...]
    edges: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class TemplateDefinition:
    """One authoritative Visual Mode definition for a shipped runner asset.

    ``blueprint`` is the persisted representation, while ``source_sha256``
    records which canonical template revision it was derived from.  The
    every node is a direct SDK operation, so callers never need to know the
    source-level function boundaries of a shipped template.
    """

    id: str
    display_name: str
    blueprint: dict[str, object]
    source_sha256: str


def _literal(value: ast.AST, default: Any = None) -> Any:
    try:
        return ast.literal_eval(value)
    except (ValueError, TypeError):
        return default


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
        return f"{call.func.value.id}.{call.func.attr}"
    return None


def _template_id(path: Path) -> str:
    return path.relative_to(_CANONICAL_ROOT).parent.as_posix().replace("/", ":")


def _display_name(path: Path) -> str:
    relative = path.relative_to(_CANONICAL_ROOT)
    metadata = (
        _TEMPLATE_ROOT
        / relative.parent
        / ("manifest.json" if "quick-starts" in relative.parts else "template.json")
    )
    if metadata.is_file():
        try:
            values = json.loads(metadata.read_text(encoding="utf-8"))
            if isinstance(values.get("name"), str):
                return values["name"]
        except (OSError, ValueError):
            pass
    return path.parent.name.replace("-", " ").title()


def _parse(path: Path) -> BuiltinTemplate | None:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return None
    steps: list[TemplateStep] = []
    edges: list[dict[str, object]] = []
    for statement in module.body:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and _call_name(statement.value) == "graph.connect"
        ):
            call = statement.value
            if len(call.args) < 2:
                continue
            source, target = _literal(call.args[0]), _literal(call.args[1])
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            keywords = {item.arg: _literal(item.value) for item in call.keywords if item.arg}
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "kind": keywords.get("kind", "execution"),
                    "label": keywords.get("label"),
                    "source_port": keywords.get("source_port"),
                    "target_port": keywords.get("target_port"),
                }
            )
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        graph: dict[str, Any] | None = None
        for decorator in statement.decorator_list:
            if not isinstance(decorator, ast.Call) or _call_name(decorator) != "graph.step":
                continue
            if not decorator.args:
                continue
            node_id = _literal(decorator.args[0])
            if not isinstance(node_id, str):
                continue
            keywords = {item.arg: _literal(item.value) for item in decorator.keywords if item.arg}
            graph = {"id": node_id, **keywords}
        if graph and isinstance(graph.get("phase"), str):
            steps.append(
                TemplateStep(
                    id=graph["id"],
                    function_name=statement.name,
                    title=str(graph.get("title") or graph["id"].replace("-", " ").title()),
                    phase=graph["phase"],
                    inputs=tuple(graph.get("inputs") or ()),
                    outputs=tuple(graph.get("outputs") or ()),
                    description=graph.get("description")
                    if isinstance(graph.get("description"), str)
                    else None,
                )
            )
    if not steps:
        return None
    return BuiltinTemplate(_template_id(path), _display_name(path), path, tuple(steps), tuple(edges))


@lru_cache(maxsize=1)
def templates() -> dict[str, BuiltinTemplate]:
    """Discover all repository-shipped runner and Quick Start sources."""
    paths = [
        path
        for path in sorted(_CANONICAL_ROOT.glob("**/runner.py"))
        if path.parent.name not in {"quick-start.example", "runner-template.example"}
    ]
    values = [_parse(path) for path in paths]
    return {value.id: value for value in values if value is not None}


def catalog() -> list[dict[str, Any]]:
    """Return one visual starter per trusted built-in runner source."""
    return [
        {
            "id": f"builtin:{definition.id}",
            "group_key": "templates",
            "title_key": f"visual.templates.{definition.id.replace(':', '.').replace('-', '_')}.title",
            "description_key": f"visual.templates.{definition.id.replace(':', '.').replace('-', '_')}.description",
            "display_name": definition.display_name,
            "blueprint": deepcopy(definition.blueprint),
        }
        for definition in definitions().values()
    ]


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


def _node(step: TemplateStep, kind: str, config: Mapping[str, object]) -> dict[str, object]:
    """Create a persisted node while retaining the template's public graph ID."""
    return {
        "id": step.id,
        "kind": kind,
        "title": step.title,
        "phase": step.phase,
        "inputs": list(step.inputs),
        "outputs": list(step.outputs),
        "description": step.description,
        "config": dict(config),
        "script": "",
    }


def _cycle_materials(
    *,
    command_env: str,
    namespace: str,
    actions: tuple[str, str, str, str],
    payload: Mapping[str, object],
    action_kind: str,
    contract_kind: str,
    contract_config: Mapping[str, object],
    close: str,
    finalize: str,
    log_source: str,
) -> dict[str, tuple[str, Mapping[str, object]]]:
    """Return the reusable operations shared by external evaluator cycles."""
    names = ("preflight", "prepared", "result", "evidence")
    step_ids = ("preflight", "prepare", "run", "collect")
    values: dict[str, tuple[str, Mapping[str, object]]] = {}
    for step_id, result_key, action in zip(step_ids, names, actions):
        values[step_id] = (
            action_kind,
            {
                "command_env": command_env,
                "action": action,
                "namespace": namespace,
                "result_key": result_key,
                "input_env": "ORBIT_CYCLE_INPUT",
                "input_data": payload,
                "timeout": 3600,
                "log_source": log_source,
                "include_iteration": step_id != "preflight",
            },
        )
    values.update(
        {
            "validate": (contract_kind, contract_config),
            "close": ("log_message", {"message": close}),
            "finalize": ("log_message", {"message": finalize}),
        }
    )
    return values


def _materials_for(template: BuiltinTemplate) -> dict[str, tuple[str, Mapping[str, object]]]:
    """Map canonical step IDs to SDK materials, never to palette-only assets.

    The keys intentionally describe runner semantics rather than Python function
    names.  A visual Blueprint therefore survives an implementation refactor in
    a shipped template without gaining a new template-specific node type.
    """
    template_id = template.id
    if template_id in {
        "runner-templates:json-agent-cycle",
        "quick-starts:openorbit.ai-experience-improvement",
    }:
        return _cycle_materials(
            command_env="ORBIT_AGENT_COMMAND",
            namespace="agent_cycle",
            actions=("status", "prepare", "run-once", "collect-evidence"),
            payload=_AGENT_PAYLOAD,
            action_kind="json_cycle_action",
            contract_kind="require_test_cases",
            contract_config={},
            close="Completed one bounded external agent cycle",
            finalize="Finalized the external agent",
            log_source="agent-cycle",
        )
    if template_id == "runner-templates:external-command-adapter":
        return _cycle_materials(
            command_env="ORBIT_ADAPTER_COMMAND",
            namespace="external_adapter",
            actions=("status", "prepare", "run-once", "collect-evidence"),
            payload={},
            action_kind="command_cycle_action",
            contract_kind="validate_command_environment",
            contract_config={"command_env": "ORBIT_ADAPTER_COMMAND"},
            close="Completed one bounded external adapter cycle",
            finalize="Finalized the external automation evaluation",
            log_source="external-adapter",
        )
    if template_id in {
        "runner-templates:evidence-gated-probe-cycle",
        "quick-starts:openorbit.ai-slo-drift-monitor",
    }:
        return _cycle_materials(
            command_env="ORBIT_PROBE_COMMAND",
            namespace="probe_gate",
            actions=("preflight", "prepare", "run-probes", "collect-evidence"),
            payload=_PROBE_PAYLOAD,
            action_kind="json_cycle_action",
            contract_kind="require_test_cases",
            contract_config={"label": "fixed probe case"},
            close="Completed one bounded probe matrix cycle",
            finalize="Finalized the probe matrix",
            log_source="probe-gate",
        )
    if template_id in {"runner-templates:site-exploration", "quick-starts:openorbit.site-exploration-review"}:
        return {
            "validate-site": ("validate_build_fields", {"fields": ["browser_base_url"]}),
            "explore-site": ("explore_rendered_site", {"namespace": "site_exploration", "max_clicks": 3}),
            "review-evidence": (
                "log_message",
                {"message": "Retained rendered exploration evidence for review"},
            ),
            "finalize-review": ("log_message", {"message": "Finalized the bounded site exploration review"}),
        }
    if template_id == "runner-templates:source-aware-browser-journey":
        return {
            "validate-source-contract": ("validate_source_contract", {"namespace": "source_aware_journey"}),
            "run-browser-journey": (
                "run_source_aware_browser_journey",
                {"namespace": "source_aware_journey"},
            ),
            "publish-rendered-evidence": (
                "log_message",
                {"message": "Published source context with rendered browser evidence"},
            ),
            "close-source-aware-cycle": (
                "log_message",
                {"message": "Completed one bounded source-aware browser journey"},
            ),
            "finalize-source-aware-journey": (
                "log_message",
                {"message": "Finalized the source-aware browser evaluation"},
            ),
        }
    if template_id in {"runner-templates:user-journey-cycle", "quick-starts:openorbit.critical-flow-proof"}:
        namespace = "critical_flow" if "critical-flow" in template_id else "user_journey"
        prefix = "critical-flow" if "critical-flow" in template_id else "user-journey"
        return {
            f"validate-{prefix}-runtime": ("validate_browser_runtime", {}),
            f"validate-{prefix}": ("require_test_cases", {"label": "fixed journey case"}),
            f"load-{prefix}-state": ("initialize_user_journey_state", {"namespace": namespace}),
            f"plan-{prefix}": ("plan_user_journey", {"namespace": namespace}),
            f"run-{prefix}": ("run_user_journey", {"namespace": namespace}),
            f"review-{prefix}": ("publish_user_journey_handoff", {"namespace": namespace}),
            f"retain-{prefix}": ("log_message", {"message": "Closed this bounded user journey"}),
            f"finalize-{prefix}": ("log_message", {"message": "Finalized the user journey evaluation"}),
        }
    if template_id == "quick-starts:openorbit.user-journey-smoke-test":
        return {
            "validate-browser-runtime": ("validate_browser_runtime", {}),
            "validate-browser-journey": ("require_test_cases", {"label": "browser journey case"}),
            "run-browser-journey": (
                "run_browser_smoke",
                {"namespace": "browser_smoke", "fail_on_unpassed": True},
            ),
            "verify-browser-evidence": (
                "log_message",
                {"message": "Quick start browser evaluation completed"},
            ),
            "finalize-browser-evaluation": (
                "log_message",
                {"message": "Finalized the one-shot browser evaluation"},
            ),
        }
    if template_id == "runner-templates:native-improvement-cycle":
        return {
            "validate-target": ("validate_git_repository", {}),
            "validate-evaluation-inputs": ("validate_improvement_inputs", {}),
            "snapshot-baseline": ("snapshot", {"operation": "save_before_each"}),
            "prepare-prompt": ("prepare_managed_prompt", {"mode": "apply_accepted"}),
            "exercise-target": ("exercise_managed_prompt", {"include_candidate": True}),
            "assess-candidate": ("assess_prompt_candidate", {}),
            "retain-iteration": ("retain_improvement_iteration", {}),
            "restore-baseline": ("restore_improvement_baseline", {}),
        }
    if template_id == "quick-starts:openorbit.agent-self-improvement":
        return {
            "validate-target": ("validate_git_repository", {}),
            "validate-evaluation-inputs": ("validate_improvement_inputs", {}),
            "prepare-prompt": ("prepare_managed_prompt", {"mode": "isolated_worktree"}),
            "exercise-target": ("exercise_managed_prompt", {}),
            "retain-iteration": (
                "log_message",
                {"message": "Retained target-AI responses and supervisor assessment evidence"},
            ),
            "propose-agent-change": (
                "create_agent_proposal",
                {"provider": "${agent_provider}", "options": "${agent_options}"},
            ),
        }
    if template_id == "quick-starts:openorbit.continuous-user-journey":
        return {
            "validate-browser-runtime": ("validate_browser_runtime", {}),
            "validate": ("validate_persona_contract", {}),
            "observe": ("observe_persona_page", {"namespace": "autonomous_persona"}),
            "decide": ("plan_persona_action", {"namespace": "autonomous_persona"}),
            "act": ("run_persona_action", {"namespace": "autonomous_persona"}),
            "reflect": ("reflect_persona_session", {"namespace": "autonomous_persona"}),
            "finalize": ("log_message", {"message": "Finalized the autonomous persona journey"}),
        }
    if template_id == "runner-templates:autonomous-persona-journey":
        return {
            "validate": ("validate_persona_contract", {}),
            "observe": ("observe_persona_page", {"namespace": "autonomous_persona"}),
            "decide": ("plan_persona_action", {"namespace": "autonomous_persona"}),
            "act": ("run_persona_action", {"namespace": "autonomous_persona"}),
            "reflect": ("reflect_persona_session", {"namespace": "autonomous_persona"}),
            "finalize-persona-journey": (
                "log_message",
                {"message": "Finalized the autonomous persona journey"},
            ),
        }
    if template_id == "runner-templates:playwright-continuous-journey":
        return {
            "validate": ("validate_browser_journey_contract", {}),
            "plan": ("plan_user_journey", {"namespace": "continuous_journey"}),
            "exercise": ("run_user_journey", {"namespace": "continuous_journey"}),
            "retain": ("publish_user_journey_handoff", {"namespace": "continuous_journey"}),
            "close-journey-cycle": (
                "log_message",
                {"message": "Completed one bounded continuous browser journey"},
            ),
            "finalize-browser-journey": (
                "log_message",
                {"message": "Finalized the continuous browser journey"},
            ),
        }
    if template_id == "runner-templates:selenium-external-journey":
        return {
            "ready": ("validate_command_environment", {"command_env": "ORBIT_SELENIUM_COMMAND"}),
            "prepare": (
                "command_cycle_action",
                {
                    "command_env": "ORBIT_SELENIUM_COMMAND",
                    "action": "prepare",
                    "namespace": "selenium_journey",
                    "result_key": "prepared",
                    "timeout": 3600,
                    "log_source": "selenium-adapter",
                },
            ),
            "run": (
                "command_cycle_action",
                {
                    "command_env": "ORBIT_SELENIUM_COMMAND",
                    "action": "run-once",
                    "namespace": "selenium_journey",
                    "result_key": "result",
                    "timeout": 3600,
                    "log_source": "selenium-adapter",
                },
            ),
            "collect": (
                "command_cycle_action",
                {
                    "command_env": "ORBIT_SELENIUM_COMMAND",
                    "action": "collect-evidence",
                    "namespace": "selenium_journey",
                    "result_key": "evidence",
                    "timeout": 3600,
                    "log_source": "selenium-adapter",
                },
            ),
            "close-selenium-cycle": (
                "log_message",
                {"message": "Completed one bounded Selenium adapter cycle"},
            ),
            "finalize-selenium-journey": (
                "log_message",
                {"message": "Finalized the Selenium adapter evaluation"},
            ),
        }
    if template_id == "runner-templates:tailwind-source-aware":
        return {
            "inspect-source": ("validate_tailwind_source", {}),
            "run-browser": ("run_source_aware_browser_journey", {"namespace": "tailwind_journey"}),
            "publish-evidence": (
                "log_message",
                {"message": "Published Tailwind source context with rendered browser evidence"},
            ),
            "close-tailwind-cycle": (
                "log_message",
                {"message": "Completed one bounded Tailwind browser journey"},
            ),
            "finalize-tailwind-journey": (
                "log_message",
                {"message": "Finalized the Tailwind browser evaluation"},
            ),
        }
    return {}


def _material_for_step(
    template: BuiltinTemplate, step: TemplateStep
) -> tuple[str, Mapping[str, object]] | None:
    """Resolve one canonical graph ID to a reusable operation.

    The three external-cycle families use different public graph IDs while
    sharing the same seven operations, so their small ID vocabulary is handled
    here instead of creating per-template node kinds.
    """
    materials = _materials_for(template)
    direct = materials.get(step.id)
    if direct:
        return direct
    if step.id == "check-adapter":
        return materials.get("preflight")
    cycle_key = next(
        (
            key
            for key in ("validate", "preflight", "prepare", "run", "collect", "close", "finalize")
            if step.id.startswith(key) or f"-{key}-" in step.id or step.id.endswith(f"-{key}")
        ),
        None,
    )
    return materials.get(cycle_key or "")


@lru_cache(maxsize=1)
def definitions() -> dict[str, TemplateDefinition]:
    """Build stable TemplateDefinitions from every built-in runner graph."""
    result: dict[str, TemplateDefinition] = {}
    for template in templates().values():
        # The graph and lifecycle IDs are part of a runner's observable
        # contract. Preserve them verbatim so generated executions retain the
        # same step evidence as the canonical source.
        ids = {step.id: step.id for step in template.steps}
        nodes = []
        for step in template.steps:
            material = _material_for_step(template, step)
            if material is None:
                raise RuntimeError(f"no reusable visual material is defined for {template.id}/{step.id}")
            nodes.append(_node(step, material[0], material[1]))
        for node, position in zip(nodes, initial_positions(step.phase for step in template.steps)):
            node["position"] = position
        edges = [
            {**edge, "source": ids[edge["source"]], "target": ids[edge["target"]]}
            for edge in template.edges
            if edge["source"] in ids and edge["target"] in ids
        ]
        result[template.id] = TemplateDefinition(
            id=template.id,
            display_name=template.display_name,
            blueprint={"schema_version": 1, "nodes": nodes, "edges": edges},
            source_sha256=hashlib.sha256(template.source.read_bytes()).hexdigest(),
        )
    return result


def definition_for_runner_template(template_id: str) -> TemplateDefinition | None:
    """Return the Visual definition for a built-in runner-template ID."""
    return definitions().get(f"runner-templates:{template_id}")


def definition_for_quick_start(quick_start_id: str) -> TemplateDefinition | None:
    """Return the Visual definition for a built-in Quick Start runner."""
    return definitions().get(f"quick-starts:{quick_start_id}")


def instantiate_definition(
    definition: TemplateDefinition, parameters: Mapping[str, str] | None = None
) -> dict[str, object]:
    """Return a blueprint bound to approved Quick Start parameter values."""
    blueprint = deepcopy(definition.blueprint)
    values = dict(parameters or {})
    if values:
        blueprint["parameters"] = values

    def bind(value: object) -> object:
        if isinstance(value, str):
            return re.sub(
                r"\$\{([a-z][a-z0-9_]*)\}",
                lambda match: values.get(match.group(1), match.group(0)),
                value,
            )
        if isinstance(value, list):
            return [bind(item) for item in value]
        if isinstance(value, dict):
            return {key: bind(item) for key, item in value.items()}
        return value

    for node in blueprint["nodes"]:
        node["config"] = bind(node["config"])
    return blueprint
