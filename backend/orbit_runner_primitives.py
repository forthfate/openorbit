"""Low-level, composable building blocks for OpenOrbit runner recipes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunnerRequirements:
    """Reusable preflight checks for runner recipes or custom runners."""

    build_fields: tuple[str, ...] = ()
    require_test_cases: bool = False

    def validate_build_fields(self, ctx: Any) -> None:
        missing = [field for field in self.build_fields if not ctx.build.get(field)]
        if missing:
            raise ValueError(f"Set required build field(s): {', '.join(missing)}")

    def validate_test_cases(self, ctx: Any) -> None:
        if self.require_test_cases and not ctx.test_cases:
            raise ValueError("Select at least one fixed test case before running this runner")

    def validate(self, ctx: Any) -> None:
        self.validate_build_fields(ctx)
        self.validate_test_cases(ctx)


def focused_cases(ctx: Any, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Retry failed cases before rotating through the declared fixed cases."""
    cases = list(ctx.test_cases)
    failed = {str(case_id) for case_id in state.get("failed_case_ids", [])}
    retry = [case for case in cases if str(case.get("id")) in failed]
    if retry:
        return retry
    return [cases[int(state.get("next_case_index", 0)) % len(cases)]]
