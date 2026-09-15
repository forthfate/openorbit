"""High-level authoring recipes for concise OpenOrbit runner assets.

This module deliberately sits *above* :mod:`orbit_sdk`. The SDK owns the
stable console protocol and low-level capabilities; this kit turns repeated
runner patterns into small, readable declarations.
"""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from typing import Any

from orbit_runner_primitives import RunnerRequirements, focused_cases


@dataclass(frozen=True)
class CallbackCycle:
    """Register a declarative lifecycle around product-specific callbacks."""

    steps: tuple[tuple[str, str, str, tuple[str, ...], tuple[str, ...]], ...]
    edges: tuple[tuple[str, str, str, str | None], ...]

    def install(self, callbacks: dict[str, Any]) -> None:
        import orbit_sdk

        graph, runner = orbit_sdk.graph, orbit_sdk.runner
        for source, target, kind, label in self.edges:
            graph.connect(source, target, kind=kind, label=label)
        phases: dict[str, list[Any]] = {}
        for identifier, title, phase, inputs, outputs in self.steps:
            callback = callbacks[identifier]

            @graph.step(identifier, title=title, phase=phase, inputs=inputs, outputs=outputs)
            def step(ctx: Any, callback: Any = callback) -> Any:
                return callback(ctx)

            phases.setdefault(phase, []).append(step)
        for phase, handlers in phases.items():

            @runner.phase(phase)
            def invoke(ctx: Any, handlers: list[Any] = handlers) -> None:
                for handler in handlers:
                    handler(ctx)


