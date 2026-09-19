import pytest

from orbit import ImprovementPolicy, SourceCatalogPolicy, load_bundle, render_prompt


def test_load_bundle_unknown_raises_value_error():
    """Verify that attempting to load a non-existent behavior bundle raises ValueError."""
    with pytest.raises(ValueError, match="Unknown behavior bundle"):
        load_bundle("non-existent-bundle-name")


def test_render_prompt_unknown_prompt_id_raises_value_error():
    """Verify that referencing an undefined prompt name in a bundle raises ValueError."""
    bundle = load_bundle("user-simulation")
    with pytest.raises(ValueError, match="has no prompt named"):
        render_prompt(bundle, "unknown_prompt_key", persona="A")


def test_render_prompt_extra_variables_raises_value_error():
    """Verify that providing unexpected extra variables during prompt rendering raises ValueError."""
    bundle = load_bundle("user-simulation")
    with pytest.raises(ValueError, match="variables mismatch"):
        render_prompt(bundle, "session_planner", persona="A", memory="B", catalog="C", unexpected_arg="D")


def test_source_catalog_rejects_empty_or_unmatched_targets():
    """Verify that actions with empty or non-catalog targets are properly rejected."""
    catalog = {"route:/dashboard", "route:/settings"}
    actions = [{"target": "route:/dashboard"}, {"target": "route:/unauthorized"}]
    with pytest.raises(ValueError, match="Actions are not source-backed: route:/unauthorized"):
        SourceCatalogPolicy.validate_actions(actions, catalog)


def test_improvement_policy_reverts_on_insufficient_scores_after_gate_limit():
    """Verify that failing scores trigger a revert decision once required evaluations count is met."""
    # When stable_runs + 1 >= REQUIRED_EVALUATIONS (3) and scores are below minimum
    insufficient_scores = [3, 4, 4, 4, 4, 4, 4]  # one score < 4
    decision = ImprovementPolicy.assess(insufficient_scores, 2, True)
    assert decision.action == "revert"
    assert decision.stable_runs == 3
    assert "Three non-sufficient gates exhausted the candidate" in decision.reason


def test_improvement_policy_continues_when_insufficient_before_limit():
    """Verify that candidate continues in isolation when evaluations remain below gate limit."""
    insufficient_scores = [3, 4, 4, 4, 4, 4, 4]
    decision = ImprovementPolicy.assess(insufficient_scores, 0, True)
    assert decision.action == "continue"
    assert decision.stable_runs == 1
    assert "Candidate remains isolated for another gate" in decision.reason
