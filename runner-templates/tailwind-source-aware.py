"""Reference runner for Tailwind applications with rendered browser evidence."""

from orbit_sdk import graph, runner

graph.connect("inspect-source", "run-browser")
graph.connect("run-browser", "publish-evidence")


@graph.step(
    "inspect-source",
    title="Inspect Tailwind source contract",
    phase="before_all",
    outputs=["source_contract"],
)
@runner.phase("before_all")
def before_all(ctx):
    # Inspect stylesheet content as well as config paths: Tailwind v4 commonly
    # uses `@import "tailwindcss"` in an otherwise generic `index.css` name.
    files = ctx.exec(
        ["sh", "-lc", "rg -l 'tailwindcss|@tailwind' --glob '*.css' . || true"],
        cwd=ctx.project_root,
        timeout=30,
    )
    config = ctx.exec(
        ["sh", "-lc", "rg --files -g 'tailwind.config.*' . || true"], cwd=ctx.project_root, timeout=30
    )
    if not files.strip() and not config.strip():
        raise ValueError("No Tailwind configuration or stylesheet was found in the target project")
    if not ctx.build.get("browser_base_url") or not ctx.test_cases:
        raise ValueError("A browser base URL and at least one journey case are required")
    ctx.emit_result(
        {
            "tailwind_journey": {
                "stylesheet_files": files.splitlines()[:40],
                "config_files": config.splitlines()[:20],
            }
        }
    )
    ctx.log("Validated the Tailwind source contract")


@graph.step(
    "run-browser",
    title="Run rendered Tailwind journey",
    phase="execute",
    inputs=["source_contract"],
    outputs=["browser_evidence"],
)
@runner.phase("execute")
def execute(ctx):
    # The SDK captures screenshots and visible-page evidence; Tailwind class names
    # are never treated as proof that a user-visible interaction succeeded.
    evidence = ctx.playwright_journey()
    ctx.emit_result({"tailwind_journey": {"iteration": ctx.loop_index, "evidence": evidence}})
    ctx.save_data_file(
        f"tailwind-journey/iteration-{ctx.loop_index}.json",
        __import__("json").dumps(evidence, ensure_ascii=False, indent=2),
        label="Tailwind rendered journey evidence",
        content_type="application/json",
    )


@graph.step(
    "publish-evidence",
    title="Publish rendered evidence",
    phase="verify",
    inputs=["browser_evidence"],
    outputs=["review_ready"],
)
@runner.phase("verify")
def verify(ctx):
    ctx.log("Published Tailwind source context with rendered browser evidence")


@runner.phase("after_each")
def after_each(ctx):
    ctx.log("Completed one bounded Tailwind browser journey")


@runner.phase("after_all")
def after_all(ctx):
    ctx.log("Finalized the Tailwind browser evaluation")


if __name__ == "__main__":
    runner.main()
