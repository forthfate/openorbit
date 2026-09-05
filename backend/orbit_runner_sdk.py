"""Small, dependency-free SDK for Orbit runner assets.

Runner files are operator-owned Python.  Orbit invokes exactly one named phase
per subprocess, so a runner cannot accidentally become a second scheduler.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(os.environ.get("ORBIT_TARGET_REPOSITORY", Path.cwd())).resolve()
ORBIT_APP_DATA = Path(os.environ.get("ORBIT_APP_DATA", Path.home() / ".local" / "share" / "orbit")).resolve()


def ORBIT_PROJECT_PATH(*parts: str) -> Path:
    """Resolve a safe path relative to the evaluation target repository."""
    candidate = PROJECT_ROOT.joinpath(*parts).resolve()
    if candidate != PROJECT_ROOT and PROJECT_ROOT not in candidate.parents:
        raise ValueError("project path must stay within PROJECT_ROOT")
    return candidate


@dataclass
class RunnerContext:
    phase: str
    target_repository: Path
    mode: str
    loop_index: int
    environment: dict[str, str] = field(default_factory=lambda: dict(os.environ))

    @property
    def resources(self) -> dict[str, object]:
        encoded = self.environment.get("ORBIT_RUNNER_RESOURCES", "")
        if not encoded:
            return {}
        return json.loads(base64.b64decode(encoded).decode("utf-8"))

    @property
    def project_root(self) -> Path:
        """Evaluation target root; use this instead of a machine-specific path."""
        return self.target_repository.resolve()

    @property
    def app_data(self) -> Path:
        """Orbit's per-user writable data directory."""
        return ORBIT_APP_DATA

    def project_path(self, *parts: str) -> Path:
        """Resolve a path relative to PROJECT_ROOT without escaping it."""
        return ORBIT_PROJECT_PATH(*parts)

    @property
    def workflow(self) -> dict[str, object]:
        return dict(self.resources.get("workflow", {}))

    @property
    def evaluation_build(self) -> dict[str, object]:
        return dict(self.resources.get("evaluation_build", {}))

    @property
    def test_cases(self) -> list[dict[str, object]]:
        return list(self.resources.get("test_cases", []))

    def resource(self, name: str, default: object = None) -> object:
        """Read an Orbit resource snapshot supplied for this execution."""
        return self.resources.get(name, default)

    def log(self, message: str) -> None:
        print(f"[orbit:{self.phase}] {message}", flush=True)

    def emit_result(self, values: dict[str, object]) -> None:
        """Attach structured, JSON-safe evidence to the current Orbit step."""
        print("__ORBIT_RESULT__" + json.dumps(values, ensure_ascii=False), flush=True)

    def playwright_journey(self, cases: list[dict[str, object]] | None = None) -> dict[str, object]:
        """Run bounded, read-only Playwright page checks for the supplied cases.

        The browser process is short lived.  Scheduling, locking, and any
        application-server lifecycle remain Orbit's responsibility.
        """
        build = self.evaluation_build
        base_url = str(build.get("browser_base_url") or self.environment.get("ORBIT_BROWSER_BASE_URL") or "").strip()
        if not base_url:
            raise ValueError("browser_base_url is required for a Playwright journey")
        selected_cases = cases if cases is not None else self.test_cases
        if not selected_cases:
            raise ValueError("at least one fixed test case is required for a Playwright journey")
        artifacts = self.app_data / "artifacts" / self.environment.get("ORBIT_RUN_ID", "manual") / f"loop-{self.loop_index}"
        artifacts.mkdir(parents=True, exist_ok=True)
        module = self.environment.get("ORBIT_PLAYWRIGHT_MODULE", "")
        if not module:
            module = str(Path(__file__).resolve().parents[1] / "frontend" / "node_modules" / "playwright")
        payload = {"baseUrl": base_url, "cases": selected_cases, "artifacts": str(artifacts), "headless": self.environment.get("ORBIT_BROWSER_HEADLESS", "true") != "false", "executablePath": str(build.get("browser_executable_path", "")).strip()}
        script = r'''const fs=require('fs'); const { chromium }=require(process.argv[1]); const input=JSON.parse(process.argv[2]);
(async()=>{const launch={headless:input.headless}; if(input.executablePath)launch.executablePath=input.executablePath; else if(process.env.SIM_BROWSER_BIN)launch.executablePath=process.env.SIM_BROWSER_BIN; const browser=await chromium.launch(launch); const results=[];
for(const item of input.cases){const page=await browser.newPage();const path=String(item.path||'/');const url=new URL(path,input.baseUrl).toString();const id=String(item.id||'case').replace(/[^a-zA-Z0-9_-]/g,'-');const screenshot=`${input.artifacts}/${id}.png`;try{await page.goto(url,{waitUntil:'domcontentloaded',timeout:30000});const expected=String(item.expected_text||'').trim();const passed=!expected||await page.getByText(expected,{exact:false}).first().isVisible({timeout:5000});await page.screenshot({path:screenshot,fullPage:true});results.push({id:item.id,name:item.name,url,passed,expected_text:expected,screenshot});}catch(error){try{await page.screenshot({path:screenshot,fullPage:true});}catch{}results.push({id:item.id,name:item.name,url,passed:false,error:String(error),screenshot});}finally{await page.close();}}
await browser.close(); console.log(JSON.stringify({base_url:input.baseUrl,results}));})().catch(error=>{console.error(error);process.exit(1)});'''
        environment = dict(self.environment)
        library_path = str(build.get("browser_library_path", "")).strip()
        if library_path:
            environment["LD_LIBRARY_PATH"] = library_path + (os.pathsep + environment["LD_LIBRARY_PATH"] if environment.get("LD_LIBRARY_PATH") else "")
        result = subprocess.run(["node", "-e", script, module, json.dumps(payload)], env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout[-4000:] or "Playwright journey failed")
        try:
            evidence = json.loads(result.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as error:
            raise RuntimeError("Playwright did not return structured journey evidence") from error
        evidence["artifacts_directory"] = str(artifacts)
        self.emit_result({"browser_journey": evidence})
        return evidence

    def exec(self, command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
        self.log(f"exec: {' '.join(command)}")
        result = subprocess.run(command, cwd=cwd or self.target_repository, env=self.environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        if result.stdout:
            print(result.stdout, end="", flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


class Runner:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[RunnerContext], None]] = {}

    def phase(self, name: str) -> Callable[[Callable[[RunnerContext], None]], Callable[[RunnerContext], None]]:
        def register(handler: Callable[[RunnerContext], None]) -> Callable[[RunnerContext], None]:
            self._handlers[name] = handler
            return handler
        return register

    def main(self) -> None:
        parser = argparse.ArgumentParser(description="Orbit runner phase")
        parser.add_argument("--phase", required=True)
        args = parser.parse_args()
        handler = self._handlers.get(args.phase)
        if handler is None:
            raise SystemExit(f"runner does not define phase: {args.phase}")
        handler(RunnerContext(args.phase, Path(os.environ["ORBIT_TARGET_REPOSITORY"]), os.environ.get("ORBIT_EXECUTION_MODE", "run"), int(os.environ.get("ORBIT_LOOP_INDEX", "1"))))


runner = Runner()