@dataclass(frozen=True)
class RecurringBrowserJourney:
    """Install a complete, evidence-backed recurring browser journey."""

    namespace: str = "user_journey"
    title: str = "User journey"
    history_limit: int = 24

    def install(self) -> None:
        # Resolve these at installation time so graph previews can use a fresh graph.
        import orbit_sdk

        graph, runner = orbit_sdk.graph, orbit_sdk.runner
        prefix = self.namespace.replace("_", "-")
        validate_id, plan_id, run_id = f"validate-{prefix}", f"plan-{prefix}", f"run-{prefix}"
        review_id, retain_id, finalize_id = f"review-{prefix}", f"retain-{prefix}", f"finalize-{prefix}"
        requirements = RunnerRequirements(build_fields=("browser_base_url",), require_test_cases=True)

        graph.connect(validate_id, plan_id)
        graph.connect(plan_id, run_id, label="focused cases")
        graph.connect(run_id, review_id, kind="data", label="browser evidence")
        graph.connect(review_id, retain_id)
        graph.connect(retain_id, plan_id, kind="loop", label="next iteration")
        graph.connect(retain_id, finalize_id, kind="condition", label="completed")

        @graph.step(
            validate_id,
            title=f"Validate {self.title.lower()} contract",
            phase="before_all",
            outputs=["journey_contract"],
        )
        @runner.phase("before_all")
        def before_all(ctx: Any) -> None:
            requirements.validate(ctx)
            ctx.log(f"Validated the {self.title.lower()} contract")

        @graph.step(
            plan_id,
            title=f"Plan focused {self.title.lower()}",
            phase="before_each",
            inputs=["journey_contract"],
            outputs=["journey_plan"],
        )
        @runner.phase("before_each")
        def before_each(ctx: Any) -> None:
            state = ctx.load_state(
                self.namespace, {"next_case_index": 0, "failed_case_ids": [], "history": []}
            )
            chosen = focused_cases(ctx, state)
            failed = bool(state.get("failed_case_ids"))
            rules = [
                "Preserve observable evidence for every browser action.",
                "Do not infer a result that the page did not expose.",
            ]
            if failed:
                rules.insert(0, "Revisit previously failed journeys before exploring a new route.")
            feedback = ctx.previous_supervisor_feedback
            if feedback.get("reported_issues"):
                rules.insert(0, "Prioritize the supervisor's previously reported issues.")
            plan = {
                "case_ids": [str(case.get("id")) for case in chosen],
                "rules": rules,
                "reason": "Previously failed journeys require confirmation."
                if failed
                else "Rotate one fixed journey to retain broad, bounded coverage.",
                "supervisor_feedback": feedback,
            }
            state["plan"] = plan
            ctx.save_state(self.namespace, state)
            ctx.emit_result(
                {
                    self.namespace: {
                        "iteration": ctx.loop_index,
                        "case_count": len(ctx.test_cases),
                        "plan": plan,
                    }
                }
            )
            ctx.log(f"Planned {len(chosen)} focused journey case(s): {plan['reason']}")

        @graph.step(
            run_id,
            title=f"Run {self.title.lower()}",
            phase="execute",
            inputs=["journey_plan"],
            outputs=["journey_evidence"],
        )
        @runner.phase("execute")
        def execute(ctx: Any) -> None:
            state = ctx.load_state(self.namespace, {})
            plan = state.get("plan") or {}
            chosen_ids = set(plan.get("case_ids", []))
            cases = [case for case in ctx.test_cases if str(case.get("id")) in chosen_ids]
            evidence = ctx.playwright_journey(cases)
            results = list(evidence.get("results", []))
            failed_case_ids = [str(item.get("id")) for item in results if not item.get("passed")]
            state["failed_case_ids"] = failed_case_ids
            state["next_case_index"] = (int(state.get("next_case_index", 0)) + 1) % len(ctx.test_cases)
            handoff = {
                "iteration": ctx.loop_index,
                "reason": plan.get("reason", ""),
                "rules": plan.get("rules", []),
                "passed": len(results) - len(failed_case_ids),
                "failed": len(failed_case_ids),
                "failed_case_ids": failed_case_ids,
            }
            state.setdefault("history", []).append(handoff)
            state["history"] = state["history"][-self.history_limit :]
            state["handoff"] = handoff
            ctx.save_state(self.namespace, state)
            artifact = ctx.save_data_file(
                f"{prefix}/iteration-{ctx.loop_index}.json",
                json.dumps(
                    {"plan": plan, "evidence": evidence, "handoff": handoff}, ensure_ascii=False, indent=2
                ),
                label=f"{self.title} iteration evidence",
                content_type="application/json",
            )
            ctx.emit_result(
                {
                    self.namespace: {
                        "iteration": ctx.loop_index,
                        "plan": plan,
                        "results": results,
                        "evidence": evidence,
                        "handoff": handoff,
                        "artifact": artifact,
                    }
                }
            )

        @graph.step(
            review_id,
            title=f"Review {self.title.lower()} evidence",
            phase="verify",
            inputs=["journey_evidence"],
            outputs=["journey_handoff"],
        )
        @runner.phase("verify")
        def verify(ctx: Any) -> None:
            ctx.emit_result(
                {self.namespace: {"next_iteration": ctx.load_state(self.namespace, {}).get("handoff", {})}}
            )
            ctx.log("Stored the journey summary and next-iteration handoff")

        @graph.step(
            retain_id,
            title=f"Retain {self.title.lower()} result",
            phase="after_each",
            inputs=["journey_handoff"],
            outputs=["iteration_complete"],
        )
        @runner.phase("after_each")
        def after_each(ctx: Any) -> None:
            ctx.log(f"Closed this bounded {self.title.lower()}")

        @graph.step(
            finalize_id,
            title=f"Finalize {self.title.lower()} evaluation",
            phase="after_all",
            inputs=["iteration_complete"],
            outputs=["final_status"],
        )
        @runner.phase("after_all")
        def after_all(ctx: Any) -> None:
            ctx.log(f"Finalized the {self.title.lower()} evaluation")


