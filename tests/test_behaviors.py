import pytest

from orbit import ImprovementPolicy, SourceCatalogPolicy, load_bundle, render_prompt


def test_bundles_declare_public_operating_contracts():
    simulation = load_bundle("user-simulation")
    improvement = load_bundle("paired-improvement")
    assert simulation.definition["graph"][-1] == "normalize_evidence"
    assert improvement.definition["gate"]["replay_probes"] == 5
    assert improvement.definition["gate"]["development_probes"] == 2


def test_prompt_rendering_is_strict():
    bundle = load_bundle("user-simulation")
    prompt = render_prompt(bundle, "session_planner", persona="A", memory="B", catalog="C")
    assert "{{" not in prompt
    with pytest.raises(ValueError, match="variables mismatch"):
        render_prompt(bundle, "session_planner", persona="A")


def test_source_catalog_rejects_invented_browser_target():
    assert SourceCatalogPolicy.validate_actions([{"target": "route:/"}], {"route:/"})
    with pytest.raises(ValueError, match="source-backed"):
        SourceCatalogPolicy.validate_actions([{"target": "route:/invented"}], {"route:/"})


def test_improvement_policy_promotes_only_after_three_complete_gates():
    scores = [4] * 7
    assert ImprovementPolicy.assess(scores, 1, True).action == "continue"
    assert ImprovementPolicy.assess(scores, 2, True).action == "promote"
    assert ImprovementPolicy.assess(scores, 2, False).action == "blocked"
    assert ImprovementPolicy.assess([4] * 6, 2, True).action == "blocked"
