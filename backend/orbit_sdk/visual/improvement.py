"""Reusable, evidence-backed prompt-improvement operations for Visual Mode."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from ..decorators.visual import visual_node

_REQUIRED_SUFFICIENT_EVALUATIONS = 3
_PROMPT_BLOCK_START = "<!-- OPENORBIT_ACCEPTED_PROPOSALS_START -->"
_PROMPT_BLOCK_END = "<!-- OPENORBIT_ACCEPTED_PROPOSALS_END -->"


def _git(ctx: Any, *args: str) -> str:
    return ctx.exec(["git", *args], cwd=ctx.project_root, timeout=300)


def _prompt_path(ctx: Any) -> str:
    value = str(ctx.build.get("managed_prompt_path") or ctx.build.get("prompt_bundle") or "").strip()
    if not value:
        raise ValueError("native improvement cycle requires target_environment.managed_prompt_path")
    return value


def _prompt_evidence(ctx: Any) -> dict[str, str]:
    path = _prompt_path(ctx)
    content = ctx.project_path(path).read_text(encoding="utf-8")
    return {"path": path, "sha256": hashlib.sha256(content.encode()).hexdigest(), "content": content}


def _candidate(ctx: Any) -> tuple[str | None, list[str]]:
    patch = _git(ctx, "diff", "--binary", "--")
    changed = [line for line in _git(ctx, "diff", "--name-only").splitlines() if line]
    return (hashlib.sha256(patch.encode()).hexdigest() if patch else None), changed


def _state_path(ctx: Any) -> Any:
    build_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(ctx.build.get("id") or "manual"))
    directory = ctx.app_data / "improvement-cycles"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{build_id}.json"


def _load_state(ctx: Any) -> dict[str, Any]:
    path = _state_path(ctx)
    if not path.exists():
        return {"candidate_fingerprint": None, "sufficient_evaluations": 0, "history": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    return (
        value
        if isinstance(value, dict)
        else {"candidate_fingerprint": None, "sufficient_evaluations": 0, "history": []}
    )


def _save_state(ctx: Any, state: dict[str, Any]) -> None:
    state["history"] = list(state.get("history", []))[-24:]
    _state_path(ctx).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _accepted_proposals(ctx: Any) -> list[dict[str, Any]]:
    feedback = ctx.previous_supervisor_feedback
    return [
        proposal
        for proposal in feedback.get("improvements", [])
        if isinstance(proposal, dict) and str(proposal.get("status") or "").lower() == "accepted"
    ]


def _apply_proposals(ctx: Any, proposals: list[dict[str, Any]]) -> dict[str, object]:
    path = _prompt_path(ctx)
    current = ctx.project_path(path).read_text(encoding="utf-8")
    if not proposals:
        return {"path": path, "changed": False, "reason": "no_accepted_proposals"}
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
    block = "\n".join((_PROMPT_BLOCK_START, "\n".join(lines).rstrip(), _PROMPT_BLOCK_END))
    start, end = current.find(_PROMPT_BLOCK_START), current.find(_PROMPT_BLOCK_END)
    if start >= 0 and end > start:
        updated = current[:start] + block + current[end + len(_PROMPT_BLOCK_END) :]
    elif start >= 0 or end >= 0:
        raise ValueError("prompt has an incomplete OpenOrbit accepted-proposals block")
    else:
        updated = current.rstrip() + "\n\n" + block + "\n"
    return ctx.update_file(path, updated)


@visual_node(
    kind="validate_git_repository",
    group_key="improvement",
    display_name="Validate Git repository",
    title_key="visual.nodes.validateGitRepository.title",
    description_key="visual.nodes.validateGitRepository.description",
    default_outputs=("repository_target",),
)
def validate_git_repository(ctx: Any, _: Mapping[str, Any], __: Mapping[str, object]) -> dict[str, object]:
    """Require a Git worktree before an improvement operation begins."""
    _git(ctx, "rev-parse", "--show-toplevel")
    return {"repository_target": True}


@visual_node(
    kind="validate_improvement_inputs",
    group_key="improvement",
    display_name="Validate improvement inputs",
    title_key="visual.nodes.validateImprovementInputs.title",
    description_key="visual.nodes.validateImprovementInputs.description",
    default_outputs=("evaluation_contract",),
)
def validate_improvement_inputs(
    ctx: Any, _: Mapping[str, Any], __: Mapping[str, object]
) -> dict[str, object]:
    """Require fixed target-AI cases and the selected model profile."""
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed target-AI prompt for a native improvement cycle")
    profile = ctx.resource("model_profile", {})
    if not isinstance(profile, dict) or not profile.get("model"):
        raise ValueError("Select a configured model profile for a native improvement cycle")
    ctx.log("Validated an OpenOrbit-native target-AI prompt improvement cycle")
    return {"evaluation_contract": True}


@visual_node(
    kind="prepare_managed_prompt",
    group_key="improvement",
    display_name="Prepare managed prompt",
    title_key="visual.nodes.prepareManagedPrompt.title",
    description_key="visual.nodes.prepareManagedPrompt.description",
    default_config={"mode": "apply_accepted"},
    default_outputs=("managed_prompt",),
)
def prepare_managed_prompt(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Apply approved changes or expose a prompt as isolated-worktree evidence."""
    mode = str(config.get("mode", "apply_accepted"))
    if mode == "isolated_worktree":
        value = {"iteration": ctx.loop_index, "proposal_mode": mode, "managed_prompt": _prompt_evidence(ctx)}
    elif mode == "apply_accepted":
        accepted = _accepted_proposals(ctx)
        required = bool(ctx.build.get("require_human_approval_before_apply", False))
        update = (
            {"changed": False, "reason": "awaiting_human_approval", "proposal_count": len(accepted)}
            if required and accepted
            else _apply_proposals(ctx, accepted if not required else [])
        )
        ids = [str(value) for value in ctx.previous_supervisor_feedback.get("_orbit_proposal_ids", [])]
        fingerprint, changed = _candidate(ctx)
        value = {
            "iteration": ctx.loop_index,
            "candidate_fingerprint": fingerprint,
            "changed_paths": changed,
            "prompt_update": update,
            "requires_human_approval": required,
            "managed_prompt": _prompt_evidence(ctx),
            "proposal_applications": ctx.record_proposal_application(ids, update),
        }
        ctx.log("Refreshed the rollback-protected prompt from accepted supervisor feedback")
    else:
        raise ValueError("has an unsupported managed prompt mode")
    ctx.emit_result({"improvement_cycle": value})
    return {"managed_prompt": value["managed_prompt"]}


