"""Load versioned behavior definitions and public prompt templates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import yaml

_TOKEN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


@dataclass(frozen=True)
class BehaviorBundle:
    """One self-contained, inspectable behavior contract."""

    name: str
    definition: dict[str, Any]

    @property
    def prompts(self) -> dict[str, str]:
        return dict(self.definition.get("prompts", {}))


def load_bundle(name: str) -> BehaviorBundle:
    """Load a bundled YAML behavior definition by stable name."""
    resource = files("orbit.resources.definitions").joinpath(f"{name}.yaml")
    if not resource.is_file():
        raise ValueError(f"Unknown behavior bundle: {name}")
    definition = yaml.safe_load(resource.read_text(encoding="utf-8"))
    if not isinstance(definition, dict) or definition.get("id") != name:
        raise ValueError(f"Invalid behavior definition: {name}")
    return BehaviorBundle(name=name, definition=definition)


def render_prompt(bundle: BehaviorBundle, prompt_id: str, **values: str) -> str:
    """Render a public prompt template and reject undeclared placeholders."""
    relative_path = bundle.prompts.get(prompt_id)
    if not relative_path:
        raise ValueError(f"Bundle {bundle.name} has no prompt named {prompt_id}")
    template = files("orbit.resources.prompts").joinpath(relative_path).read_text(encoding="utf-8")
    required = set(_TOKEN.findall(template))
    missing = required - values.keys()
    extra = values.keys() - required
    if missing or extra:
        raise ValueError(f"Prompt variables mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    return _TOKEN.sub(lambda match: values[match.group(1)], template)
