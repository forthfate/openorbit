"""Command-line control for a running Orbit local control room."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from typing import Any


def request(base_url: str, path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    """Call the same local API used by the web UI."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    http_request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Orbit API returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Orbit API is unavailable at {base_url}: {error.reason}") from error


def show(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def wait_for_run(base_url: str, run_id: str, timeout_seconds: int) -> Any:
    """Wait for a bounded task execution without hiding approval requirements."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        run = request(base_url, f"/api/runs/{run_id}")
        if run["status"] in {"awaiting_approval", "succeeded", "failed", "cancelled"}:
            return run
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Timed out waiting for task run {run_id} after {timeout_seconds} seconds.")
        time.sleep(0.25)


def task_wait_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--wait", action="store_true", help="Wait for completion or an approval boundary.")
    command.add_argument(
        "--timeout", type=int, default=300, help="Maximum wait time in seconds (default: 300)."
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="orbit", description=__doc__)
    root.add_argument("--url", default=os.environ.get("ORBIT_URL", "http://127.0.0.1:8787"))
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Start the local OpenOrbit web server.")
    run.add_argument("--host", default=os.environ.get("ORBIT_HOST", "127.0.0.1"))
    run.add_argument("--port", type=int, default=int(os.environ.get("ORBIT_PORT", "3000")))
    run.add_argument("--reload", action="store_true", help="Reload the server when Python sources change.")
    run.add_argument("--open", action="store_true", help="Open the local control room in a browser.")
    commands.add_parser("dashboard")
    commands.add_parser("docker-status")
    commands.add_parser("telemetry")

    builds = commands.add_parser("builds")
    build_commands = builds.add_subparsers(dest="build_command", required=True)
    build_commands.add_parser("list")
    build_invoke = commands.add_parser("invoke")
    build_invoke.add_argument("build_id")

    runs = commands.add_parser("runs")
    run_commands = runs.add_subparsers(dest="run_command", required=True)
    run_commands.add_parser("list")
    start = run_commands.add_parser("start")
    start.add_argument("workflow_id")
    cancel = run_commands.add_parser("cancel")
    cancel.add_argument("run_id")
    run_commands.add_parser("emergency-stop")

    tasks = commands.add_parser("tasks", help="List, test, and run configured target tasks.")
    task_commands = tasks.add_subparsers(dest="task_command", required=True)
    task_commands.add_parser("list")
    task_run = task_commands.add_parser("run")
    task_run.add_argument("task_id")
    task_wait_options(task_run)
    task_test = task_commands.add_parser("test")
    task_test.add_argument("task_id")
    task_wait_options(task_test)
    task_status = task_commands.add_parser("status")
    task_status.add_argument("run_id")
    task_approve = task_commands.add_parser("approve")
    task_approve.add_argument("run_id")
    task_wait_options(task_approve)
    task_reject = task_commands.add_parser("reject")
    task_reject.add_argument("run_id")

    improvements = commands.add_parser("improvements")
    improvements.add_subparsers(dest="improvement_command", required=True).add_parser("list")

    settings = commands.add_parser("settings")
    setting_commands = settings.add_subparsers(dest="settings_command", required=True)
    setting_commands.add_parser("get")
    setting_commands.add_parser("hello")
    set_values = setting_commands.add_parser("set")
    set_values.add_argument("--provider", choices=["azure-openai", "aws-bedrock"])
    set_values.add_argument("--model")
    set_values.add_argument("--endpoint")
    set_values.add_argument("--region")
    set_values.add_argument("--secret-env")
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "run":
        if not 1 <= args.port <= 65535:
            print("error: --port must be an integer from 1 through 65535.", file=sys.stderr)
            raise SystemExit(2)
        if args.open:
            webbrowser.open(f"http://{args.host}:{args.port}")
        import uvicorn

        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
        return
    try:
        if args.command == "dashboard":
            show(request(args.url, "/api/dashboard"))
        elif args.command == "docker-status":
            show(request(args.url, "/api/docker/status"))
        elif args.command == "telemetry":
            show(request(args.url, "/api/telemetry"))
        elif args.command == "invoke":
            show(request(args.url, f"/api/evaluation-builds/{args.build_id}/runs", "POST"))
        elif args.command == "builds" and args.build_command == "list":
            show(request(args.url, "/api/evaluation-builds"))
        elif args.command == "improvements":
            show(request(args.url, "/api/improvements"))
        elif args.command == "tasks":
            if args.task_command == "list":
                show(request(args.url, "/api/tasks"))
            elif args.task_command == "status":
                show(request(args.url, f"/api/runs/{args.run_id}"))
            elif args.task_command == "reject":
                show(request(args.url, f"/api/runs/{args.run_id}/reject", "POST"))
            else:
                if args.task_command == "run":
                    run = request(args.url, f"/api/tasks/{args.task_id}/runs", "POST")
                elif args.task_command == "test":
                    run = request(args.url, f"/api/tasks/{args.task_id}/tests", "POST")
                else:
                    run = request(args.url, f"/api/runs/{args.run_id}/approve", "POST")
                if args.wait:
                    run = wait_for_run(args.url, run["id"], args.timeout)
                show(run)
                if run["status"] in {"failed", "cancelled"}:
                    raise SystemExit(1)
        elif args.command == "runs":
            if args.run_command == "list":
                show(request(args.url, "/api/runs"))
            elif args.run_command == "start":
                show(request(args.url, f"/api/workflows/{args.workflow_id}/runs", "POST"))
            elif args.run_command == "cancel":
                show(request(args.url, f"/api/runs/{args.run_id}/cancel", "POST"))
            else:
                show(request(args.url, "/api/runs/emergency-stop", "POST"))
        elif args.command == "settings":
            if args.settings_command == "get":
                show(request(args.url, "/api/settings"))
            elif args.settings_command == "hello":
                show(request(args.url, "/api/settings/hello", "POST"))
            else:
                current = request(args.url, "/api/settings")
                updates = {
                    "provider": args.provider,
                    "model": args.model,
                    "endpoint": args.endpoint,
                    "region": args.region,
                    "secret_env": args.secret_env,
                }
                current.update({key: value for key, value in updates.items() if value is not None})
                show(request(args.url, "/api/settings", "PUT", current))
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
