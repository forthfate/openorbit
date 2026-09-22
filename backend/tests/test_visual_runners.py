from __future__ import annotations

import pytest
from app.visual_runners import generate_source, validate_blueprint


def blueprint() -> dict:
    return {
        "schema_version": 1,
        "nodes": [
            {
                "id": "score_journey",
                "kind": "custom_script",
                "title": "Score journey",
                "phase": "verify",
                "outputs": ["score"],
                "config": {},
                "script": "outputs['score'] = 100",
                "position": {"x": 10, "y": 20},
            }
        ],
        "edges": [],
    }


def test_visual_runner_source_is_explicit_and_compilable():
    source = generate_source(blueprint())

    compile(source, "visual-runner.py", "exec")
    assert "@graph.step('score_journey'" in source
    assert "@runner.phase('verify')" in source
    assert "ctx.publish_visual_node_outputs('score_journey', outputs)" in source


def test_visual_runner_rejects_unknown_nodes_and_edges():
    invalid = blueprint()
    invalid["nodes"][0]["kind"] = "shell"
    with pytest.raises(ValueError, match="unsupported"):
        validate_blueprint(invalid)

    invalid = blueprint()
    invalid["edges"] = [{"source": "missing", "target": "score_journey"}]
    with pytest.raises(ValueError, match="existing"):
        validate_blueprint(invalid)


def test_visual_runner_data_edges_bind_declared_ports_only():
    value = blueprint()
    value["nodes"] = [
        {**value["nodes"][0], "id": "collect", "phase": "execute", "outputs": ["score"]},
        {**value["nodes"][0], "id": "report", "inputs": ["journey_score"], "outputs": []},
    ]
    value["edges"] = [
        {
            "source": "collect",
            "target": "report",
            "kind": "data",
            "source_port": "score",
            "target_port": "journey_score",
        }
    ]

    source = generate_source(value)

    assert "inputs=['journey_score']" in source
    assert "ctx.visual_node_inputs('report', {'journey_score': ('collect', 'score')})" in source


def test_visual_runner_rejects_invalid_data_ports_and_noncanonical_loops():
    invalid = blueprint()
    invalid["nodes"][0]["inputs"] = ["score"]
    invalid["edges"] = [
        {
            "source": "score_journey",
            "target": "score_journey",
            "kind": "data",
            "source_port": "missing",
            "target_port": "score",
        }
    ]
    with pytest.raises(ValueError, match="declared"):
        validate_blueprint(invalid)

    invalid = blueprint()
    invalid["edges"] = [{"source": "score_journey", "target": "score_journey", "kind": "loop"}]
    with pytest.raises(ValueError, match="after_each"):
        validate_blueprint(invalid)