@dataclass(frozen=True)
class JsonActionCycle:
    """Run a bounded external JSON action contract through the standard cycle."""

    command_env: str
    namespace: str
    title: str
    actions: tuple[str, str, str, str] = ("status", "prepare", "run-once", "collect-evidence")
    payload_key: str = "test_cases"

    def install(self) -> None:
        import orbit_sdk

        graph, runner = orbit_sdk.graph, orbit_sdk.runner
        prefix = self.namespace.replace("_", "-")
        ids = (
            f"preflight-{prefix}",
            f"prepare-{prefix}",
            f"run-{prefix}",
            f"collect-{prefix}",
            f"close-{prefix}",
            f"finalize-{prefix}",
        )
        graph.connect(ids[0], ids[1])
        graph.connect(ids[1], ids[2], label="prepared inputs")
        graph.connect(ids[2], ids[3], kind="data", label="action result")
        graph.connect(ids[3], ids[4])
        graph.connect(ids[4], ids[1], kind="loop", label="next cycle")
        graph.connect(ids[4], ids[5], kind="condition", label="completed")

        def invoke(ctx: Any, action: str) -> dict[str, Any]:
            configured = os.environ.get(self.command_env, "").strip()
            if not configured:
                raise ValueError(f"Set {self.command_env} to an external tool command")
            command = json.loads(configured) if configured.startswith("[") else shlex.split(configured)
            if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
                raise ValueError(f"{self.command_env} must be a JSON string array or command")
            payload = json.dumps(
                {
                    "action": action,
                    "iteration": ctx.loop_index,
                    "build": ctx.build,
                    self.payload_key: ctx.test_cases,
                },
                ensure_ascii=False,
            )
            output = ctx.exec(
                [*command, action],
                cwd=ctx.project_root,
                timeout=3600,
                env={"ORBIT_CYCLE_INPUT": payload},
                target_log_source=self.namespace.replace("_", "-"),
            )
            try:
                result = json.loads(output)
            except json.JSONDecodeError as error:
                raise RuntimeError(f"Action {action!r} did not return JSON") from error
            if not isinstance(result, dict):
                raise RuntimeError(f"Action {action!r} must return a JSON object")
            return result

        @graph.step(ids[0], title=f"Preflight {self.title.lower()}", phase="before_all", outputs=["contract"])
        @runner.phase("before_all")
        def before_all(ctx: Any) -> None:
            RunnerRequirements(require_test_cases=True).validate(ctx)
            ctx.emit_result({self.namespace: {"preflight": invoke(ctx, self.actions[0])}})

        @graph.step(
            ids[1],
            title=f"Prepare {self.title.lower()}",
            phase="before_each",
            inputs=["contract"],
            outputs=["prepared"],
        )
        @runner.phase("before_each")
        def before_each(ctx: Any) -> None:
            ctx.emit_result(
                {self.namespace: {"iteration": ctx.loop_index, "prepared": invoke(ctx, self.actions[1])}}
            )

        @graph.step(
            ids[2],
            title=f"Run {self.title.lower()}",
            phase="execute",
            inputs=["prepared"],
            outputs=["result"],
        )
        @runner.phase("execute")
        def execute(ctx: Any) -> None:
            ctx.emit_result(
                {self.namespace: {"iteration": ctx.loop_index, "result": invoke(ctx, self.actions[2])}}
            )

        @graph.step(
            ids[3],
            title=f"Collect {self.title.lower()} evidence",
            phase="verify",
            inputs=["result"],
            outputs=["evidence"],
        )
        @runner.phase("verify")
        def verify(ctx: Any) -> None:
            ctx.emit_result(
                {self.namespace: {"iteration": ctx.loop_index, "evidence": invoke(ctx, self.actions[3])}}
            )

        @graph.step(
            ids[4],
            title=f"Close {self.title.lower()} cycle",
            phase="after_each",
            inputs=["evidence"],
            outputs=["complete"],
        )
        @runner.phase("after_each")
        def after_each(ctx: Any) -> None:
            ctx.log(f"Completed one bounded {self.title.lower()} cycle")

        @graph.step(
            ids[5],
            title=f"Finalize {self.title.lower()}",
            phase="after_all",
            inputs=["complete"],
            outputs=["final"],
        )
        @runner.phase("after_all")
        def after_all(ctx: Any) -> None:
            ctx.log(f"Finalized the {self.title.lower()}")


