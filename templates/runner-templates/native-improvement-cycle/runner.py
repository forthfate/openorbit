# Requirements
# - PROJECT_ROOT is a Git repository.
# - The build selects fixed target-AI prompts and a configured model
#   profile, plus a readable managed_prompt_path on its Target Environment.
# - Only human-accepted feedback is applied to the prompt.
# This runner never commits target changes; ctx.update_file keeps rollback versions.

import hashlib
import json
import re

from orbit_sdk import graph, runner

REQUIRED_SUFFICIENT_EVALUATIONS = 3

graph.connect("validate-target", "prepare-prompt")
graph.connect("prepare-prompt", "exercise-target", label="managed prompt")
graph.connect("exercise-target", "assess-candidate", kind="data", label="responses")
graph.connect("assess-candidate", "retain-iteration")
graph.connect("retain-iteration", "prepare-prompt", kind="loop", label="next evaluation")
graph.connect("retain-iteration", "restore-baseline", kind="condition", label="completed")
# Marker comments make replacement idempotent and preserve the surrounding
# target prompt content that OpenOrbit does not own.
PROMPT_BLOCK_START = "<!-- OPENORBIT_ACCEPTED_PROPOSALS_START -->"
PROMPT_BLOCK_END = "<!-- OPENORBIT_ACCEPTED_PROPOSALS_END -->"


def state_path(ctx):
    """Return the per-build state file outside the target repository."""
    build_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(ctx.build.get("id") or "manual"))
    directory = ctx.app_data / "improvement-cycles"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{build_id}.json"


