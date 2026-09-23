"""Browser and source-contract operations shared by built-in runner assets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ..decorators.visual import visual_node


@visual_node(
    kind="run_browser_smoke",
    group_key="browser",
    display_name="Run browser smoke journey",
    title_key="visual.nodes.runBrowserSmoke.title",
    description_key="visual.nodes.runBrowserSmoke.description",
    default_config={"namespace": "browser_smoke", "fail_on_unpassed": True},
    default_outputs=("journey_evidence",),
)
def run_browser_smoke(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Run fixed browser cases and retain the exact smoke-test evidence envelope."""
    evidence = ctx.playwright_journey()
    namespace = str(config.get("namespace", "browser_smoke"))
    ctx.emit_result({namespace: {"iteration": ctx.loop_index, "evidence": evidence}})
    if config.get("fail_on_unpassed", True) and not all(
        item.get("passed") for item in evidence.get("results", [])
    ):
        raise SystemExit("A browser journey failed")
    return {"journey_evidence": evidence}


@visual_node(
    kind="validate_source_contract",
    group_key="browser",
    display_name="Validate source contract",
    title_key="visual.nodes.validateSourceContract.title",
    description_key="visual.nodes.validateSourceContract.description",
    default_config={
        "namespace": "source_aware_journey",
        "pattern_env": "ORBIT_SOURCE_CONTRACT_PATTERN",
        "glob_env": "ORBIT_SOURCE_CONTRACT_GLOB",
    },
    default_outputs=("source_contract",),
)
def validate_source_contract(
    ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]
) -> dict[str, object]:
    """Collect bounded source matches and validate browser inputs for a journey."""
    if not ctx.build.get("browser_base_url") or not ctx.test_cases:
        raise ValueError("A browser base URL and at least one fixed journey case are required")
    pattern = str(ctx.environment.get(config.get("pattern_env", "ORBIT_SOURCE_CONTRACT_PATTERN"), "")).strip()
    if not pattern:
        raise ValueError("Set ORBIT_SOURCE_CONTRACT_PATTERN to a required source expression")
    glob = str(ctx.environment.get(config.get("glob_env", "ORBIT_SOURCE_CONTRACT_GLOB"), "")).strip()
    command = ["rg", "-l", pattern]
    if glob:
        command.extend(["--glob", glob])
    command.append(".")
    output = ctx.exec(command, cwd=ctx.project_root, timeout=30)
    files = [path for path in output.splitlines() if path][:40]
    if not files:
        raise ValueError("The configured source contract was not found in the target project")
    contract = {"pattern": pattern, "glob": glob or None, "files": files}
    namespace = str(config.get("namespace", "source_aware_journey"))
    ctx.emit_result({namespace: {"source_contract": contract}})
    ctx.log(f"Validated source contract in {len(files)} file(s)")
    return {"source_contract": contract}


@visual_node(
    kind="validate_tailwind_source",
    group_key="browser",
    display_name="Validate Tailwind source",
    title_key="visual.nodes.validateSourceContract.title",
    description_key="visual.nodes.validateSourceContract.description",
    default_outputs=("source_contract",),
)
def validate_tailwind_source(ctx: Any, _: Mapping[str, Any], __: Mapping[str, object]) -> dict[str, object]:
    """Require Tailwind source evidence together with a runnable browser journey."""
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
    contract = {"stylesheet_files": files.splitlines()[:40], "config_files": config.splitlines()[:20]}
    ctx.emit_result({"tailwind_journey": contract})
    ctx.log("Validated the Tailwind source contract")
    return {"source_contract": contract}