@visual_node(
    kind="exercise_managed_prompt",
    group_key="improvement",
    display_name="Exercise managed prompt",
    title_key="visual.nodes.exerciseManagedPrompt.title",
    description_key="visual.nodes.exerciseManagedPrompt.description",
    default_config={"include_candidate": False},
    default_outputs=("target_responses",),
)
def exercise_managed_prompt(
    ctx: Any, config: Mapping[str, Any], __: Mapping[str, object]
) -> dict[str, object]:
    """Run every fixed request against the managed prompt and retain raw evidence."""
    prompt = _prompt_evidence(ctx)
    responses: list[dict[str, object]] = []
    for case in ctx.test_cases:
        request = str(case.get("prompt") or "").strip()
        if not request:
            raise ValueError("each target-AI test case requires a prompt")
        turn = ctx.complete_model(
            "# Managed agent instructions\n"
            + prompt["content"]
            + "\n\n# User request\n"
            + request
            + "\n\nRespond as the managed agent."
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
    fingerprint, changed = _candidate(ctx)
    value: dict[str, object] = {
        "iteration": ctx.loop_index,
        "evidence": {"target_ai_responses": responses, "artifact": artifact},
    }
    if config.get("include_candidate", False) or fingerprint or changed:
        value.update({"candidate_fingerprint": fingerprint, "changed_paths": changed})
    ctx.emit_result({"improvement_cycle": value})
    return {"target_responses": responses}


@visual_node(
    kind="assess_prompt_candidate",
    group_key="improvement",
    display_name="Assess prompt candidate",
    title_key="visual.nodes.assessPromptCandidate.title",
    description_key="visual.nodes.assessPromptCandidate.description",
    default_outputs=("candidate_verdict",),
)
def assess_prompt_candidate(ctx: Any, _: Mapping[str, Any], __: Mapping[str, object]) -> dict[str, object]:
    """Promote only a stable candidate after repeated sufficient evaluations."""
    state = _load_state(ctx)
    fingerprint, changed = _candidate(ctx)
    if not fingerprint:
        state["candidate_fingerprint"], state["sufficient_evaluations"], verdict = None, 0, "no_candidate"
    elif state.get("candidate_fingerprint") == fingerprint:
        state["sufficient_evaluations"] = int(state.get("sufficient_evaluations", 0)) + 1
        verdict = (
            "ready_for_approval"
            if state["sufficient_evaluations"] >= _REQUIRED_SUFFICIENT_EVALUATIONS
            else "continue_validation"
        )
    else:
        state["candidate_fingerprint"], state["sufficient_evaluations"], verdict = (
            fingerprint,
            1,
            "continue_validation",
        )
    state.setdefault("history", []).append(
        {"iteration": ctx.loop_index, "fingerprint": fingerprint, "paths": changed, "verdict": verdict}
    )
    _save_state(ctx, state)
    value = {
        "candidate_fingerprint": fingerprint,
        "changed_paths": changed,
        "sufficient_evaluations": state["sufficient_evaluations"],
        "required_evaluations": _REQUIRED_SUFFICIENT_EVALUATIONS,
        "verdict": verdict,
    }
    ctx.emit_result({"improvement_cycle": value})
    ctx.log(f"Candidate verdict: {verdict}")
    return {"candidate_verdict": value}


@visual_node(
    kind="retain_improvement_iteration",
    group_key="improvement",
    display_name="Retain improvement iteration",
    title_key="visual.nodes.retainImprovementIteration.title",
    description_key="visual.nodes.retainImprovementIteration.description",
    default_outputs=("iteration_snapshot",),
)
def retain_improvement_iteration(
    ctx: Any, _: Mapping[str, Any], __: Mapping[str, object]
) -> dict[str, object]:
    """Keep a recovery checkpoint and the current improvement evidence."""
    value = ctx.save_first_after_each_snapshot()
    ctx.log("Retained prompt versions, decisions, and validation evidence")
    return {"iteration_snapshot": value}


@visual_node(
    kind="restore_improvement_baseline",
    group_key="improvement",
    display_name="Restore improvement baseline",
    title_key="visual.nodes.restoreImprovementBaseline.title",
    description_key="visual.nodes.restoreImprovementBaseline.description",
    default_outputs=("restored_target",),
)
def restore_improvement_baseline(
    ctx: Any, _: Mapping[str, Any], __: Mapping[str, object]
) -> dict[str, object]:
    """Restore the exact pre-iteration target without creating a commit."""
    value = ctx.restore_before_each_snapshot()
    ctx.log("Restored the native improvement target without committing changes")
    return {"restored_target": value}


@visual_node(
    kind="create_agent_proposal",
    group_key="improvement",
    display_name="Create agent proposal",
    title_key="visual.nodes.createAgentProposal.title",
    description_key="visual.nodes.createAgentProposal.description",
    default_config={"provider": "codex", "options": ""},
    default_outputs=("agent_proposal",),
    required_config=("provider",),
)
def create_agent_proposal(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Ask an isolated coding agent for one supervisor-reviewed proposal."""
    issue = ctx.current_issue_assessment
    assessment = issue.get("evaluation") if isinstance(issue, dict) else None
    if not issue or (isinstance(assessment, dict) and assessment.get("approval") == "rejected"):
        reason = "no_reported_issue" if not issue else "issue_rejected"
        value = {"skipped": True, "reason": reason, **({"issue": issue} if issue else {})}
        ctx.emit_result({"agent_proposal": value})
        if issue:
            ctx.log("Skipped AI agent work because the supervisor rejected the issue")
        return {"agent_proposal": value}
    task = "\n".join(
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
    agent = ctx.run_ai_agent(task, provider=config["provider"], options=config.get("options", ""))
    proposal = agent.get("proposal", {})
    if agent["feedback"] and agent["changed_files"] and proposal.get("fingerprint"):
        ctx.register_evaluation(
            str(agent["feedback"]),
            changed_files=[str(path) for path in agent["changed_files"]],
            validation="Agent completed its autonomous repository task.",
            improvement_fingerprint=str(proposal["fingerprint"]),
        )
    value = {"issue": issue, "agent": {key: value for key, value in agent.items() if key != "output"}}
    ctx.emit_result({"agent_proposal": value})
    ctx.log("Retained an isolated agent change proposal for review")
    return {"agent_proposal": value}
