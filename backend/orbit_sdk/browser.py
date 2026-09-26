"""Reusable browser-readiness primitives for runner-owned Selenium sessions.

The SDK deliberately does not import Selenium.  Any WebDriver-compatible
object with CDP and JavaScript execution methods can use these helpers.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable

DEFAULT_IGNORED_URL_PATTERNS = (
    r"analytics",
    r"telemetry",
    r"sentry",
    r"/ingest(?:/|$)",
    r"/vitals(?:/|$)",
    r"/logs?(?:/|$)",
)


@dataclass(frozen=True)
class NetworkSettleOptions:
    """Bounded readiness policy used before browser evidence is captured."""

    quiet_window_seconds: float = 1.25
    stability_seconds: float = 5.0
    timeout_seconds: float = 35.0
    poll_interval_seconds: float = 0.25
    loading_text_pattern: str = r"\\bloading(?:\\.\\.\\.|…)?\\b"
    ignored_url_patterns: tuple[str, ...] = DEFAULT_IGNORED_URL_PATTERNS


def _tracker_script(ignored_url_patterns: Iterable[str]) -> str:
    """Build an idempotent preload script that counts relevant fetch/XHR work."""
    patterns = json.dumps(list(ignored_url_patterns))
    return f"""
(() => {{
  if (window.__orbitNetworkTracker) return;
  const ignored = new RegExp(({patterns}).join('|'), 'i');
  const tracker = window.__orbitNetworkTracker = {{ pending: 0, lastActivity: Date.now() }};
  const relevant = value => {{
    try {{ return !ignored.test(typeof value === 'string' ? value : (value && value.url) || ''); }}
    catch (_) {{ return true; }}
  }};
  const start = () => {{ tracker.pending += 1; tracker.lastActivity = Date.now(); }};
  const finish = () => {{ tracker.pending = Math.max(0, tracker.pending - 1); tracker.lastActivity = Date.now(); }};
  const originalFetch = window.fetch;
  if (originalFetch) window.fetch = function (...args) {{
    if (!relevant(args[0])) return originalFetch.apply(this, args);
    start();
    try {{ return Promise.resolve(originalFetch.apply(this, args)).finally(finish); }}
    catch (error) {{ finish(); throw error; }}
  }};
  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {{
    this.__orbitRelevantRequest = relevant(url);
    return originalOpen.call(this, method, url, ...rest);
  }};
  XMLHttpRequest.prototype.send = function (...args) {{
    if (this.__orbitRelevantRequest) {{
      start();
      this.addEventListener('loadend', finish, {{ once: true }});
    }}
    return originalSend.apply(this, args);
  }};
}})();
"""


def install_selenium_network_tracker(
    driver: Any, *, ignored_url_patterns: Iterable[str] = DEFAULT_IGNORED_URL_PATTERNS
) -> None:
    """Install request tracking before navigation in a Selenium browser session.

    WebSocket and EventSource traffic are not patched.  This avoids treating
    intentionally long-lived connections as page-load work.
    """
    script = _tracker_script(ignored_url_patterns)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
    # Also make the tracker available if the caller installs it after a page
    # has already been opened.  The preload registration handles future pages.
    driver.execute_script(script)


def wait_for_selenium_page_settlement(
    driver: Any,
    *,
    label: str = "page",
    options: NetworkSettleOptions = NetworkSettleOptions(),
) -> dict[str, Any]:
    """Wait for request quietness, loading disappearance, and visual stability.

    A fresh request or a visible loading marker restarts the stability clock.
    The returned timeout result is evidence, not a successful readiness claim.
    """
    if (
        min(
            options.quiet_window_seconds,
            options.stability_seconds,
            options.timeout_seconds,
            options.poll_interval_seconds,
        )
        <= 0
    ):
        raise ValueError("network-settlement durations must be positive")
    pattern = json.dumps(options.loading_text_pattern)
    observe_script = f"""
const visible = element => !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
const loading = document.body && [...document.querySelectorAll('body *')].some(element =>
  visible(element) && new RegExp({pattern}, 'i').test((element.textContent || '').trim())
);
const tracker = window.__orbitNetworkTracker;
return {{
  pending: tracker ? Number(tracker.pending || 0) : 0,
  quiet_for_ms: tracker ? Date.now() - Number(tracker.lastActivity || Date.now()) : 0,
  loading_visible: Boolean(loading),
  tracker_available: Boolean(tracker),
}};
"""
    deadline = time.monotonic() + options.timeout_seconds
    stable_since: float | None = None
    state: dict[str, Any] = {}
    while True:
        raw = driver.execute_script(observe_script)
        state = raw if isinstance(raw, dict) else {}
        idle = (
            bool(state.get("tracker_available"))
            and int(state.get("pending", 0)) == 0
            and float(state.get("quiet_for_ms", 0)) >= options.quiet_window_seconds * 1000
            and not bool(state.get("loading_visible"))
        )
        now = time.monotonic()
        if idle:
            stable_since = stable_since or now
            if now - stable_since >= options.stability_seconds:
                return {"status": "ready", "label": label, "options": asdict(options), "network": state}
        else:
            stable_since = None
        if now >= deadline:
            reason = "loading_visible" if state.get("loading_visible") else "network_not_idle"
            return {
                "status": "timeout",
                "label": label,
                "reason": reason,
                "options": asdict(options),
                "network": state,
            }
        time.sleep(options.poll_interval_seconds)
