"""Canonical runner lifecycle names and legacy aliases."""

PHASE_ALIASES = {
    "init": "before_all",
    "setup": "before_each",
    "run": "execute",
    "eval": "verify",
    "post_supervision": "after_supervision",
    "teardown": "after_each",
    "finalize": "after_all",
}


def canonical_phase(name: str) -> str:
    """Return the canonical lifecycle key for a current or legacy phase."""
    return PHASE_ALIASES.get(name, name)
