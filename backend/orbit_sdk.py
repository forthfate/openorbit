"""Small, dependency-free SDK for Orbit runner assets.

Runner files are operator-owned Python.  Orbit invokes exactly one named phase
per subprocess, so a runner cannot accidentally become a second scheduler.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal

PROJECT_ROOT = Path(os.environ.get("ORBIT_TARGET_REPOSITORY", Path.cwd())).resolve()
ORBIT_APP_DATA = Path(os.environ.get("ORBIT_APP_DATA", Path.home() / ".local" / "share" / "orbit")).resolve()


def ORBIT_PROJECT_PATH(*parts: str) -> Path:
    """Resolve a safe path relative to the evaluation target repository."""
    candidate = PROJECT_ROOT.joinpath(*parts).resolve()
    if candidate != PROJECT_ROOT and PROJECT_ROOT not in candidate.parents:
        raise ValueError("project path must stay within PROJECT_ROOT")
    return candidate


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    """Replace a file only after its complete replacement has been written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.orbit-tmp-{os.getpid()}")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _file_history_paths(project_root: Path, relative_path: str) -> tuple[Path, Path]:
    """Keep retained versions outside the target repository and collision-free."""
    project_key = _sha256(str(project_root).encode("utf-8"))
    path_key = _sha256(relative_path.encode("utf-8"))
    directory = ORBIT_APP_DATA / "file-history" / project_key / path_key
    return directory, directory / "manifest.json"


