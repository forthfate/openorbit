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
import threading
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from ..decorators.visual import visual_node
from .registry import VisualNodeDefinition, visual_nodes

_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE_ROOT = _ROOT / "templates"
_CANONICAL_ROOT = Path(__file__).resolve().parent / "canonical"
_MODULE_LOCK = threading.RLock()


class _TemplateGraph:
    """No-op decorator facade used while loading canonical template functions."""

    def connect(self, *_: object, **__: object) -> None:
        return None

    def step(self, *_: object, **__: object):
        return lambda handler: handler


class _TemplateRunner:
    """No-op lifecycle facade; the visual runner owns dispatch and tracing."""

    def phase(self, *_: object, **__: object):
        return lambda handler: handler


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
    adapter-backed steps are a migration boundary; a definition can replace
    them with direct SDK operations without changing callers.
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


def _step_kind(template_id: str, step_id: str) -> str:
    """Return a stable SDK node kind for one canonical template step."""
    return "template_" + re.sub(r"[^a-z0-9]+", "_", f"{template_id}_{step_id}".lower()).strip("_")


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


@lru_cache(maxsize=None)
def _module(template_id: str, parameter_key: str = "") -> dict[str, object]:
    try:
        template = templates()[template_id]
    except KeyError as error:
        raise ValueError(f"unsupported built-in visual template: {template_id}") from error
    # Load the trusted function bodies without registering their graph a second
    # time.  The generated visual runner is the sole lifecycle/trace owner.
    import orbit_sdk

    with _MODULE_LOCK:
        graph, runner = orbit_sdk.graph, orbit_sdk.runner
        orbit_sdk.graph, orbit_sdk.runner = _TemplateGraph(), _TemplateRunner()
        try:
            source = template.source.read_text(encoding="utf-8")
            if parameter_key:
                parameters = json.loads(parameter_key)
                source = re.sub(
                    r"\$\{([a-z][a-z0-9_]*)\}",
                    lambda match: parameters.get(match.group(1), match.group(0)),
                    source,
                )
            module = {
                "__name__": f"orbit_builtin_{template_id.replace(':', '_').replace('-', '_')}",
                "__file__": str(template.source),
            }
            exec(compile(source, str(template.source), "exec"), module)
            return module
        finally:
            orbit_sdk.graph, orbit_sdk.runner = graph, runner


def _execute_template_step(
    ctx: Any, *, template_id: str, step_id: str, config: Mapping[str, Any]
) -> dict[str, object]:
    """Execute one canonical function; shared by generated per-step handlers."""
    template = templates().get(template_id)
    if template is None or step_id not in {step.id for step in template.steps}:
        raise ValueError("built-in template step is not declared by the SDK catalog")
    parameters = config.get("parameters", {})
    if not isinstance(parameters, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in parameters.items()
    ):
        raise ValueError("built-in template parameters must be a string object")
    parameter_key = json.dumps(dict(parameters), sort_keys=True, separators=(",", ":"))
    module = _module(template_id, parameter_key)
    function = module.get(next(step.function_name for step in template.steps if step.id == step_id))
    if not callable(function):
        raise RuntimeError(f"built-in template step is not callable: {template_id}/{step_id}")
    function(ctx)
    return {"completed": True}


@visual_node(
    kind="builtin_template_step",
    group_key="templates",
    display_name="Built-in template step",
    title_key="visual.nodes.builtinTemplateStep.title",
    description_key="visual.nodes.builtinTemplateStep.description",
    default_config={
        "template_id": "runner-templates:json-agent-cycle",
        "step_id": "validate-agent-cycle-contract",
    },
    required_config=("template_id", "step_id"),
    default_outputs=("completed",),
)
def builtin_template_step(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Compatibility facade for legacy visual blueprints using the generic node."""
    return _execute_template_step(
        ctx, template_id=config["template_id"], step_id=config["step_id"], config=config
    )


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


@lru_cache(maxsize=1)
def definitions() -> dict[str, TemplateDefinition]:
    """Build stable TemplateDefinitions from every built-in runner graph."""
    result: dict[str, TemplateDefinition] = {}
    for template in templates().values():
        # The graph and lifecycle IDs are part of a runner's observable
        # contract. Preserve them verbatim so generated executions retain the
        # same step evidence as the canonical source.
        ids = {step.id: step.id for step in template.steps}
        nodes = [
            {
                "id": ids[step.id],
                "kind": _step_kind(template.id, step.id),
                "title": step.title,
                "phase": step.phase,
                "inputs": list(step.inputs),
                "outputs": list(step.outputs),
                "description": step.description,
                "config": {},
                "script": "",
                "position": {"x": 100 + index * 280, "y": 130 + (index % 2) * 180},
            }
            for index, step in enumerate(template.steps)
        ]
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
    for node in blueprint["nodes"]:
        node["config"] = {**node["config"], "parameters": values}
    return blueprint


def register_template_step_nodes() -> None:
    """Register one explicit SDK visual node for every shipped template step."""
    registered = {item["kind"] for item in visual_nodes.catalog()}
    for template in templates().values():
        for step in template.steps:
            kind = _step_kind(template.id, step.id)
            if kind in registered:
                continue

            def handler(
                ctx: Any,
                config: Mapping[str, Any],
                _: Mapping[str, object],
                *,
                template_id: str = template.id,
                step_id: str = step.id,
            ) -> dict[str, object]:
                return _execute_template_step(ctx, template_id=template_id, step_id=step_id, config=config)

            visual_nodes.register(
                VisualNodeDefinition(
                    kind=kind,
                    group_key="templates",
                    display_name=step.title,
                    title_key=f"visual.templates.{template.id.replace(':', '.').replace('-', '_')}.steps.{step.id.replace('-', '_')}.title",
                    description_key=f"visual.templates.{template.id.replace(':', '.').replace('-', '_')}.steps.{step.id.replace('-', '_')}.description",
                    default_config={"parameters": {}},
                    default_inputs=step.inputs,
                    default_outputs=step.outputs,
                    handler=handler,
                )
            )
            registered.add(kind)
