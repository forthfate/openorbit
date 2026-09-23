"""Initial canvas layout shared by Visual Mode's shipped blueprints.

The read-only workflow preview places lifecycle phases in columns and stacks
steps in each phase.  Persist the same starting positions in blueprints, while
leaving later user-driven node movement entirely untouched.
"""

from __future__ import annotations

from collections.abc import Iterable

LIFECYCLE_PHASES = (
    "before_all",
    "before_each",
    "execute",
    "verify",
    "after_supervision",
    "after_each",
    "after_all",
)

# These match the preview's 340px phase columns and its 48px vertical gap.
# Visual Mode nodes are 140px tall for initial-layout purposes.
_COLUMN_WIDTH = 340
_LEFT_INSET = 30
_TOP_INSET = 72
_NODE_HEIGHT = 140
_ROW_GAP = 48


def initial_positions(phases: Iterable[str]) -> list[dict[str, int]]:
    """Return preview-style initial positions in the supplied node order."""
    values = list(phases)
    present = list(dict.fromkeys(values))
    ordered = [
        *[phase for phase in LIFECYCLE_PHASES if phase in present],
        *[phase for phase in present if phase not in LIFECYCLE_PHASES],
    ]
    columns = {phase: index for index, phase in enumerate(ordered)}
    rows = {phase: 0 for phase in ordered}
    positions: list[dict[str, int]] = []
    for phase in values:
        row = rows[phase]
        positions.append(
            {
                "x": _LEFT_INSET + columns[phase] * _COLUMN_WIDTH,
                "y": _TOP_INSET + row * (_NODE_HEIGHT + _ROW_GAP),
            }
        )
        rows[phase] += 1
    return positions