def _proposal_history_path(project_root: Path) -> Path:
    project_key = _sha256(str(project_root).encode("utf-8"))
    return ORBIT_APP_DATA / "proposal-history" / project_key / "decisions.json"


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

    def managed_asset_dir(self, name: str) -> Path:
        """Return a private, runner-managed AppData directory for a named asset set."""
        if not name or any(part in {"", ".", ".."} for part in Path(name).parts):
            raise ValueError("managed asset name must be a relative, non-empty path")
        directory = self.app_data / "runner-assets" / _sha256(str(self.project_root).encode()) / name
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def materialize_assets(self, name: str, files: dict[str, str | bytes]) -> dict[str, object]:
        """Atomically materialize runner-owned files outside the target repository."""
        directory = self.managed_asset_dir(name)
        manifest: dict[str, str] = {}
        for relative, value in files.items():
            candidate = (directory / relative).resolve()
            if candidate == directory or directory not in candidate.parents:
                raise ValueError("managed asset path must stay within its asset directory")
            content = value.encode("utf-8") if isinstance(value, str) else bytes(value)
            _atomic_write(candidate, content)
            manifest[relative] = _sha256(content)
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        _atomic_write(directory / ".manifest.json", manifest_bytes)
        result = {"directory": str(directory), "sha256": _sha256(manifest_bytes), "files": manifest}
        self.emit_result({"managed_assets": {"name": name, **result}})
        return result

    def write_artifact(
        self,
        relative_path: str | Path,
        content: str | bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> dict[str, object]:
        """Persist immutable run evidence in AppData and attach its metadata to the step."""
        relative = Path(relative_path)
        if (
            not relative.parts
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ValueError("artifact path must be a non-empty relative path")
        run_id = self.environment.get("ORBIT_RUN_ID", "manual")
        directory = self.app_data / "artifacts" / run_id / f"loop-{self.loop_index}"
        target = (directory / relative).resolve()
        if directory.resolve() not in target.parents:
            raise ValueError("artifact path must stay within its run directory")
        payload = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        _atomic_write(target, payload)
        result = {
            "path": str(target),
            "relative_path": relative.as_posix(),
            "sha256": _sha256(payload),
            "size": len(payload),
            "content_type": content_type,
        }
        self.emit_result({"artifact": result})
        return result

    def git_candidate(
        self, paths: list[str] | None = None, *, retain_patch: bool = False
    ) -> dict[str, object]:
        """Summarize the current Git candidate without flooding runner output with its diff."""
        suffix = ["--", *(paths or [])]
        patch = subprocess.run(
            ["git", "diff", "--binary", *suffix],
            cwd=self.project_root,
            env=self.environment,
            capture_output=True,
            check=True,
        ).stdout
        changed = subprocess.run(
            ["git", "diff", "--name-only", *suffix],
            cwd=self.project_root,
            env=self.environment,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.splitlines()
        result: dict[str, object] = {
            "fingerprint": _sha256(patch) if patch else None,
            "changed_paths": changed,
        }
        if retain_patch and patch:
            result["patch_artifact"] = self.write_artifact(
                "candidates/current.patch", patch, content_type="text/x-diff"
            )
        self.emit_result({"git_candidate": result})
        return result

    def windows_path(self, value: str | Path) -> str:
        """Convert a WSL-mounted path to a Windows path for a Windows child process."""
        path = Path(value)
        parts = path.parts
        if len(parts) >= 4 and parts[1] == "mnt" and len(parts[2]) == 1:
            return parts[2].upper() + ":\\" + "\\".join(parts[3:])
        raise ValueError(f"path is not a Windows-mounted drive: {path}")

    def _versioned_file(self, relative_path: str | Path) -> tuple[Path, str, Path, Path]:
        """Resolve a target file and its private, AppData-backed history directory."""
        target = self.project_root.joinpath(str(relative_path)).resolve()
        if target != self.project_root and self.project_root not in target.parents:
            raise ValueError("project path must stay within PROJECT_ROOT")
        if target == self.project_root:
            raise ValueError("a file path is required")
        if target.exists() and not target.is_file():
            raise ValueError("file versioning only supports regular files")
        relative = target.relative_to(self.project_root).as_posix()
        directory, manifest_path = _file_history_paths(self.project_root, relative)
        return target, relative, directory, manifest_path

    def _load_file_history(self, relative_path: str | Path) -> tuple[Path, str, Path, Path, dict]:
        target, relative, directory, manifest_path = self._versioned_file(relative_path)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            manifest = {
                "schema_version": 1,
                "project_root": str(self.project_root),
                "relative_path": relative,
                "history": [],
            }
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Orbit file history is invalid for {relative}") from error
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != 1
            or manifest.get("project_root") != str(self.project_root)
            or manifest.get("relative_path") != relative
            or not isinstance(manifest.get("history"), list)
        ):
            raise RuntimeError(f"Orbit file history does not match {relative}")
        return target, relative, directory, manifest_path, manifest

    @staticmethod
    def _file_state(content: bytes | None) -> dict[str, object]:
        if content is None:
            return {"exists": False, "sha256": None, "size": 0, "snapshot": None}
        return {"exists": True, "sha256": _sha256(content), "size": len(content), "snapshot": None}

    def _record_file_version(
        self,
        *,
        directory: Path,
        manifest_path: Path,
        manifest: dict,
        relative_path: str,
        previous: bytes | None,
        written: bytes | None,
        operation: str,
        rollback_of: str | None = None,
    ) -> dict[str, object]:
        history = manifest["history"]
        sequence = len(history) + 1
        previous_state = self._file_state(previous)
        if previous is not None:
            snapshot_name = f"versions/{sequence:06d}-{previous_state['sha256'][:16]}.bin"
            _atomic_write(directory / snapshot_name, previous)
            previous_state["snapshot"] = snapshot_name
        written_state = self._file_state(written)
        version_id = f"v{sequence:06d}-{str(previous_state['sha256'] or 'absent')[:12]}"
        record = {
            "id": version_id,
            "sequence": sequence,
            "operation": operation,
            "rollback_of": rollback_of,
            "recorded_at": datetime.now(UTC).isoformat(),
            "iteration": self.loop_index,
            "phase": self.phase,
            "run_id": self.environment.get("ORBIT_RUN_ID") or None,
            "relative_path": relative_path,
            "previous": previous_state,
            "written": written_state,
        }
        history.append(record)
        _atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        )
        return record

    def update_file(
        self, relative_path: str | Path, content: str | bytes, *, encoding: str = "utf-8"
    ) -> dict[str, object]:
        """Atomically update a project file, retaining its pre-update version.

        Snapshots and their metadata live under Orbit AppData rather than the
        target repository. Each changed write retains the prior bytes together
        with the runner iteration, phase, run ID, timestamp, and SHA-256 hashes.
        Use :meth:`file_versions` to inspect retained versions and
        :meth:`rollback_file` to restore a selected one.
        """
        target, relative, directory, manifest_path, manifest = self._load_file_history(relative_path)
        next_content = content.encode(encoding) if isinstance(content, str) else bytes(content)
        previous = target.read_bytes() if target.exists() else None
        if previous == next_content:
            return {
                "changed": False,
                "path": relative,
                "sha256": _sha256(next_content),
                "version": None,
            }
        mode = target.stat().st_mode if target.exists() else None
        record = self._record_file_version(
            directory=directory,
            manifest_path=manifest_path,
            manifest=manifest,
            relative_path=relative,
            previous=previous,
            written=next_content,
            operation="update",
        )
        _atomic_write(target, next_content)
        if mode is not None:
            os.chmod(target, mode)
        self.emit_result({"file_update": {"path": relative, "changed": True, "version": record}})
        return {"changed": True, "path": relative, "sha256": _sha256(next_content), "version": record}

    def file_versions(self, relative_path: str | Path) -> list[dict[str, object]]:
        """List retained pre-update versions for a project file, newest first."""
        _, _, _, _, manifest = self._load_file_history(relative_path)
        return list(reversed(manifest["history"]))

    def rollback_file(self, relative_path: str | Path, version_id: str) -> dict[str, object]:
        """Restore the pre-update state retained by ``version_id``.

        Rolling back first snapshots the current file as a new version. This
        makes a rollback reversible: call this method again using that newly
        returned version ID to return to the state before the rollback.
        """
        target, relative, directory, manifest_path, manifest = self._load_file_history(relative_path)
        version = next((item for item in manifest["history"] if item.get("id") == version_id), None)
        if version is None:
            raise KeyError(f"unknown file version: {version_id}")
        previous_state = version.get("previous")
        if not isinstance(previous_state, dict):
            raise RuntimeError(f"Orbit file history is invalid for {relative}")
        snapshot_name = previous_state.get("snapshot")
        restore = (directory / str(snapshot_name)).read_bytes() if snapshot_name else None
        if bool(previous_state.get("exists")) != (restore is not None):
            raise RuntimeError(f"Orbit file snapshot is missing for {relative}")
        current = target.read_bytes() if target.exists() else None
        record = self._record_file_version(
            directory=directory,
            manifest_path=manifest_path,
            manifest=manifest,
            relative_path=relative,
            previous=current,
            written=restore,
            operation="rollback",
            rollback_of=version_id,
        )
        if restore is None:
            target.unlink(missing_ok=True)
        else:
            mode = target.stat().st_mode if target.exists() else None
            _atomic_write(target, restore)
            if mode is not None:
                os.chmod(target, mode)
        self.emit_result(
            {"file_rollback": {"path": relative, "restored_version": version_id, "version": record}}
        )
        return {"path": relative, "restored_version": version_id, "version": record}

    def proposal_decisions(self) -> list[dict[str, object]]:
        """Return recorded accepted/rejected proposals for this target, newest first."""
        path = _proposal_history_path(self.project_root)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as error:
            raise RuntimeError("Orbit proposal decision history is invalid") from error
        decisions = document.get("decisions") if isinstance(document, dict) else None
        if not isinstance(decisions, list):
            raise RuntimeError("Orbit proposal decision history is invalid")
        return list(reversed(decisions))

    def record_proposal_decision(
        self,
        proposal: dict[str, object],
        decision: Literal["accepted", "rejected"],
        *,
        proposal_id: str | None = None,
        rationale: str = "",
    ) -> dict[str, object]:
        """Persist an auditable accepted or rejected improvement proposal.

        The ledger is stored in Orbit AppData, outside the target repository.
        Repeating the same decision for unchanged proposal content is idempotent,
        while a changed decision is appended as a new event. This produces a
        compact event stream for a future proposal-review UI.
        """
        if not proposal:
            raise ValueError("proposal must not be empty")
        canonical = json.dumps(proposal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = _sha256(canonical.encode("utf-8"))
        identifier = proposal_id or f"proposal-{fingerprint[:16]}"
        path = _proposal_history_path(self.project_root)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            document = {
                "schema_version": 1,
                "project_root": str(self.project_root),
                "decisions": [],
            }
        except json.JSONDecodeError as error:
            raise RuntimeError("Orbit proposal decision history is invalid") from error
        decisions = document.get("decisions") if isinstance(document, dict) else None
        if (
            not isinstance(decisions, list)
            or document.get("schema_version") != 1
            or document.get("project_root") != str(self.project_root)
        ):
            raise RuntimeError("Orbit proposal decision history does not match this project")
        existing = next(
            (
                item
                for item in reversed(decisions)
                if isinstance(item, dict)
                and item.get("proposal_id") == identifier
                and item.get("decision") == decision
                and item.get("proposal_sha256") == fingerprint
            ),
            None,
        )
        if existing is not None:
            return {"recorded": False, "decision": existing}
        build = self.evaluation_build
        record = {
            "id": f"pd-{len(decisions) + 1:06d}-{fingerprint[:12]}",
            "event_type": "decision",
            "proposal_id": identifier,
            "proposal_sha256": fingerprint,
            "decision": decision,
            "rationale": rationale,
            "proposal": proposal,
            "recorded_at": datetime.now(UTC).isoformat(),
            "iteration": self.loop_index,
            "phase": self.phase,
            "run_id": self.environment.get("ORBIT_RUN_ID") or None,
            "evaluation_build_id": build.get("id") or None,
            "evaluation_build_name": build.get("name") or None,
        }
        decisions.append(record)
        _atomic_write(
            path, json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        )
        self.emit_result({"proposal_decision": record})
        return {"recorded": True, "decision": record}

    def record_proposal_application(
        self, proposal_ids: list[str], file_update: dict[str, object]
    ) -> list[dict[str, object]]:
        """Link accepted proposals to the prompt version they changed.

        This is an append-only lifecycle event. It lets a review UI traverse
        from a decision to an exact prompt snapshot and its rollback version
        without mutating the original decision record.
        """
        version = file_update.get("version")
        if not isinstance(version, dict) or not version.get("id"):
            return []
        prompt_version_id = str(version["id"])
        path = _proposal_history_path(self.project_root)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as error:
            raise RuntimeError("Orbit proposal decision history is invalid") from error
        decisions = document.get("decisions") if isinstance(document, dict) else None
        if not isinstance(decisions, list):
            raise RuntimeError("Orbit proposal decision history is invalid")
        build = self.evaluation_build
        recorded: list[dict[str, object]] = []
        for proposal_id in dict.fromkeys(proposal_ids):
            already_linked = any(
                isinstance(item, dict)
                and item.get("event_type") == "prompt_updated"
                and item.get("proposal_id") == proposal_id
                and isinstance(item.get("prompt_version"), dict)
                and item["prompt_version"].get("id") == prompt_version_id
                for item in decisions
            )
            if already_linked:
                continue
            record = {
                "id": f"pa-{len(decisions) + 1:06d}-{prompt_version_id}",
                "event_type": "prompt_updated",
                "proposal_id": proposal_id,
                "recorded_at": datetime.now(UTC).isoformat(),
                "iteration": self.loop_index,
                "phase": self.phase,
                "run_id": self.environment.get("ORBIT_RUN_ID") or None,
                "evaluation_build_id": build.get("id") or None,
                "evaluation_build_name": build.get("name") or None,
                "prompt_version": {
                    "id": prompt_version_id,
                    "path": file_update.get("path"),
                    "sha256": file_update.get("sha256"),
                    "previous": version.get("previous"),
                    "written": version.get("written"),
                },
            }
            decisions.append(record)
            recorded.append(record)
        if recorded:
            _atomic_write(
                path, json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            )
            self.emit_result({"proposal_applications": recorded})
        return recorded

    def accept_proposal(
        self, proposal: dict[str, object], *, proposal_id: str | None = None, rationale: str = ""
    ) -> dict[str, object]:
        """Record that a proposal was selected for this target's improvement history."""
        return self.record_proposal_decision(
            proposal, "accepted", proposal_id=proposal_id, rationale=rationale
        )

    def reject_proposal(
        self, proposal: dict[str, object], *, proposal_id: str | None = None, rationale: str = ""
    ) -> dict[str, object]:
        """Record that a proposal was not selected for this target's improvement history."""
        return self.record_proposal_decision(
            proposal, "rejected", proposal_id=proposal_id, rationale=rationale
        )

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

    @property
    def previous_supervisor_feedback(self) -> dict[str, object]:
        """Return the latest completed supervisor response for this run.

        Runner phases run in separate subprocesses.  Reading the retained run
        record lets the next iteration use the previous iteration's feedback
        without coupling a runner to a target-specific state file.
        """
        run_id = self.environment.get("ORBIT_RUN_ID", "").strip()
        if not run_id:
            return {}
        path = self.app_data / "data" / "runs" / f"{run_id}.json"
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        records = values.get("supervisor_results", [])
        if not isinstance(records, list):
            return {}
        for record in reversed(records):
            response = record.get("response") if isinstance(record, dict) else None
            if isinstance(response, dict):
                return response
        return {}

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
        base_url = str(
            build.get("browser_base_url") or self.environment.get("ORBIT_BROWSER_BASE_URL") or ""
        ).strip()
        if not base_url:
            raise ValueError("browser_base_url is required for a Playwright journey")
        selected_cases = cases if cases is not None else self.test_cases
        if not selected_cases:
            raise ValueError("at least one fixed test case is required for a Playwright journey")
        artifacts = (
            self.app_data
            / "artifacts"
            / self.environment.get("ORBIT_RUN_ID", "manual")
            / f"loop-{self.loop_index}"
        )
        artifacts.mkdir(parents=True, exist_ok=True)
        module = self.environment.get("ORBIT_PLAYWRIGHT_MODULE", "")
        if not module:
            module = str(Path(__file__).resolve().parents[1] / "frontend" / "node_modules" / "playwright")
        payload = {
            "baseUrl": base_url,
            "cases": selected_cases,
            "artifacts": str(artifacts),
            "headless": self.environment.get("ORBIT_BROWSER_HEADLESS", "true") != "false",
            "executablePath": str(build.get("browser_executable_path", "")).strip(),
        }
        script = r"""const fs=require('fs'); const { chromium }=require(process.argv[1]); const input=JSON.parse(process.argv[2]);
(async()=>{const launch={headless:input.headless}; if(input.executablePath)launch.executablePath=input.executablePath; else if(process.env.SIM_BROWSER_BIN)launch.executablePath=process.env.SIM_BROWSER_BIN; const browser=await chromium.launch(launch); const results=[];
for(const item of input.cases){const page=await browser.newPage();const path=String(item.path||'/');const url=new URL(path,input.baseUrl).toString();const id=String(item.id||'case').replace(/[^a-zA-Z0-9_-]/g,'-');const screenshot=`${input.artifacts}/${id}.png`;try{await page.goto(url,{waitUntil:'domcontentloaded',timeout:30000});const expected=String(item.expected_text||'').trim();const passed=!expected||await page.getByText(expected,{exact:false}).first().isVisible({timeout:5000});await page.screenshot({path:screenshot,fullPage:true});results.push({id:item.id,name:item.name,url,passed,expected_text:expected,screenshot});}catch(error){try{await page.screenshot({path:screenshot,fullPage:true});}catch{}results.push({id:item.id,name:item.name,url,passed:false,error:String(error),screenshot});}finally{await page.close();}}
await browser.close(); console.log(JSON.stringify({base_url:input.baseUrl,results}));})().catch(error=>{console.error(error);process.exit(1)});"""
        environment = dict(self.environment)
        library_path = str(build.get("browser_library_path", "")).strip()
        if library_path:
            environment["LD_LIBRARY_PATH"] = library_path + (
                os.pathsep + environment["LD_LIBRARY_PATH"] if environment.get("LD_LIBRARY_PATH") else ""
            )
        result = subprocess.run(
            ["node", "-e", script, module, json.dumps(payload)],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError(result.stdout[-4000:] or "Playwright journey failed")
        try:
            evidence = json.loads(result.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as error:
            raise RuntimeError("Playwright did not return structured journey evidence") from error
        evidence["artifacts_directory"] = str(artifacts)
        self.emit_result({"browser_journey": evidence})
        return evidence

    def exec(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Run one bounded child command and return its captured output.

        A runner phase is deliberately not a scheduler.  Returning the output
        lets a phase turn its one-shot result into Orbit-owned structured
        evidence without starting a persistent child daemon.
        """
        self.log(f"exec: {' '.join(command)}")
        result = subprocess.run(
            command,
            cwd=cwd or self.target_repository,
            env={**self.environment, **(env or {})},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        if result.stdout:
            print(result.stdout, end="", flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)
        return result.stdout


class Runner:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[RunnerContext], None]] = {}

    def phase(
        self, name: str
    ) -> Callable[[Callable[[RunnerContext], None]], Callable[[RunnerContext], None]]:
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
        handler(
            RunnerContext(
                args.phase,
                Path(os.environ["ORBIT_TARGET_REPOSITORY"]),
                os.environ.get("ORBIT_EXECUTION_MODE", "run"),
                int(os.environ.get("ORBIT_LOOP_INDEX", "1")),
            )
        )


runner = Runner()
