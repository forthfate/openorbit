"""Explore a site safely and retain rendered product-review evidence.

The embedded browser script follows only bounded same-origin links and excludes
destructive actions. Its structured output is evidence for supervision, not an
automatic product change.
"""

import json
from pathlib import Path

import orbit_sdk
from orbit_sdk import graph, runner

graph.connect("validate-site", "explore-site")
graph.connect("explore-site", "review-evidence", kind="data", label="rendered pages")
graph.connect("review-evidence", "finalize-review")


@graph.step("validate-site", title="Validate site", phase="before_all", outputs=["site_target"])
@runner.phase("before_all", step_id="validate-site")
def validate_site(ctx):
    """Validate the browser target before safely exploring it."""
    if not ctx.build.get("browser_base_url"):
        raise ValueError("Set required build field(s): browser_base_url")
    if not ctx.test_cases:
        raise ValueError("Select at least one fixed journey case before running this runner")


@graph.step(
    "explore-site",
    title="Explore rendered site",
    phase="execute",
    inputs=["site_target"],
    outputs=["rendered_pages"],
)
@runner.phase("execute", step_id="explore-site")
def explore_site(ctx):
    """Visit a bounded number of safe same-origin links.

    The embedded Playwright script excludes destructive paths and emits one
    machine-readable evidence record after collecting rendered page content.
    """
    module = str(Path(orbit_sdk.__file__).resolve().parents[2] / "frontend" / "node_modules" / "playwright")
    screenshot = (
        ctx.app_data
        / "artifacts"
        / ctx.environment.get("ORBIT_RUN_ID", "manual")
        / f"loop-{ctx.loop_index}"
        / "site-exploration.png"
    )
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    script = """const {chromium}=require(process.argv[1]),i=JSON.parse(process.argv[2]),blocked=/(logout|signout|delete|remove|destroy|payment|checkout|purchase|upgrade|unsubscribe)/i;(async()=>{const b=await chromium.launch({headless:true}),p=await b.newPage(),v=[],seen=new Set(),o=new URL(i.baseUrl).origin;try{await p.goto(i.baseUrl,{waitUntil:'domcontentloaded',timeout:30000});for(let n=0;n<=i.maxClicks;n++){seen.add(p.url());v.push({url:p.url(),title:await p.title(),text:(await p.locator('body').innerText().catch(()=>'' )).replace(/\\s+/g,' ').slice(0,1200)});if(n===i.maxClicks)break;const a=await p.locator('a[href]').evaluateAll(x=>x.map((e,k)=>({k,href:e.href,text:(e.textContent||'').trim()})));const c=a.filter(x=>{try{const u=new URL(x.href);return u.origin===o&&!seen.has(u.href)&&!blocked.test(u.pathname+' '+x.text)}catch{return false}});if(!c.length)break;await p.locator('a[href]').nth(c[0].k).click({timeout:5000});await p.waitForLoadState('domcontentloaded',{timeout:10000}).catch(()=>{})}await p.screenshot({path:i.screenshot,fullPage:true});console.log('__ORBIT_SITE_EXPLORATION_RESULT__'+JSON.stringify({visited:v,screenshot:i.screenshot}))}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)})"""
    output = ctx.exec(
        [
            "node",
            "-e",
            script,
            module,
            json.dumps(
                {"baseUrl": ctx.build["browser_base_url"], "maxClicks": 3, "screenshot": str(screenshot)}
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
@runner.phase("verify", step_id="review-evidence")
def verify(ctx):
    """Keep the rendered exploration evidence available to the supervisor."""
    ctx.log("Retained rendered exploration evidence for review")


@graph.step(
    "finalize-review",
    title="Finalize site review",
    phase="after_all",
    inputs=["product_review"],
    outputs=["completed_review"],
)
@runner.phase("after_all", step_id="finalize-review")
def after_all(ctx):
    """Finalize the bounded site exploration review."""
    ctx.log("Finalized the bounded site exploration review")


if __name__ == "__main__":
    runner.main()
