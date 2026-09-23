from __future__ import annotations

import ast

import pytest
from app.visual_runners import generate_source, validate_blueprint
from orbit_sdk.visual import builtin_template_catalog, starter_catalog, visual_nodes
from orbit_sdk.visual.bindings import evaluate, resolve
from orbit_sdk.visual.builtin_templates import definitions, instantiate_definition, templates
from orbit_sdk.visual.layout import initial_positions


def test_initial_visual_layout_matches_the_phase_columns_in_workflow_preview():
    assert initial_positions(["before_all", "execute", "execute", "after_all"]) == [
        {"x": 30, "y": 72},
        {"x": 370, "y": 72},
        {"x": 370, "y": 260},
        {"x": 710, "y": 72},
    ]


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
    assert "@runner.phase('verify', step_id='score_journey')" in source
    assert "ctx.publish_visual_node_outputs('score_journey', outputs)" in source


def test_visual_runner_source_uses_python_literals_for_node_config():
    value = blueprint()
    value["nodes"][0].update({"kind": "browser_journey", "config": {"fail_on_unpassed": True}})

    source = generate_source(value)

    compile(source, "visual-runner.py", "exec")
    assert "'fail_on_unpassed': True" in source


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


@pytest.mark.parametrize(
    ("kind", "config"),
    [
        ("command_action", {"command_env": "ORBIT_TOOL", "action": "check"}),
        ("browser_journey", {}),
        ("state_load", {"name": "journey"}),
        ("state_save", {"name": "journey"}),
        ("model_prompt", {"prompt": "Review this"}),
        ("model_json", {"prompt": "Return JSON"}),
        ("ai_agent", {"prompt": "Fix it", "provider": "codex"}),
        ("require_test_cases", {}),
        ("snapshot", {"operation": "save_before_each"}),
    ],
)
def test_visual_runner_generates_sdk_backed_node_kinds(kind, config):
    value = blueprint()
    value["nodes"][0].update({"kind": kind, "config": config})

    source = generate_source(value)

    compile(source, "visual-runner.py", "exec")
    assert f"ctx.run_visual_node({kind!r}" in source


def test_sdk_catalog_owns_node_metadata_and_starter_blueprints():
    nodes = {item["kind"]: item for item in visual_nodes.catalog()}
    assert nodes["browser_journey"]["title_key"] == "visual.nodes.browserJourney.title"
    assert nodes["custom_script"]["is_custom_script"] is True
    assert {starter["id"] for starter in starter_catalog()} >= {
        "json_agent_cycle",
        "command_adapter",
        "browser_journey",
        "user_journey_cycle",
    }
    for starter in starter_catalog():
        source = generate_source(starter["blueprint"])
        assert "@graph.step" in source
        assert "@runner.phase" in source

    json_source = generate_source(
        next(item for item in starter_catalog() if item["id"] == "json_agent_cycle")["blueprint"]
    )
    assert "step_id='preflight'" in json_source
    assert "ctx.run_visual_node('json_cycle_action'" in json_source


def test_every_shipped_runner_and_quick_start_has_a_canonical_visual_starter():
    starters = builtin_template_catalog()
    ids = {starter["id"] for starter in starters}
    assert len(starters) == 18
    assert sum(item.startswith("builtin:runner-templates:") for item in ids) == 11
    assert sum(item.startswith("builtin:quick-starts:") for item in ids) == 7
    assert "builtin:runner-templates:native-improvement-cycle" in ids
    assert "builtin:quick-starts:openorbit.continuous-user-journey" in ids
    for starter in starters:
        source = generate_source(starter["blueprint"])
        assert "ctx.run_visual_node('template_" not in source
        assert "step_id=" in source


def test_every_canonical_step_has_an_explicit_sdk_owned_visual_node():
    registered = {item["kind"] for item in visual_nodes.catalog()}
    for definition in definitions().values():
        for node in definition.blueprint["nodes"]:
            assert node["kind"] in registered
            visual_nodes.validate(node["kind"], node["config"])


def test_template_definitions_preserve_canonical_lifecycle_step_ids_and_edges():
    for template in templates().values():
        definition = definitions()[template.id]
        assert {node["id"] for node in definition.blueprint["nodes"]} == {step.id for step in template.steps}
        assert definition.blueprint["edges"] == list(template.edges)
        source = generate_source(definition.blueprint)
        for step in template.steps:
            assert f"@graph.step({step.id!r}" in source
            assert f"step_id={step.id!r}" in source


def test_shipped_template_graphs_connect_each_lifecycle_step():
    for template in templates().values():
        incoming = {step.id: 0 for step in template.steps}
        for edge in template.edges:
            if edge["target"] in incoming:
                incoming[edge["target"]] += 1
        disconnected = [
            step.id for step in template.steps if step.phase != "before_all" and incoming[step.id] == 0
        ]
        assert not disconnected, f"{template.id} has disconnected steps: {disconnected}"


def test_template_definitions_use_only_reusable_material_nodes():
    for definition in definitions().values():
        kinds = {node["kind"] for node in definition.blueprint["nodes"]}
        assert not any(kind.startswith("template_") for kind in kinds)
        assert "builtin_template_step" not in kinds


def test_visible_catalog_contains_only_composable_material_groups():
    groups = {item["group_key"] for item in visual_nodes.catalog() if item["palette_visible"]}
    assert groups == {
        "actions",
        "advanced",
        "ai",
        "browser",
        "contracts",
        "evidence",
        "improvement",
        "journeys",
        "state",
    }


def test_quick_start_parameters_bind_only_declared_blueprint_values():
    definition = definitions()["quick-starts:openorbit.agent-self-improvement"]
    blueprint = instantiate_definition(definition, {"agent_provider": "claude", "agent_options": "--fast"})
    proposal = next(node for node in blueprint["nodes"] if node["id"] == "propose-agent-change")
    assert proposal["config"] == {"provider": "claude", "options": "--fast"}


def test_template_definitions_generate_valid_runner_sources():
    for definition in definitions().values():
        ast.parse(generate_source(definition.blueprint))


def test_visual_runtime_bindings_resolve_only_context_inputs_and_resources():
    class Context:
        loop_index = 4
        build = {"id": "build-1", "browser_base_url": "https://example.test"}
        test_cases = [{"id": "case-1"}]
        previous_supervisor_feedback = {"reported_issues": ["one"]}
        current_issue_assessment = {}
        environment = {"ORBIT_RUN_ID": "run-1"}
        phase = "execute"

        def resource(self, name, default):
            return {"model_profile": {"model": "test-model"}}.get(name, default)

        def load_state(self, name, default, *, scope):
            assert (name, scope) == ("journey", "runner")
            return {"next_case": 2}

    context = Context()
    value = resolve(
        context,
        {
            "iteration": {"$ctx": "loop_index"},
            "base_url": {"$ctx": "build.browser_base_url"},
            "case": {"$input": "selected.id"},
            "model": {"$resource": "model_profile.model"},
            "state": {"$state": {"name": "journey", "path": "next_case"}},
        },
        {"selected": {"id": "case-1"}},
    )

    assert value == {
        "iteration": 4,
        "base_url": "https://example.test",
        "case": "case-1",
        "model": "test-model",
        "state": 2,
    }
    assert evaluate(context, {"$equals": [{"$ctx": "loop_index"}, 4]}, {}) is True


def test_visual_runner_generates_a_safe_node_condition():
    value = blueprint()
    value["nodes"][0]["when"] = {"$exists": {"$ctx": "build.browser_base_url"}}

    source = generate_source(value)

    assert "ctx.visual_should_run" in source
    assert "return" in source
