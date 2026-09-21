"""Validate a declared source contract before running rendered browser journeys.

Source matches provide implementation context only; rendered browser evidence
remains the proof of user-visible behavior. The lifecycle keeps those two kinds
of evidence distinct for supervisor review.
"""

import json
import os

from orbit_sdk import graph, runner


def source_contract(ctx):
    """Return bounded source evidence without treating source as UI proof.

    Args:
        ctx: The active Orbit runner context.

    Returns:
        The configured expression and a bounded list of matching files.

    Raises:
        ValueError: If the source contract is absent or has no matching files.
    """
    pattern = os.environ.get("ORBIT_SOURCE_CONTRACT_PATTERN", "").strip()
    if not pattern:
        raise ValueError("Set ORBIT_SOURCE_CONTRACT_PATTERN to a required source expression")
    glob = os.environ.get("ORBIT_SOURCE_CONTRACT_GLOB", "").strip()
    command = ["rg", "-l", pattern]
    if glob:
        command.extend(["--glob", glob])
    command.append(".")
    output = ctx.exec(command, cwd=ctx.project_root, timeout=30)
    files = [path for path in output.splitlines() if path][:40]
    if not files:
        raise ValueError("The configured source contract was not found in the target project")
    return {"pattern": pattern, "glob": glob or None, "files": files}


graph.connect("validate-source-contract", "run-browser-journey")
graph.connect("run-browser-journey", "publish-rendered-evidence", kind="data", label="browser evidence")
graph.connect("publish-rendered-evidence", "close-source-aware-cycle")
graph.connect("close-source-aware-cycle", "run-browser-journey", kind="loop", label="next iteration")
graph.connect(
    "close-source-aware-cycle", "finalize-source-aware-journey", kind="condition", label="completed"
)


@graph.step(
    "validate-source-contract",
    title="Validate source and browser contract",
    phase="before_all",
    outputs=["source_contract"],
)
@runner.phase("before_all", step_id="validate-source-contract")
def validate_source_contract(ctx):
    """Validate browser inputs and publish the source-side contract."""
    if not ctx.build.get("browser_base_url") or not ctx.test_cases:
        raise ValueError("A browser base URL and at least one fixed journey case are required")
    contract = source_contract(ctx)
    ctx.emit_result({"source_aware_journey": {"source_contract": contract}})
    ctx.log(f"Validated source contract in {len(contract['files'])} file(s)")


@graph.step(
    "run-browser-journey",
    title="Run rendered browser journey",
    phase="execute",
    inputs=["source_contract"],
    outputs=["browser_evidence"],
)
@runner.phase("execute", step_id="run-browser-journey")
def run_browser_journey(ctx):
    """Run the rendered browser journey independently of source evidence."""
    evidence = ctx.playwright_journey()
    ctx.emit_result({"source_aware_journey": {"iteration": ctx.loop_index, "evidence": evidence}})
    ctx.save_data_file(
        f"source-aware-journey/iteration-{ctx.loop_index}.json",
        json.dumps(evidence, ensure_ascii=False, indent=2),
        label="Source-aware rendered journey evidence",
        content_type="application/json",
    )


@graph.step(
    "publish-rendered-evidence",
    title="Publish rendered evidence",
    phase="verify",
    inputs=["browser_evidence"],
    outputs=["review_ready"],
)
@runner.phase("verify", step_id="publish-rendered-evidence")
def publish_rendered_evidence(ctx):
    """Mark the combined source and browser evidence ready for review."""
    ctx.log("Published source context with rendered browser evidence")


@graph.step(
    "close-source-aware-cycle",
    title="Close source-aware browser cycle",
    phase="after_each",
    inputs=["review_ready"],
    outputs=["cycle_complete"],
)
@runner.phase("after_each", step_id="close-source-aware-cycle")
def close_source_aware_cycle(ctx):
    """Close one bounded source-aware browser iteration."""
    ctx.log("Completed one bounded source-aware browser journey")


@graph.step(
    "finalize-source-aware-journey",
    title="Finalize source-aware browser journey",
    phase="after_all",
    inputs=["cycle_complete"],
    outputs=["journey_complete"],
)
@runner.phase("after_all", step_id="finalize-source-aware-journey")
def finalize_source_aware_journey(ctx):
    """Finalize the source-aware browser journey."""
    ctx.log("Finalized the source-aware browser evaluation")


if __name__ == "__main__":
    runner.main()
