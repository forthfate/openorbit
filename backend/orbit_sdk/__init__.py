"""Public, dependency-free API for OpenOrbit runner assets.

The package keeps the historical ``from orbit_sdk import graph, runner`` API
stable while separating runtime primitives, declarative decorators, reusable
helpers, and visual-node definitions into dedicated modules.
"""

import sys
from types import ModuleType

from .core import context as _context
from .core.context import (
    ORBIT_APP_DATA,
    RunnerContext,
)
from .core.lifecycle import PHASE_ALIASES, canonical_phase
from .decorators import Graph, GraphEdge, GraphNode, Runner, graph, runner


class _OrbitSdkModule(ModuleType):
    """Keep mutable legacy module settings synchronized with ``core``.

    Existing runner tests and integrations sometimes set ``ORBIT_APP_DATA`` on
    the public module. The runtime now lives in ``core.context``, so forward
    that small compatibility surface rather than leaking the old layout.
    """

    def __getattr__(self, name: str):
        return getattr(_context, name)

    def __setattr__(self, name: str, value: object) -> None:
        if name == "ORBIT_APP_DATA":
            setattr(_context, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _OrbitSdkModule

__all__ = [
    "ORBIT_APP_DATA",
    "PHASE_ALIASES",
    "Graph",
    "GraphEdge",
    "GraphNode",
    "Runner",
    "RunnerContext",
    "canonical_phase",
    "graph",
    "runner",
]
