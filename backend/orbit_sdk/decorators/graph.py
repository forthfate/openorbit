"""Declarative graph annotations for Orbit runner functions.

The graph layer intentionally owns no runner runtime state.  It only records
metadata and wraps a function when its first argument behaves like a runner
context (that is, it provides ``function(id)``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, Literal

from ..core.lifecycle import canonical_phase


@dataclass(frozen=True)
class GraphNode:
    """A declarative visual-workflow node attached to a runner function."""

    id: str
    title: str
    phase: str | None
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    description: str | None = None
    after_supervision: bool = False


@dataclass(frozen=True)
class GraphEdge:
    """A directed relationship between visual-workflow nodes."""

    source: str
    target: str
    kind: Literal["execution", "data", "condition", "loop", "error"] = "execution"
    label: str | None = None
    source_port: str | None = None
    target_port: str | None = None


class Graph:
    """Declare a runner's visual workflow without changing its execution."""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []

    def step(
        self,
        id: str | None = None,
        *,
        title: str | None = None,
        phase: str | None = None,
        inputs: tuple[str, ...] | list[str] = (),
        outputs: tuple[str, ...] | list[str] = (),
        description: str | None = None,
        after_supervision: bool = False,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Annotate one function as a visual workflow node."""

        def register(handler: Callable[..., Any]) -> Callable[..., Any]:
            node_id = id or handler.__name__
            if not node_id or node_id in self._nodes:
                raise ValueError(f"graph node ID must be unique: {node_id!r}")
            node = GraphNode(
                id=node_id,
                title=title or handler.__name__.replace("_", " ").title(),
                phase=canonical_phase(phase or getattr(handler, "__orbit_phase__", "")) or None,
                inputs=tuple(inputs),
                outputs=tuple(outputs),
                description=description,
                after_supervision=after_supervision,
            )
            self._nodes[node_id] = node
            setattr(handler, "__orbit_graph_node__", node)

            @wraps(handler)
            def instrumented(*args: Any, **kwargs: Any) -> Any:
                context = next(
                    (
                        value
                        for value in (*args, *kwargs.values())
                        if callable(getattr(value, "function", None))
                    ),
                    None,
                )
                if context is None:
                    return handler(*args, **kwargs)
                with context.function(node_id):
                    return handler(*args, **kwargs)

            setattr(instrumented, "__orbit_graph_node__", node)
            setattr(handler, "__orbit_graph_wrapper__", instrumented)
            return instrumented

        return register

    def connect(
        self,
        source: str,
        target: str,
        *,
        kind: Literal["execution", "data", "condition", "loop", "error"] = "execution",
        label: str | None = None,
        source_port: str | None = None,
        target_port: str | None = None,
    ) -> GraphEdge:
        """Declare a typed arrow; loops and conditions model control flow."""
        edge = GraphEdge(source, target, kind, label, source_port, target_port)
        self._edges.append(edge)
        return edge

    def definition(self) -> dict[str, object]:
        """Return JSON-safe graph data for a visual client or source inspector."""
        return {
            "nodes": [
                {
                    "id": node.id,
                    "title": node.title,
                    "phase": node.phase,
                    "inputs": list(node.inputs),
                    "outputs": list(node.outputs),
                    "description": node.description,
                    **({"after_supervision": True} if node.after_supervision else {}),
                }
                for node in self._nodes.values()
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "kind": edge.kind,
                    "label": edge.label,
                    "source_port": edge.source_port,
                    "target_port": edge.target_port,
                }
                for edge in self._edges
            ],
        }


graph = Graph()
