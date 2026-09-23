"""Schema validation and deterministic Python generation for visual runners."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from orbit_sdk.visual import visual_nodes
from orbit_sdk.visual.bindings import validate as validate_bindings
from orbit_sdk.visual.bindings import validate_condition

PHASES = ("before_all", "before_each", "execute", "verify", "after_each", "after_all")
NODE_KINDS = {item["kind"] for item in visual_nodes.catalog()}
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PYTHON_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PHASE_INDEX = {phase: index for index, phase in enumerate(PHASES)}


def validate_blueprint(value: dict[str, Any]) -> dict[str, Any]:
    """Validate a visual runner blueprint and return its normalized value."""
    if value.get("schema_version") != 1:
        raise ValueError("visual runner blueprint requires schema_version 1")
    nodes = value.get("nodes")
    edges = value.get("edges", [])
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("visual runner blueprint requires at least one node")
    if not isinstance(edges, list):
        raise ValueError("visual runner blueprint edges must be an array")
    parameters = value.get("parameters", {})
    if not isinstance(parameters, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in parameters.items()
    ):
        raise ValueError("visual runner blueprint parameters must be a string object")
    ids: set[str] = set()
    normalized_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("visual runner nodes must be objects")
        node_id = str(node.get("id", ""))
        if not _IDENTIFIER.fullmatch(node_id) or node_id in ids:
            raise ValueError("visual runner node IDs must be unique lowercase identifiers")
        ids.add(node_id)
        kind, phase = str(node.get("kind", "")), str(node.get("phase", ""))
        if kind not in NODE_KINDS or phase not in PHASES:
            raise ValueError(f"visual runner node {node_id!r} has an unsupported kind or phase")
        inputs = _ports(node.get("inputs", []), node_id, "input")
        outputs = _ports(node.get("outputs", []), node_id, "output")
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        try:
            validate_bindings(config)
            validate_condition(node.get("when"))
        except ValueError as error:
            raise ValueError(
                f"visual runner node {node_id!r} has invalid runtime binding: {error}"
            ) from error
        if kind != "custom_script":
            try:
                visual_nodes.validate(kind, config)
            except ValueError as error:
                raise ValueError(f"visual runner node {node_id!r} {error}") from error
        position = node.get("position") if isinstance(node.get("position"), dict) else {}
        normalized_nodes.append(
            {
                "id": node_id,
                "kind": kind,
                "title": str(node.get("title") or node_id.replace("_", " ").title()),
                "description": str(node.get("description") or "") or None,
                "phase": phase,
                "inputs": inputs,
                "outputs": outputs,
                "config": config,
                "when": node.get("when"),
                "script": str(node.get("script") or ""),
                "position": {"x": _number(position.get("x", 0)), "y": _number(position.get("y", 0))},
            }
        )
    nodes_by_id = {node["id"]: node for node in normalized_nodes}
    normalized_edges: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("source") not in ids or edge.get("target") not in ids:
            raise ValueError("visual runner edges must connect existing nodes")
        source, target = str(edge["source"]), str(edge["target"])
        kind = str(edge.get("kind", "data"))
        if kind not in {"execution", "data", "condition", "loop"}:
            raise ValueError("visual runner edge kind is invalid")
        source_port = str(edge.get("source_port") or "") or None
        target_port = str(edge.get("target_port") or "") or None
        if kind == "data":
            if bool(source_port) != bool(target_port):
                raise ValueError("visual runner data edges must declare both ports or neither")
            if source_port and (
                source_port not in nodes_by_id[source]["outputs"]
                or target_port not in nodes_by_id[target]["inputs"]
            ):
                raise ValueError("visual runner data edges must connect declared output and input ports")
        elif source_port or target_port:
            raise ValueError("only visual runner data edges may use ports")
        if kind == "loop":
            if nodes_by_id[source]["phase"] != "after_each" or nodes_by_id[target]["phase"] not in {
                "before_each",
                "execute",
            }:
                raise ValueError("visual runner loops must connect after_each to before_each or execute")
        elif _PHASE_INDEX[nodes_by_id[source]["phase"]] > _PHASE_INDEX[nodes_by_id[target]["phase"]]:
            raise ValueError("visual runner edges must follow lifecycle order")
        normalized_edges.append(
            {
                "source": source,
                "target": target,
                "kind": kind,
                "source_port": source_port,
                "target_port": target_port,
                "label": str(edge.get("label") or "") or None,
            }
        )
    _ensure_acyclic(nodes_by_id, normalized_edges)
    return {
        "schema_version": 1,
        "parameters": dict(parameters),
        "nodes": normalized_nodes,
        "edges": normalized_edges,
    }


def _ports(value: object, node_id: str, label: str) -> list[str]:
    if not isinstance(value, list) or not all(_IDENTIFIER.fullmatch(str(port)) for port in value):
        raise ValueError(f"visual runner node {node_id!r} has invalid {label} ports")
    ports = [str(port) for port in value]
    if len(set(ports)) != len(ports):
        raise ValueError(f"visual runner node {node_id!r} has duplicate {label} ports")
    return ports


def _number(value: object) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0
    return value


def _ensure_acyclic(nodes: dict[str, dict[str, Any]], edges: Iterable[dict[str, Any]]) -> None:
    """Reject cycles other than the explicit iteration loop edge."""
    adjacent = {node_id: [] for node_id in nodes}
    for edge in edges:
        if edge["kind"] != "loop":
            adjacent[edge["source"]].append(edge["target"])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("visual runner edges must not contain a cycle")
        if node_id not in visited:
            visiting.add(node_id)
            for target in adjacent[node_id]:
                visit(target)
            visiting.remove(node_id)
            visited.add(node_id)

    for node_id in nodes:
        visit(node_id)


def generate_source(blueprint: dict[str, Any]) -> str:
    """Generate one explicit, executable runner source file from a blueprint."""
    blueprint = validate_blueprint(blueprint)
    bindings_by_target: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    for edge in blueprint["edges"]:
        if edge["kind"] == "data" and edge["source_port"] and edge["target_port"]:
            bindings_by_target[edge["target"]][edge["target_port"]] = (
                edge["source"],
                edge["source_port"],
            )
    by_phase: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in blueprint["nodes"]:
        by_phase[node["phase"]].append({**node, "_bindings": bindings_by_target[node["id"]]})
    lines = [
        '"""Generated by OpenOrbit Visual Runner Editor. Do not edit by hand."""',
        "",
        "from orbit_sdk import graph, runner",
        "",
    ]
    for edge in blueprint["edges"]:
        arguments = [repr(edge["source"]), repr(edge["target"])]
        if edge["kind"] != "execution":
            arguments.append(f"kind={edge['kind']!r}")
        if edge["label"]:
            arguments.append(f"label={edge['label']!r}")
        if edge["source_port"]:
            arguments.append(f"source_port={edge['source_port']!r}")
        if edge["target_port"]:
            arguments.append(f"target_port={edge['target_port']!r}")
        lines.append(f"graph.connect({', '.join(arguments)})")
    lines.append("")
    for phase in PHASES:
        ordered_nodes = _ordered_nodes(by_phase[phase], blueprint["edges"])
        for node in ordered_nodes:
            lines.extend(_node_source(node))
        if by_phase[phase]:
            lines.append(f"@runner.phase({phase!r})")
            lines.append(f"def phase_{phase}(ctx):")
            lines.extend(f"    {_function_name(node['id'])}(ctx)" for node in ordered_nodes)
            lines.append("")
    lines.extend(["if __name__ == '__main__':", "    runner.main()", ""])
    return "\n".join(lines)


def _node_source(node: dict[str, Any]) -> list[str]:
    # Generated runners are Python source, not JSON. ``json.dumps`` emits
    # JSON literals such as ``true`` and ``null``, which are invalid Python.
    config = repr(node["config"])
    outputs = repr(node["outputs"])
    lines = [
        f"@graph.step({node['id']!r}, title={node['title']!r}, phase={node['phase']!r}, inputs={node['inputs']!r}, outputs={outputs}, description={node['description']!r})",
        f"@runner.phase({node['phase']!r}, step_id={node['id']!r})",
        f"def {_function_name(node['id'])}(ctx):",
        f"    config = {config}",
        f"    outputs = ctx.visual_node_inputs({node['id']!r}, {_bindings(node)!r})",
    ]
    if node["when"] is not None:
        lines.append(f"    if not ctx.visual_should_run({node['when']!r}, inputs=outputs):")
        lines.append("        return")
    if node["kind"] == "custom_script":
        script = node["script"] or "# Set values on outputs, then return.\npass"
        lines.extend(f"    {line}" if line else "" for line in script.splitlines())
    else:
        lines.append(
            f"    outputs.update(ctx.run_visual_node({node['kind']!r}, node_id={node['id']!r}, config=config, inputs=outputs))"
        )
    lines.extend([f"    ctx.publish_visual_node_outputs({node['id']!r}, outputs)", ""])
    return lines


def _bindings(node: dict[str, Any]) -> dict[str, tuple[str, str]]:
    # Set by generate_source immediately before each node is rendered.
    return node.get("_bindings", {})


def _function_name(node_id: str) -> str:
    """Return a deterministic, safe Python function name for a graph node ID."""
    if _PYTHON_IDENTIFIER.fullmatch(node_id):
        return node_id
    return "node_" + re.sub(r"[^a-z0-9_]", "_", node_id)


def _ordered_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order same-phase nodes by graph dependencies while retaining canvas order."""
    node_ids = {node["id"] for node in nodes}
    predecessors = {node_id: set() for node_id in node_ids}
    for edge in edges:
        if edge["kind"] != "loop" and edge["source"] in node_ids and edge["target"] in node_ids:
            predecessors[edge["target"]].add(edge["source"])
    ordered: list[dict[str, Any]] = []
    remaining = list(nodes)
    while remaining:
        ready = next((node for node in remaining if not predecessors[node["id"]]), None)
        if ready is None:  # validate_blueprint has already provided the user-facing error.
            return nodes
        remaining.remove(ready)
        ordered.append(ready)
        for values in predecessors.values():
            values.discard(ready["id"])
    return ordered