@visual_node(
    kind="run_source_aware_browser_journey",
    group_key="browser",
    display_name="Run source-aware browser journey",
    title_key="visual.nodes.runSourceAwareBrowserJourney.title",
    description_key="visual.nodes.runSourceAwareBrowserJourney.description",
    default_config={"namespace": "source_aware_journey"},
    default_outputs=("browser_evidence",),
)
def run_source_aware_browser_journey(
    ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]
) -> dict[str, object]:
    """Run rendered evidence independently from the source-side contract."""
    evidence = ctx.playwright_journey()
    namespace = str(config.get("namespace", "source_aware_journey"))
    ctx.emit_result({namespace: {"iteration": ctx.loop_index, "evidence": evidence}})
    artifact = ctx.save_data_file(
        f"source-aware-journey/iteration-{ctx.loop_index}.json",
        json.dumps(evidence, ensure_ascii=False, indent=2),
        label="Source-aware rendered journey evidence",
        content_type="application/json",
    )
    return {"browser_evidence": evidence, "artifact": artifact}


_SITE_SCRIPT = """const {chromium}=require(process.argv[1]),i=JSON.parse(process.argv[2]),blocked=/(logout|signout|delete|remove|destroy|payment|checkout|purchase|upgrade|unsubscribe)/i;(async()=>{const b=await chromium.launch({headless:true}),p=await b.newPage(),v=[],seen=new Set(),o=new URL(i.baseUrl).origin;try{await p.goto(i.baseUrl,{waitUntil:'domcontentloaded',timeout:30000});for(let n=0;n<=i.maxClicks;n++){seen.add(p.url());v.push({url:p.url(),title:await p.title(),text:(await p.locator('body').innerText().catch(()=>'' )).replace(/\\s+/g,' ').slice(0,1200)});if(n===i.maxClicks)break;const a=await p.locator('a[href]').evaluateAll(x=>x.map((e,k)=>({k,href:e.href,text:(e.textContent||'').trim()})));const c=a.filter(x=>{try{const u=new URL(x.href);return u.origin===o&&!seen.has(u.href)&&!blocked.test(u.pathname+' '+x.text)}catch{return false}});if(!c.length)break;await p.locator('a[href]').nth(c[0].k).click({timeout:5000});await p.waitForLoadState('domcontentloaded',{timeout:10000}).catch(()=>{})}await p.screenshot({path:i.screenshot,fullPage:true});console.log('__ORBIT_SITE_EXPLORATION_RESULT__'+JSON.stringify({visited:v,screenshot:i.screenshot}))}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)})"""


@visual_node(
    kind="explore_rendered_site",
    group_key="browser",
    display_name="Explore rendered site",
    title_key="visual.nodes.exploreRenderedSite.title",
    description_key="visual.nodes.exploreRenderedSite.description",
    default_config={"namespace": "site_exploration", "max_clicks": 3},
    default_outputs=("rendered_pages",),
)
def explore_rendered_site(ctx: Any, config: Mapping[str, Any], _: Mapping[str, object]) -> dict[str, object]:
    """Visit bounded safe same-origin links and retain rendered page evidence."""
    if not ctx.build.get("browser_base_url") or not ctx.test_cases:
        raise ValueError("Set required build field(s): browser_base_url and test cases")
    # The SDK package lives at backend/orbit_sdk; the checked-in frontend is at repository root.
    import orbit_sdk

    module = str(Path(orbit_sdk.__file__).resolve().parents[2] / "frontend" / "node_modules" / "playwright")
    screenshot = (
        ctx.app_data
        / "artifacts"
        / ctx.environment.get("ORBIT_RUN_ID", "manual")
        / f"loop-{ctx.loop_index}"
        / "site-exploration.png"
    )
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    output = ctx.exec(
        [
            "node",
            "-e",
            _SITE_SCRIPT,
            module,
            json.dumps(
                {
                    "baseUrl": ctx.build["browser_base_url"],
                    "maxClicks": config.get("max_clicks", 3),
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
    value = {
        "evidence": evidence,
        "opinion": f"Explored {len(titles)} rendered page(s): {'; '.join(titles[:3])}. Review the captured pages for clarity, usefulness, and friction.",
    }
    ctx.emit_result({str(config.get("namespace", "site_exploration")): value})
    return {"rendered_pages": value}
