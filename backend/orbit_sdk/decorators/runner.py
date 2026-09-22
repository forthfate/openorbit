"""Lifecycle decorator registration and runner CLI dispatch."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.lifecycle import canonical_phase
from .graph import Graph, graph

if TYPE_CHECKING:
    from ..core.context import RunnerContext


class Runner:
    """Register lifecycle handlers without owning runtime context operations."""

    def __init__(self, graph_definition: Graph | None = None) -> None:
        """Create a runner registry, using the public graph singleton by default."""
        self._graph = graph_definition or graph
        self._handlers: dict[str, Callable[[RunnerContext], None]] = {}

    def phase(self, name: str, *, step_id: str | None = None):
        """Register one handler for an Orbit lifecycle phase."""

        def register(handler: Callable[[RunnerContext], None]) -> Callable[[RunnerContext], None]:
            phase = canonical_phase(name)
            key = f"{phase}:{step_id}" if step_id else phase
            self._handlers[key] = handler
            setattr(handler, "__orbit_phase__", phase)
            return handler

        return register

    def main(self) -> None:
        """Dispatch the lifecycle phase requested by the Orbit process."""
        parser = argparse.ArgumentParser(description="Orbit runner phase")
        command = parser.add_mutually_exclusive_group(required=True)
        command.add_argument("--phase")
        parser.add_argument("--step")
        command.add_argument("--graph", action="store_true")
        args = parser.parse_args()
        if args.graph:
            print(json.dumps(self._graph.definition(), ensure_ascii=False))
            return
        phase = canonical_phase(args.phase)
        handler = self._handlers.get(f"{phase}:{args.step}") if args.step else None
        handler = handler or self._handlers.get(phase)
        if handler is None:
            raise SystemExit(f"runner does not define phase: {args.phase}")
        from ..core.context import RunnerContext

        context = RunnerContext(
            phase,
            Path(os.environ["ORBIT_TARGET_REPOSITORY"]),
            os.environ.get("ORBIT_EXECUTION_MODE", "run"),
            int(os.environ.get("ORBIT_LOOP_INDEX", "1")),
        )
        handler = getattr(handler, "__orbit_graph_wrapper__", handler)
        before = context.git_head()
        try:
            handler(context)
        finally:
            try:
                context.record_commit_change(before)
            except (OSError, subprocess.CalledProcessError) as error:
                context.log(f"Could not retain commit-change evidence: {error}")


runner = Runner(graph)
