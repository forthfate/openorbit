"""Declarative registry for SDK-backed visual runner nodes.

This module deliberately has no FastAPI or frontend dependency. The API server
serializes its catalog, the runner compiler validates against it, and the SDK
runtime dispatches through it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from . import bindings

VisualNodeHandler = Callable[[Any, Mapping[str, Any], Mapping[str, object]], dict[str, object]]
VisualNodeValidator = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True)
class VisualNodeDefinition:
    """One SDK-owned operation that may be placed in a visual runner."""

    kind: str
    group_key: str
    title_key: str
    description_key: str
    display_name: str
    default_inputs: tuple[str, ...] = ()
    default_outputs: tuple[str, ...] = ()
    required_config: tuple[str, ...] = ()
    config_schema: dict[str, object] | None = None
    default_config: dict[str, object] | None = None
    handler: VisualNodeHandler | None = None
    is_custom_script: bool = False
    palette_visible: bool = True
    config_validator: VisualNodeValidator | None = None

    def validate_config(self, config: Mapping[str, Any]) -> None:
        """Validate the minimum portable configuration for this operation."""
        for name in self.required_config:
            value = config.get(name)
            if bindings.is_binding(value):
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"requires {name}")
        bindings.validate(config)
        if self.config_validator:
            self.config_validator(config)

    def catalog(self) -> dict[str, object]:
        """Return frontend-safe metadata without exposing executable code."""
        return {
            "kind": self.kind,
            "group_key": self.group_key,
            "title_key": self.title_key,
            "description_key": self.description_key,
            "display_name": self.display_name,
            "default_inputs": list(self.default_inputs),
            "default_outputs": list(self.default_outputs),
            "config_schema": self.config_schema or {"type": "object"},
            "default_config": self.default_config or {},
            "is_custom_script": self.is_custom_script,
            "palette_visible": self.palette_visible,
        }


class VisualNodeRegistry:
    """Register and dispatch SDK-owned visual node definitions."""

    def __init__(self) -> None:
        self._definitions: dict[str, VisualNodeDefinition] = {}

    def node(self, **metadata: Any) -> Callable[[VisualNodeHandler], VisualNodeHandler]:
        """Register an executable visual node through a decorator."""

        def register(handler: VisualNodeHandler) -> VisualNodeHandler:
            definition = VisualNodeDefinition(handler=handler, **metadata)
            if definition.kind in self._definitions:
                raise ValueError(f"visual node kind must be unique: {definition.kind}")
            self._definitions[definition.kind] = definition
            return handler

        return register

    def register(self, definition: VisualNodeDefinition) -> None:
        """Register metadata-only nodes such as the Custom Script escape hatch."""
        if definition.kind in self._definitions:
            raise ValueError(f"visual node kind must be unique: {definition.kind}")
        self._definitions[definition.kind] = definition

    def get(self, kind: str) -> VisualNodeDefinition:
        """Return one registered definition or a clear validation error."""
        try:
            return self._definitions[kind]
        except KeyError as error:
            raise ValueError(f"unsupported visual node kind: {kind}") from error

    def validate(self, kind: str, config: Mapping[str, Any]) -> None:
        """Validate one node configuration."""
        self.get(kind).validate_config(config)

    def execute(
        self, kind: str, ctx: Any, *, config: Mapping[str, Any], inputs: Mapping[str, object]
    ) -> dict[str, object]:
        """Run one registered node and require its JSON-object output."""
        definition = self.get(kind)
        definition.validate_config(config)
        handler = definition.handler
        if handler is None:
            raise ValueError(f"visual node kind {kind!r} has no SDK runtime handler")
        result = handler(ctx, config, inputs)
        if not isinstance(result, dict):
            raise RuntimeError(f"visual node {kind!r} must return a JSON object")
        return result

    def catalog(self) -> list[dict[str, object]]:
        """Return definitions in stable registration order for clients."""
        return [definition.catalog() for definition in self._definitions.values()]


visual_nodes = VisualNodeRegistry()
visual_node = visual_nodes.node
