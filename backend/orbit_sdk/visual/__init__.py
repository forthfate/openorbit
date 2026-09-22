"""Visual runner node declarations and runtime integration."""

from . import browser as _browser  # noqa: F401 - registers browser template nodes
from . import builtin_templates as _builtin_templates  # noqa: F401 - loads built-in blueprints
from . import builtins as _builtins  # noqa: F401 - registers curated SDK nodes
from . import improvement as _improvement  # noqa: F401 - registers improvement template nodes
from . import journeys as _journeys  # noqa: F401 - registers journey template nodes
from .builtin_templates import (
    TemplateDefinition,
    definition_for_quick_start,
    definition_for_runner_template,
    instantiate_definition,
)
from .builtin_templates import (
    catalog as builtin_template_catalog,
)
from .registry import VisualNodeDefinition, VisualNodeRegistry, visual_node, visual_nodes
from .starters import catalog as starter_catalog

__all__ = [
    "TemplateDefinition",
    "VisualNodeDefinition",
    "VisualNodeRegistry",
    "builtin_template_catalog",
    "definition_for_quick_start",
    "definition_for_runner_template",
    "instantiate_definition",
    "starter_catalog",
    "visual_node",
    "visual_nodes",
]
