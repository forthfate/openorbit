# Requirements
# - The target application is running at the build's browser base URL.
# - Playwright Chromium and LangGraph are available.
# This runner follows only same-site links and excludes destructive-looking routes.

import json
from pathlib import Path
from typing import TypedDict

import orbit_sdk
from langgraph.graph import END, START, StateGraph
from orbit_sdk import graph as orbit_graph
from orbit_sdk import runner

orbit_graph.connect("validate-site", "explore-site")
orbit_graph.connect("explore-site", "review-evidence", kind="data", label="rendered pages")
orbit_graph.connect("review-evidence", "finalize-review")


class ExplorerState(TypedDict, total=False):
    base_url: str
    max_clicks: int
    evidence: dict
    opinion: str


def explore_browser(ctx, state):
    module = str(Path(orbit_sdk.__file__).resolve().parents[1] / "frontend" / "node_modules" / "playwright")
    artifacts = (
        ctx.app_data / "artifacts" / ctx.environment.get("ORBIT_RUN_ID", "manual") / f"loop-{ctx.loop_index}"
    )
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = {
        "baseUrl": state["base_url"],
        "maxClicks": state["max_clicks"],
        "screenshot": str(artifacts / "site-exploration.png"),
    }
    script = r"""const { chromium } = require(process.argv[1]); const input = JSON.parse(process.argv[2]);
const blocked = /(logout|signout|delete|remove|destroy|payment|checkout|purchase|upgrade|unsubscribe)/i;
(async () => { const browser = await chromium.launch({headless:true}); const page = await browser.newPage(); const visited = []; const origin = new URL(input.baseUrl).origin;
  try { await page.goto(input.baseUrl, {waitUntil:"domcontentloaded", timeout:30000});
    for (let step = 0; step <= input.maxClicks; step++) { const text = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 1200); visited.push({url:page.url(), title:await page.title(), text});
      if (step === input.maxClicks) break;
      const links = await page.locator("a[href]").evaluateAll(items => items.map((item, index) => ({index, href:item.href, text:(item.textContent || "").trim()})).filter(item => item.href));
      const candidates = links.filter(item => { try { const url = new URL(item.href); return url.origin === origin && !blocked.test(url.pathname + " " + item.text); } catch { return false; } });
      if (!candidates.length) break; const target = candidates[step % candidates.length]; await page.locator("a[href]").nth(target.index).click({timeout:5000}); await page.waitForLoadState("domcontentloaded", {timeout:10000}).catch(() => {}); await page.waitForTimeout(300);
    }
    await page.screenshot({path:input.screenshot, fullPage:true}); console.log(`site exploration completed: ${visited.length} page(s)`); console.log('__ORBIT_SITE_EXPLORATION_RESULT__'+JSON.stringify({visited, screenshot:input.screenshot}));
  } finally { await browser.close(); } })().catch(error => { console.error(error); process.exit(1); });"""
    output = ctx.exec(
        ["node", "-e", script, module, json.dumps(payload)],
        timeout=120,
        target_log_source="site-exploration",
        target_log_exclude_prefixes=("__ORBIT_SITE_EXPLORATION_RESULT__",),
    )
    result = next(
        (
            line.removeprefix("__ORBIT_SITE_EXPLORATION_RESULT__")
            for line in reversed(output.splitlines())
            if line.startswith("__ORBIT_SITE_EXPLORATION_RESULT__")
        ),
        "",
    )
    if not result:
        raise RuntimeError("site exploration did not return structured evidence")
    return json.loads(result)


def form_opinion(state):
    pages = state["evidence"].get("visited", [])
    titles = [str(page.get("title") or page.get("url")) for page in pages]
    return {
        "opinion": f"Explored {len(pages)} rendered page(s): "
        + "; ".join(titles[:3])
        + ". Review the captured pages for clarity, usefulness, and friction."
    }


def graph(ctx):
    workflow = StateGraph(ExplorerState)
    workflow.add_node("explore", lambda state: {"evidence": explore_browser(ctx, state)})
    workflow.add_node("form_opinion", form_opinion)
    workflow.add_edge(START, "explore")
    workflow.add_edge("explore", "form_opinion")
    workflow.add_edge("form_opinion", END)
    return workflow.compile()


@orbit_graph.step("validate-site", title="Validate site", phase="before_all", outputs=["site_target"])
@runner.phase("before_all")
def before_all(ctx):
    if not ctx.build.get("browser_base_url"):
        raise ValueError("Set a browser base URL before exploring a site")


@orbit_graph.step(
    "explore-site",
    title="Explore rendered site",
    phase="execute",
    inputs=["site_target"],
    outputs=["rendered_pages"],
)
@runner.phase("execute")
def execute(ctx):
    result = graph(ctx).invoke({"base_url": ctx.build["browser_base_url"], "max_clicks": 3})
    ctx.emit_result({"site_exploration": {"opinion": result["opinion"], "evidence": result["evidence"]}})


@orbit_graph.step(
    "review-evidence",
    title="Review exploration evidence",
    phase="verify",
    inputs=["rendered_pages"],
    outputs=["product_review"],
)
@runner.phase("verify")
def verify(ctx):
    ctx.log("Retained rendered exploration evidence for review")


@orbit_graph.step(
    "finalize-review",
    title="Finalize site review",
    phase="after_all",
    inputs=["product_review"],
    outputs=["completed_review"],
)
@runner.phase("after_all")
def after_all(ctx):
    ctx.log("Finalized the bounded site exploration review")


if __name__ == "__main__":
    runner.main()
