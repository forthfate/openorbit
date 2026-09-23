"""Safe runtime value bindings and predicates for visual runner nodes.

Blueprints are data, never Python expressions.  This module resolves a small
allowlist of runner-context values and declared input ports so generated code
can remain deterministic and safe to inspect.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

_CONTEXT_VALUES = {
    "phase",
    "loop_index",
    "build",
    "test_cases",
    "previous_supervisor_feedback",
    "current_issue_assessment",
    "environment",
}
_BINDING_KEYS = {"$ctx", "$input", "$resource", "$state"}


def is_binding(value: object) -> bool:
    """Return whether a value is one supported dynamic binding object."""
    return isinstance(value, Mapping) and len(value) == 1 and next(iter(value), "") in _BINDING_KEYS


def validate(value: object) -> None:
    """Reject unsupported dynamic binding syntax while allowing ordinary JSON."""
    if not isinstance(value, Mapping):
        if isinstance(value, list):
            for item in value:
                validate(item)
        return
    keys = set(value)
    reserved = keys & _BINDING_KEYS
    if reserved:
        if len(keys) != 1:
            raise ValueError("a visual runtime binding must contain exactly one $ key")
        key = next(iter(reserved))
        binding = value[key]
        if key in {"$ctx", "$input", "$resource"} and not isinstance(binding, str):
            raise ValueError(f"{key} binding must be a string")
        if key == "$state" and (not isinstance(binding, Mapping) or not isinstance(binding.get("name"), str)):
            raise ValueError("$state binding requires a state name")
        return
    for item in value.values():
        validate(item)


def resolve(ctx: Any, value: object, inputs: Mapping[str, object]) -> object:
    """Resolve bindings recursively against explicitly allowed runtime values."""
    if not is_binding(value):
        if isinstance(value, Mapping):
            return {str(key): resolve(ctx, item, inputs) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(ctx, item, inputs) for item in value]
        return deepcopy(value)
    key, binding = next(iter(value.items()))  # type: ignore[union-attr]
    if key == "$ctx":
        return deepcopy(_path(_context_value(ctx, binding), ""))
    if key == "$input":
        name, _, path = binding.partition(".")
        if name not in inputs:
            return None
        return deepcopy(_path(inputs[name], path))
    if key == "$resource":
        name, _, path = binding.partition(".")
        return deepcopy(_path(ctx.resource(name, {}), path))
    # $state is deliberately explicit about scope and never exposes a filesystem path.
    state = ctx.load_state(binding["name"], binding.get("default"), scope=binding.get("scope", "runner"))
    return deepcopy(_path(state, str(binding.get("path", ""))))


def evaluate(ctx: Any, condition: object, inputs: Mapping[str, object]) -> bool:
    """Evaluate a compact JSON predicate used by a node's ``when`` property."""
    if condition is None:
        return True
    if isinstance(condition, Mapping) and len(condition) == 1:
        operator, operand = next(iter(condition.items()))
        if operator == "$not":
            return not evaluate(ctx, operand, inputs)
        if operator in {"$all", "$any"}:
            if not isinstance(operand, list):
                raise ValueError(f"{operator} requires an array")
            results = [evaluate(ctx, item, inputs) for item in operand]
            return all(results) if operator == "$all" else any(results)
        if operator in {"$equals", "$not_equals"}:
            if not isinstance(operand, list) or len(operand) != 2:
                raise ValueError(f"{operator} requires exactly two values")
            equal = resolve(ctx, operand[0], inputs) == resolve(ctx, operand[1], inputs)
            return equal if operator == "$equals" else not equal
        if operator == "$exists":
            return resolve(ctx, operand, inputs) is not None
    return bool(resolve(ctx, condition, inputs))


def validate_condition(condition: object) -> None:
    """Validate predicate syntax without evaluating runner data at save time."""
    if condition is None or isinstance(condition, bool):
        return
    if isinstance(condition, Mapping) and len(condition) == 1:
        operator, operand = next(iter(condition.items()))
        if operator == "$not":
            return validate_condition(operand)
        if operator in {"$all", "$any"}:
            if not isinstance(operand, list):
                raise ValueError(f"{operator} requires an array")
            for item in operand:
                validate_condition(item)
            return
        if operator in {"$equals", "$not_equals"}:
            if not isinstance(operand, list) or len(operand) != 2:
                raise ValueError(f"{operator} requires exactly two values")
            validate(operand[0])
            validate(operand[1])
            return
        if operator == "$exists":
            return validate(operand)
    validate(condition)


def _context_value(ctx: Any, binding: str) -> object:
    name, _, path = binding.partition(".")
    if name not in _CONTEXT_VALUES:
        raise ValueError(f"unsupported $ctx binding: {name}")
    return _path(getattr(ctx, name), path)


def _path(value: object, path: str) -> object:
    """Read a dot-separated dict/list path without attribute access or calls."""
    if not path:
        return value
    current = value
    for part in path.split("."):
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return None
    return current
