"""Create an evidence-backed agent self-improvement in an isolated worktree.

Requires a Git repository, fixed target-AI cases, a model profile, and a
readable managed prompt. The coding agent's diff is retained for review and
never applied automatically to the source repository.
"""

import hashlib
import json

from orbit_sdk import graph, runner

AGENT_PROVIDER = "${agent_provider}"
AGENT_OPTIONS = "${agent_options}"

graph.connect("validate-target", "validate-evaluation-inputs")
graph.connect("validate-evaluation-inputs", "prepare-prompt")
graph.connect("prepare-prompt", "exercise-target", label="managed prompt")
graph.connect("exercise-target", "retain-iteration", kind="data", label="responses")
graph.connect("retain-iteration", "propose-agent-change", label="supervisor assessment")
graph.connect("propose-agent-change", "prepare-prompt", kind="loop", label="next evaluation")


def git(ctx, *args):
    """Run Git in the configured project root without invoking a shell.

    Args:
        ctx: The active Orbit runner context.
        *args: Git arguments excluding the executable name.

    Returns:
        Standard output from the Git command.
    """
    return ctx.exec(["git", *args], cwd=ctx.project_root, timeout=300)


def managed_prompt_evidence(ctx):
    """Read and fingerprint the prompt that the agent will improve.

    Args:
        ctx: The active Orbit runner context.

    Returns:
        The path, content, and SHA-256 fingerprint of the managed prompt.

    Raises:
        ValueError: If no managed prompt path is configured.
    """
    prompt_path = str(ctx.build.get("managed_prompt_path") or ctx.build.get("prompt_bundle") or "").strip()
    if not prompt_path:
        raise ValueError("native improvement cycle requires target_environment.managed_prompt_path")
    content = ctx.project_path(prompt_path).read_text(encoding="utf-8")
    return {
        "path": prompt_path,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


def agent_task(ctx):
    """Build a bounded, autonomous objective for the coding agent.

    The task explicitly confines the agent's modifications to its isolated
    proposal worktree; it never authorizes an automatic source-repository edit.
    """
    issue = ctx.current_issue_assessment
    return "\n".join(
        (
            "You are the autonomous improvement agent for this repository.",
            "Do not ask questions or wait for approval. First inspect the repository and the managed prompt, then make exactly one atomic, evidence-backed improvement, validate it, and finish the task completely.",
            "You are working in an isolated proposal worktree. Make the complete change there; it will be captured as a reviewable diff and will not be applied to the source repository automatically. Do not commit, reset, or discard unrelated user changes.",
            f"Managed prompt path: {ctx.build.get('managed_prompt_path') or ctx.build.get('prompt_bundle')}",
            f"Build purpose: {ctx.build.get('purpose', '')}",
            f"Fixed acceptance criteria: {json.dumps([case.get('acceptance', '') for case in ctx.test_cases], ensure_ascii=False)}",
            f"Supervisor-assessed issue to resolve: {json.dumps(issue, ensure_ascii=False)}",
            "If you completed meaningful feedback or a change, print one final line exactly in this format: ORBIT_AGENT_FEEDBACK: <concise completed-work summary>. If there is no meaningful feedback, do not print that marker.",
        )
    )


@graph.step(
    "validate-target", title="Validate target repository", phase="before_all", outputs=["repository_target"]
)
@runner.phase("before_all", step_id="validate-target")
def before_all(ctx):
    """Validate that the configured repository is a Git worktree."""
    # Repository validation runs once before the iteration loop begins.
    git(ctx, "rev-parse", "--show-toplevel")


@graph.step(
    "validate-evaluation-inputs",
    title="Validate evaluation inputs",
    phase="before_all",
    inputs=["repository_target"],
    outputs=["evaluation_contract"],
)
@runner.phase("before_all", step_id="validate-evaluation-inputs")
def validate_evaluation_inputs(ctx):
    """Validate fixed target-AI cases and the selected model profile."""
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed target-AI prompt for a native improvement cycle")
    if not isinstance(ctx.resource("model_profile", {}), dict) or not ctx.resource("model_profile", {}).get(
        "model"
    ):
        raise ValueError("Select a configured model profile for a native improvement cycle")
    ctx.log("Validated an OpenOrbit-native target-AI prompt improvement cycle")


@graph.step(
    "prepare-prompt",
    title="Read change target",
    phase="before_each",
    inputs=["evaluation_contract"],
    outputs=["managed_prompt"],
)
@runner.phase("before_each", step_id="prepare-prompt")
def before_each(ctx):
    """Expose the current prompt as read-only evidence for this iteration."""
    ctx.emit_result(
        {
            "improvement_cycle": {
                "iteration": ctx.loop_index,
                "proposal_mode": "isolated_worktree",
                "managed_prompt": managed_prompt_evidence(ctx),
            }
        }
    )


@graph.step(
    "exercise-target",
    title="Exercise target AI",
    phase="execute",
    inputs=["managed_prompt"],
    outputs=["target_responses"],
)
@runner.phase("execute", step_id="exercise-target")
def execute(ctx):
    """Exercise the target AI and retain raw response evidence."""
    # Exercise the evaluated AI with the current managed prompt. The raw reply
    # is retained as supervisor evidence instead of treating a browser page as
    # proof that a prompt instruction was followed.
    managed_prompt = managed_prompt_evidence(ctx)
    responses = []
    for case in ctx.test_cases:
        request = str(case.get("prompt") or "").strip()
        if not request:
            raise ValueError("each target-AI test case requires a prompt")
        turn = ctx.complete_model(
            "# Managed agent instructions\\n"
            + managed_prompt["content"]
            + "\\n\\n# User request\\n"
            + request
            + "\\n\\nRespond as the managed agent."
        )
        responses.append(
            {
                "id": case.get("id"),
                "name": case.get("name"),
                "request": request,
                "acceptance": str(case.get("acceptance") or ""),
                "response": turn["response"],
                "model": turn["model"],
            }
        )
    artifact = ctx.save_data_file(
        "target-ai-responses.json",
        json.dumps(responses, ensure_ascii=False, indent=2),
        label="Target AI responses",
        content_type="application/json",
    )
    ctx.emit_result(
        {
            "improvement_cycle": {
                "iteration": ctx.loop_index,
                "evidence": {"target_ai_responses": responses, "artifact": artifact},
            }
        }
    )


@graph.step(
    "propose-agent-change",
    title="Create agent proposal for assessed issue",
    phase="after_each",
    inputs=["iteration_snapshot"],
    outputs=["agent_proposal"],
    after_supervision=True,
)
@runner.phase("after_each", step_id="propose-agent-change")
def propose_agent_change(ctx):
    """Create one isolated worktree proposal for a supervisor-assessed issue."""
    issue = ctx.current_issue_assessment
    assessment = issue.get("evaluation") if isinstance(issue, dict) else None
    decision = assessment.get("approval") if isinstance(assessment, dict) else None
    if not issue:
        ctx.emit_result({"agent_proposal": {"skipped": True, "reason": "no_reported_issue"}})
        return
    if decision == "rejected":
        ctx.emit_result({"agent_proposal": {"skipped": True, "reason": "issue_rejected", "issue": issue}})
        ctx.log("Skipped AI agent work because the supervisor rejected the issue")
        return
    agent = ctx.run_ai_agent(agent_task(ctx), provider=AGENT_PROVIDER, options=AGENT_OPTIONS)
    proposal = agent.get("proposal", {})
    if agent["feedback"] and agent["changed_files"] and proposal.get("fingerprint"):
        ctx.register_evaluation(
            str(agent["feedback"]),
            changed_files=[str(path) for path in agent["changed_files"]],
            validation="Agent completed its autonomous repository task.",
            improvement_fingerprint=str(proposal["fingerprint"]),
        )
    ctx.emit_result(
        {
            "agent_proposal": {
                "issue": issue,
                "agent": {key: value for key, value in agent.items() if key != "output"},
            }
        }
    )
    ctx.log("Retained an isolated agent change proposal for review")


@graph.step(
    "retain-iteration",
    title="Retain assessment evidence",
    phase="after_each",
    inputs=["target_responses"],
    outputs=["iteration_snapshot"],
)
@runner.phase("after_each", step_id="retain-iteration")
def after_each(ctx):
    """Keep target-AI evidence available after supervisor assessment."""
    # Per-iteration evidence remains available for supervisor review.
    ctx.log("Retained target-AI responses and supervisor assessment evidence")


if __name__ == "__main__":
    runner.main()