@dataclass(frozen=True)
class CommandActionCycle:
    """Standard lifecycle for external tools whose output need not be JSON."""

    command_env: str
    namespace: str = "external_adapter"

    def install(self) -> None:
        import orbit_sdk

        graph, runner = orbit_sdk.graph, orbit_sdk.runner
        ids = (
            "check-adapter",
            "prepare-adapter",
            "run-adapter",
            "collect-adapter-evidence",
            "close-adapter-cycle",
            "finalize-adapter",
        )
        for source, target, kwargs in (
            (ids[0], ids[1], {}),
            (ids[1], ids[2], {"label": "prepared target"}),
            (ids[2], ids[3], {"kind": "data", "label": "adapter output"}),
            (ids[3], ids[4], {}),
            (ids[4], ids[1], {"kind": "loop", "label": "next cycle"}),
            (ids[4], ids[5], {"kind": "condition", "label": "completed"}),
        ):
            graph.connect(source, target, **kwargs)

        def invoke(ctx: Any, action: str) -> str:
            raw = os.environ.get(self.command_env, "").strip()
            if not raw:
                raise ValueError(f"Set {self.command_env} to an external tool command")
            command = json.loads(raw) if raw.startswith("[") else shlex.split(raw)
            return ctx.exec(
                [*command, action],
                cwd=ctx.project_root,
                timeout=3600,
                target_log_source=self.namespace.replace("_", "-"),
            )

        def phase(phase_name: str, node: str, title: str, key: str, action: str, inputs=(), outputs=()):
            @graph.step(node, title=title, phase=phase_name, inputs=inputs, outputs=outputs)
            @runner.phase(phase_name)
            def handler(ctx: Any) -> None:
                ctx.emit_result({self.namespace: {key: invoke(ctx, action), "iteration": ctx.loop_index}})

        phase("before_all", ids[0], "Check adapter readiness", "status", "status", outputs=["adapter_status"])
        phase(
            "before_each",
            ids[1],
            "Prepare adapter cycle",
            "prepared",
            "prepare",
            inputs=["adapter_status"],
            outputs=["prepared_target"],
        )
        phase(
            "execute",
            ids[2],
            "Run bounded adapter task",
            "result",
            "run-once",
            inputs=["prepared_target"],
            outputs=["adapter_result"],
        )
        phase(
            "verify",
            ids[3],
            "Collect adapter evidence",
            "evidence",
            "collect-evidence",
            inputs=["adapter_result"],
            outputs=["adapter_evidence"],
        )

        @graph.step(
            ids[4],
            title="Close adapter cycle",
            phase="after_each",
            inputs=["adapter_evidence"],
            outputs=["cycle_complete"],
        )
        @runner.phase("after_each")
        def after_each(ctx: Any) -> None:
            ctx.log("Completed one bounded external adapter cycle")

        @graph.step(
            ids[5],
            title="Finalize external automation",
            phase="after_all",
            inputs=["cycle_complete"],
            outputs=["final_status"],
        )
        @runner.phase("after_all")
        def after_all(ctx: Any) -> None:
            ctx.log("Finalized the external automation evaluation")


@dataclass(frozen=True)
class BrowserSmokeTest:
    """Install a one-shot browser journey with evidence and a failure gate."""

    namespace: str = "browser_smoke"

    def install(self) -> None:
        import orbit_sdk

        graph, runner = orbit_sdk.graph, orbit_sdk.runner
        ids = (
            "validate-browser",
            "run-browser-journey",
            "verify-browser-evidence",
            "finalize-browser-evaluation",
        )
        graph.connect(ids[0], ids[1])
        graph.connect(ids[1], ids[2], kind="data", label="journey evidence")
        graph.connect(ids[2], ids[3])

        @graph.step(ids[0], title="Validate browser target", phase="before_all", outputs=["browser_target"])
        @runner.phase("before_all")
        def before_all(ctx: Any) -> None:
            RunnerRequirements(build_fields=("browser_base_url",), require_test_cases=True).validate(ctx)

        @graph.step(
            ids[1],
            title="Run browser journey",
            phase="execute",
            inputs=["browser_target"],
            outputs=["journey_evidence"],
        )
        @runner.phase("execute")
        def execute(ctx: Any) -> None:
            evidence = ctx.playwright_journey()
            ctx.emit_result({self.namespace: {"iteration": ctx.loop_index, "evidence": evidence}})
            if not all(item.get("passed") for item in evidence.get("results", [])):
                raise SystemExit("A browser journey failed")

        @graph.step(
            ids[2],
            title="Verify journey evidence",
            phase="verify",
            inputs=["journey_evidence"],
            outputs=["journey_verdict"],
        )
        @runner.phase("verify")
        def verify(ctx: Any) -> None:
            ctx.log("Quick start browser evaluation completed")

        @graph.step(
            ids[3],
            title="Finalize browser evaluation",
            phase="after_all",
            inputs=["journey_verdict"],
            outputs=["completed_evaluation"],
        )
        @runner.phase("after_all")
        def after_all(ctx: Any) -> None:
            ctx.log("Finalized the one-shot browser evaluation")


