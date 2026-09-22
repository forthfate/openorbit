"""Visual runner node declarations and runtime integration."""

from . import browser as _browser  # noqa: F401 - registers browser template nodes
from . import builtin_templates as _builtin_templates  # noqa: F401 - registers compatibility template step
from . import builtins as _builtins  # noqa: F401 - registers curated SDK nodes
from . import journeys as _journeys  # noqa: F401 - registers journey template nodes
from .builtin_templates import (
    TemplateDefinition,
    definition_for_quick_start,
    definition_for_runner_template,
    instantiate_definition,
    register_template_step_nodes,
)
from .builtin_templates import (
    catalog as builtin_template_catalog,
)
from .registry import VisualNodeDefinition, VisualNodeRegistry, visual_node, visual_nodes
from .starters import catalog as starter_catalog

# Register the stable, SDK-owned node kind for every canonical built-in step
# before consumers cache the visual-node catalog.
register_template_step_nodes()

__all__ = [
    "TemplateDefinition",
    "VisualNodeDefinition",
    "VisualNodeRegistry",
    "builtin_template_catalog",
    "definition_for_quick_start",
    "definition_for_runner_template",
    "instantiate_definition",
    "register_template_step_nodes",
    "starter_catalog",
    "visual_node",
    "visual_nodes",
]
