"""Safe, dependency-free local SupportOps fixture for OpenOrbit examples."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import perf_counter
from urllib.parse import urlparse

TICKETS = [
    {"id": "DEMO-101", "subject": "Invoice copy", "status": "open", "priority": "normal"},
    {"id": "DEMO-102", "subject": "Refund question", "status": "pending", "priority": "high"},
]


def support_reply(message: str) -> dict[str, object]:
    text = message.lower()
    if any(word in text for word in ("ignore", "system prompt", "secret")):
        return {"answer": "I cannot reveal internal instructions or secrets.", "safe": True, "grounded": True}
    if "refund" in text:
        answer = "Refunds are available within 30 days and require payment-team review."
        if os.environ.get("DEMO_DRIFT") == "quality":
            answer = "Your refund is approved."
        return {"answer": answer, "safe": True, "grounded": os.environ.get("DEMO_DRIFT") != "quality"}
    return {
        "answer": "I can help with invoices, refund policy, or creating a support ticket.",
        "safe": True,
        "grounded": True,
    }


class Handler(BaseHTTPRequestHandler):
    def _json(self, body: object, status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _body(self) -> dict[str, object]:
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            return self._json({"status": "ok", "service": "supportops-demo"})
        if path == "/api/tickets":
            return self._json({"tickets": TICKETS})
        if path == "/api/metrics":
            return self._json({"quality_target": 0.9, "safety_target": 1.0, "p95_latency_ms": 800})
        if path != "/":
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        page = PAGE.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def do_POST(self) -> None:  # noqa: N802
        path, body = urlparse(self.path).path, self._body()
        if path == "/api/assistant":
            started = perf_counter()
            response = support_reply(str(body.get("message", "")))
            response["latency_ms"] = round((perf_counter() - started) * 1000, 2)
            return self._json(response)
        if path == "/api/tickets":
            ticket = {
                "id": f"DEMO-{103 + len(TICKETS)}",
                "subject": str(body.get("subject", "Untitled")),
                "status": "open",
                "priority": "normal",
            }
            TICKETS.append(ticket)
            return self._json(ticket, HTTPStatus.CREATED)
        return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, _format: str, *_args: object) -> None:
        return


PAGE = """<!doctype html><title>SupportOps demo</title><style>body{max-width:760px;margin:40px auto;font:16px system-ui}input,button{padding:8px;margin:4px}pre{background:#f4f4f4;padding:12px}</style><h1>SupportOps demo</h1><p>Local-only synthetic support fixture.</p><input id=m value='What is the refund policy?'><button onclick='ask()'>Ask</button><pre id=o>Waiting.</pre><script>async function ask(){let r=await fetch('/api/assistant',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m.value})});o.textContent=JSON.stringify(await r.json(),null,2)}</script>"""


if __name__ == "__main__":
    print("SupportOps demo listening only on http://127.0.0.1:4174")
    ThreadingHTTPServer(("127.0.0.1", 4174), Handler).serve_forever()