def load_state(ctx):
    """Load the previous verdict state, or start a fresh candidate baseline."""
    path = state_path(ctx)
    if not path.exists():
        return {"candidate_fingerprint": None, "sufficient_evaluations": 0, "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(ctx, state):
    """Persist only bounded history so recurring evaluations do not grow unbounded."""
    state["history"] = state.get("history", [])[-24:]
    state_path(ctx).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def git(ctx, *args):
    """Run Git in the configured project root without invoking a shell."""
    return ctx.exec(["git", *args], cwd=ctx.project_root, timeout=300)


def candidate(ctx):
    """Fingerprint the current working-tree diff and retain its changed paths."""
    patch = git(ctx, "diff", "--binary", "--")
    changed = [line for line in git(ctx, "diff", "--name-only").splitlines() if line]
    return (hashlib.sha256(patch.encode("utf-8")).hexdigest() if patch else None), changed


def update_prompt_from_accepted_proposals(ctx, proposals):
    """Replace only OpenOrbit's managed prompt block and retain a rollback version."""
    prompt_path = str(ctx.build.get("managed_prompt_path") or ctx.build.get("prompt_bundle") or "").strip()
    if not prompt_path:
        raise ValueError("native improvement cycle requires target_environment.managed_prompt_path")
    target = ctx.project_path(prompt_path)
    current = target.read_text(encoding="utf-8")
    if not proposals:
        # Do not manufacture a changing candidate when the supervisor has not
        # accepted a change. A stable candidate must retain the same fingerprint
        # across repeated validations before it can be promoted.
        return {"path": prompt_path, "changed": False, "reason": "no_accepted_proposals"}
    lines = ["## Accepted improvement proposals", "", f"Iteration: {ctx.loop_index}", ""]
    for proposal in proposals:
        lines.extend(
            (
                f"### {proposal.get('title') or 'Accepted proposal'}",
                str(proposal.get("rationale") or ""),
                f"Acceptance evidence: {proposal.get('acceptanceEvidence') or ''}",
                "",
            )
        )
    block = "\n".join((PROMPT_BLOCK_START, "\n".join(lines).rstrip(), PROMPT_BLOCK_END))
    start, end = current.find(PROMPT_BLOCK_START), current.find(PROMPT_BLOCK_END)
    if start >= 0 and end > start:
        updated = current[:start] + block + current[end + len(PROMPT_BLOCK_END) :]
    elif start >= 0 or end >= 0:
        raise ValueError("prompt has an incomplete OpenOrbit accepted-proposals block")
    else:
        updated = current.rstrip() + "\n\n" + block + "\n"
    return ctx.update_file(prompt_path, updated)


def managed_prompt_evidence(ctx):
    """Expose the current managed prompt beside the target-AI response evidence."""
    prompt_path = str(ctx.build.get("managed_prompt_path") or ctx.build.get("prompt_bundle") or "").strip()
    if not prompt_path:
        raise ValueError("native improvement cycle requires target_environment.managed_prompt_path")
    content = ctx.project_path(prompt_path).read_text(encoding="utf-8")
    return {
        "path": prompt_path,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


@graph.step("validate-target", title="Validate target", phase="before_all", outputs=["evaluation_contract"])
@runner.phase("before_all")
def before_all(ctx):
    # Process-level validation runs once before the iteration loop begins.
    git(ctx, "rev-parse", "--show-toplevel")
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed target-AI prompt for a native improvement cycle")
    if not isinstance(ctx.resource("model_profile", {}), dict) or not ctx.resource("model_profile", {}).get(
        "model"
    ):
        raise ValueError("Select a configured model profile for a native improvement cycle")
    ctx.log("Validated an OpenOrbit-native target-AI prompt improvement cycle")


@graph.step(
    "prepare-prompt",
    title="Prepare prompt candidate",
    phase="before_each",
    inputs=["evaluation_contract"],
    outputs=["managed_prompt"],
)
@runner.phase("before_each")
def before_each(ctx):
    # Keep the target's complete pre-evaluation state outside commit history.
    # The call is idempotent because before_each runs for every iteration.
    ctx.save_before_each_snapshot()
    # Apply only feedback accepted by a human before the next validation.
    feedback = ctx.previous_supervisor_feedback
    accepted = [
        proposal
        for proposal in feedback.get("improvements", [])
        if isinstance(proposal, dict) and str(proposal.get("status") or "").lower() == "accepted"
    ]
    requires_human_approval = bool(ctx.build.get("require_human_approval_before_apply", False))
    if requires_human_approval and accepted:
        # A supervisor's adoption is a recommendation, not an operator
        # authorization. Keep it as evidence until an operator approves it.
        prompt_update = {
            "changed": False,
            "reason": "awaiting_human_approval",
            "proposal_count": len(accepted),
        }
        accepted = []
    else:
        prompt_update = update_prompt_from_accepted_proposals(ctx, accepted)
    accepted_ids = [str(value) for value in feedback.get("_orbit_proposal_ids", [])]
    proposal_applications = ctx.record_proposal_application(accepted_ids, prompt_update)
    fingerprint, changed = candidate(ctx)
    ctx.emit_result(
        {
            "improvement_cycle": {
                "iteration": ctx.loop_index,
                "candidate_fingerprint": fingerprint,
                "changed_paths": changed,
                "prompt_update": prompt_update,
                "requires_human_approval": requires_human_approval,
                "managed_prompt": managed_prompt_evidence(ctx),
                "proposal_applications": proposal_applications,
            }
        }
    )
    ctx.log("Refreshed the rollback-protected prompt from accepted supervisor feedback")


@graph.step(
    "exercise-target",
    title="Exercise target AI",
    phase="execute",
    inputs=["managed_prompt"],
    outputs=["target_responses"],
)
@runner.phase("execute")
def execute(ctx):
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
    fingerprint, changed = candidate(ctx)
    ctx.emit_result(
        {
            "improvement_cycle": {
                "iteration": ctx.loop_index,
                "candidate_fingerprint": fingerprint,
                "changed_paths": changed,
                "evidence": {"target_ai_responses": responses, "artifact": artifact},
            }
        }
    )


@graph.step(
    "assess-candidate",
    title="Assess candidate evidence",
    phase="verify",
    inputs=["target_responses"],
    outputs=["candidate_verdict"],
)
@runner.phase("verify")
def verify(ctx):
    # Promote a candidate only after the required number of stable evaluations.
    state = load_state(ctx)
    fingerprint, changed = candidate(ctx)
    if not fingerprint:
        state["candidate_fingerprint"] = None
        state["sufficient_evaluations"] = 0
        verdict = "no_candidate"
    elif state.get("candidate_fingerprint") == fingerprint:
        state["sufficient_evaluations"] = int(state.get("sufficient_evaluations", 0)) + 1
        verdict = (
            "ready_for_approval"
            if state["sufficient_evaluations"] >= REQUIRED_SUFFICIENT_EVALUATIONS
            else "continue_validation"
        )
    else:
        state["candidate_fingerprint"] = fingerprint
        state["sufficient_evaluations"] = 1
        verdict = "continue_validation"
    state.setdefault("history", []).append(
        {"iteration": ctx.loop_index, "fingerprint": fingerprint, "paths": changed, "verdict": verdict}
    )
    save_state(ctx, state)
    ctx.emit_result(
        {
            "improvement_cycle": {
                "candidate_fingerprint": fingerprint,
                "changed_paths": changed,
                "sufficient_evaluations": state["sufficient_evaluations"],
                "required_evaluations": REQUIRED_SUFFICIENT_EVALUATIONS,
                "verdict": verdict,
            }
        }
    )
    ctx.log(f"Candidate verdict: {verdict}")


@graph.step(
    "retain-iteration",
    title="Retain iteration evidence",
    phase="after_each",
    inputs=["candidate_verdict"],
    outputs=["iteration_snapshot"],
)
@runner.phase("after_each")
def after_each(ctx):
    # Preserve the first evaluated state as a named recovery checkpoint.
    ctx.save_first_after_each_snapshot()
    # Per-iteration evidence remains available for supervisor review.
    ctx.log("Retained prompt versions, decisions, and validation evidence")


@graph.step(
    "restore-baseline",
    title="Restore baseline",
    phase="after_all",
    inputs=["iteration_snapshot"],
    outputs=["restored_target"],
)
@runner.phase("after_all")
def after_all(ctx):
    # Return the target to its exact baseline without creating a Git commit.
    ctx.restore_before_each_snapshot()
    ctx.log("Restored the native improvement target without committing changes")


if __name__ == "__main__":
    runner.main()