@dataclass(frozen=True)
class SiteExplorationReview:
    """Safely explore same-origin pages and retain rendered review evidence."""

    max_clicks: int = 3

    def install(self) -> None:
        import orbit_sdk

        graph, runner = orbit_sdk.graph, orbit_sdk.runner
        graph.connect("validate-site", "explore-site")
        graph.connect("explore-site", "review-evidence", kind="data", label="rendered pages")
        graph.connect("review-evidence", "finalize-review")

        @graph.step("validate-site", title="Validate site", phase="before_all", outputs=["site_target"])
        @runner.phase("before_all")
        def before_all(ctx: Any) -> None:
            RunnerRequirements(build_fields=("browser_base_url",)).validate(ctx)

        @graph.step(
            "explore-site",
            title="Explore rendered site",
            phase="execute",
            inputs=["site_target"],
            outputs=["rendered_pages"],
        )
        @runner.phase("execute")
        def execute(ctx: Any) -> None:
            module = str(
                __import__("pathlib").Path(orbit_sdk.__file__).resolve().parents[1]
                / "frontend"
                / "node_modules"
                / "playwright"
            )
            screenshot = (
                ctx.app_data
                / "artifacts"
                / ctx.environment.get("ORBIT_RUN_ID", "manual")
                / f"loop-{ctx.loop_index}"
                / "site-exploration.png"
            )
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            script = """const {chromium}=require(process.argv[1]),i=JSON.parse(process.argv[2]),blocked=/(logout|signout|delete|remove|destroy|payment|checkout|purchase|upgrade|unsubscribe)/i;(async()=>{const b=await chromium.launch({headless:true}),p=await b.newPage(),v=[],o=new URL(i.baseUrl).origin;try{await p.goto(i.baseUrl,{waitUntil:'domcontentloaded',timeout:30000});for(let n=0;n<=i.maxClicks;n++){v.push({url:p.url(),title:await p.title(),text:(await p.locator('body').innerText().catch(()=>'' )).replace(/\\s+/g,' ').slice(0,1200)});if(n===i.maxClicks)break;const a=await p.locator('a[href]').evaluateAll(x=>x.map((e,k)=>({k,href:e.href,text:(e.textContent||'').trim()})));const c=a.filter(x=>{try{return new URL(x.href).origin===o&&!blocked.test(new URL(x.href).pathname+' '+x.text)}catch{return false}});if(!c.length)break;await p.locator('a[href]').nth(c[n%c.length].k).click({timeout:5000});await p.waitForLoadState('domcontentloaded',{timeout:10000}).catch(()=>{})}await p.screenshot({path:i.screenshot,fullPage:true});console.log('__ORBIT_SITE_EXPLORATION_RESULT__'+JSON.stringify({visited:v,screenshot:i.screenshot}))}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)})"""
            output = ctx.exec(
                [
                    "node",
                    "-e",
                    script,
                    module,
                    json.dumps(
                        {
                            "baseUrl": ctx.build["browser_base_url"],
                            "maxClicks": self.max_clicks,
                            "screenshot": str(screenshot),
                        }
                    ),
                ],
                timeout=120,
                target_log_source="site-exploration",
                target_log_exclude_prefixes=("__ORBIT_SITE_EXPLORATION_RESULT__",),
            )
            payload = next(
                (
                    line.removeprefix("__ORBIT_SITE_EXPLORATION_RESULT__")
                    for line in reversed(output.splitlines())
                    if line.startswith("__ORBIT_SITE_EXPLORATION_RESULT__")
                ),
                "",
            )
            if not payload:
                raise RuntimeError("site exploration did not return structured evidence")
            evidence = json.loads(payload)
            titles = [str(page.get("title") or page.get("url")) for page in evidence.get("visited", [])]
            ctx.emit_result(
                {
                    "site_exploration": {
                        "evidence": evidence,
                        "opinion": f"Explored {len(titles)} rendered page(s): {'; '.join(titles[:3])}. Review the captured pages for clarity, usefulness, and friction.",
                    }
                }
            )

        @graph.step(
            "review-evidence",
            title="Review exploration evidence",
            phase="verify",
            inputs=["rendered_pages"],
            outputs=["product_review"],
        )
        @runner.phase("verify")
        def verify(ctx: Any) -> None:
            ctx.log("Retained rendered exploration evidence for review")

        @graph.step(
            "finalize-review",
            title="Finalize site review",
            phase="after_all",
            inputs=["product_review"],
            outputs=["completed_review"],
        )
        @runner.phase("after_all")
        def after_all(ctx: Any) -> None:
            ctx.log("Finalized the bounded site exploration review")


@dataclass(frozen=True)
class InsightaPersonaCycle:
    """Install Insighta's source-backed persona lifecycle around a simulator.

    The simulator and its product policy remain in the private Insighta bundle;
    this recipe owns only OpenOrbit lifecycle registration and evidence flow.
    """

    simulator: Any
    required_cases: set[str]
    ensure_dependencies: Any = lambda: None

    def install(self) -> None:
        from insighta_persona.phases.lifecycle import register

        register(
            simulator=self.simulator,
            ensure_dependencies=self.ensure_dependencies,
            required_cases=self.required_cases,
        )
