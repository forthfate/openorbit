"""Small, dependency-free SDK for Orbit runner assets.

Runner files are operator-owned Python.  Orbit invokes exactly one named phase
per subprocess, so a runner cannot accidentally become a second scheduler.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Literal

from coding_agents import build_coding_agent_command

from orbit_sdk.core.lifecycle import canonical_phase
from orbit_sdk.helpers import command_from_environment

PROJECT_ROOT = Path(os.environ.get("ORBIT_TARGET_REPOSITORY", Path.cwd())).resolve()
ORBIT_APP_DATA = Path(os.environ.get("ORBIT_APP_DATA", Path.home() / ".local" / "share" / "orbit")).resolve()


def ORBIT_PROJECT_PATH(*parts: str) -> Path:
    """Resolve a safe path relative to the evaluation target repository.

    Args:
        *parts: Path components below the target repository.

    Returns:
        An absolute path inside the target repository.

    Raises:
        ValueError: If the resolved path would escape the target repository.
    """
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


def _state_name(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
        raise ValueError("state name must be 1-64 letters, numbers, underscores, or hyphens")
    return name


def _repository_snapshot_paths(project_root: Path) -> tuple[Path, Path]:
    """Return the private manifest location for Git-object repository snapshots."""
    project_key = _sha256(str(project_root).encode("utf-8"))
    directory = ORBIT_APP_DATA / "repository-snapshots" / project_key
    return directory, directory / "manifest.json"


@dataclass
class RunnerContext:
    """Per-phase SDK interface supplied to a runner handler.

    Do not construct this class in a normal runner. Decorate a function with
    ``@runner.phase(...)`` and Orbit creates the context when it invokes that
    phase. The context is scoped to one process invocation and one iteration.

    Attributes:
        phase: The lifecycle phase currently being invoked.
        target_repository: Root directory of the evaluated target.
        mode: Execution mode, normally ``"run"`` or ``"test"``.
        loop_index: One-based evaluation iteration number.
        environment: Environment snapshot passed to the runner process.
    """

    phase: str
    target_repository: Path
    mode: str
    loop_index: int
    environment: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    _active_workflow_functions: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        self.phase = canonical_phase(self.phase)

    @contextmanager
    def function(self, function_id: str) -> Iterator[None]:
        """Record one graph-annotated function's outcome within this lifecycle phase.

        Args:
            function_id: Stable graph function identifier shown in retained run evidence.

        Yields:
            Control to the wrapped function body.
        """
        if not function_id.strip():
            raise ValueError("function_id must not be empty")
        if function_id in self._active_workflow_functions:
            yield
            return
        self._active_workflow_functions.add(function_id)
        started = datetime.now(UTC)
        self.log(f"workflow function started: {function_id}")
        self.emit_result(
            {
                "workflow_functions": [
                    {
                        "id": function_id,
                        "status": "running",
                        "started_at": started.isoformat(),
                    }
                ]
            }
        )
        try:
            yield
        except BaseException:
            self.log(f"workflow function failed: {function_id}")
            self.emit_result(
                {
                    "workflow_functions": [
                        {
                            "id": function_id,
                            "status": "failed",
                            "started_at": started.isoformat(),
                            "ended_at": datetime.now(UTC).isoformat(),
                        }
                    ]
                }
            )
            raise
        else:
            self.log(f"workflow function succeeded: {function_id}")
            self.emit_result(
                {
                    "workflow_functions": [
                        {
                            "id": function_id,
                            "status": "succeeded",
                            "started_at": started.isoformat(),
                            "ended_at": datetime.now(UTC).isoformat(),
                        }
                    ]
                }
            )
        finally:
            self._active_workflow_functions.discard(function_id)

    @property
    def resources(self) -> dict[str, object]:
        """Return the immutable resource snapshot provided for this invocation.

        The snapshot can contain the workflow, build, fixed test
        cases, model profile, and execution-environment settings. Prefer the
        typed convenience properties when one is available.

        Returns:
            Immutable resource values supplied for this invocation.
        """
        encoded = self.environment.get("ORBIT_RUNNER_RESOURCES", "")
        if not encoded:
            return {}
        return json.loads(base64.b64decode(encoded).decode("utf-8"))

    @property
    def project_root(self) -> Path:
        """Evaluation target root; use this instead of a machine-specific path.

        Returns:
            Resolved root directory of the evaluated target.
        """
        return self.target_repository.resolve()

    @property
    def app_data(self) -> Path:
        """Orbit's per-user writable data directory.

        Returns:
            Writable Orbit AppData directory.
        """
        return ORBIT_APP_DATA

    def project_path(self, *parts: str) -> Path:
        """Resolve a target-repository path without allowing path traversal.

        Args:
            *parts: Relative path components inside :attr:`project_root`.

        Returns:
            An absolute target-repository path.

        Raises:
            ValueError: If the path escapes the target repository.
        """
        return ORBIT_PROJECT_PATH(*parts)

    def managed_asset_dir(self, name: str) -> Path:
        """Return a private, runner-managed AppData directory for a named asset set.

        Args:
            name: Non-empty relative name for the runner-owned asset set.

        Returns:
            Writable AppData directory isolated from the target repository.
        """
        if not name or any(part in {"", ".", ".."} for part in Path(name).parts):
            raise ValueError("managed asset name must be a relative, non-empty path")
        directory = self.app_data / "runner-assets" / _sha256(str(self.project_root).encode()) / name
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _state_path(self, name: str, scope: str) -> Path:
        state_name = _state_name(name)
        build_id = _state_name(str(self.build.get("id") or _sha256(str(self.project_root).encode())[:16]))
        if scope not in {"build", "runner"}:
            raise ValueError("state scope must be 'build' or 'runner'")
        directory = self.app_data / "runner-state" / build_id / "build"
        if scope == "runner":
            runner_id = _state_name(
                str(self.build.get("runner_id") or self.environment.get("ORBIT_RUNNER_ID") or "manual")
            )
            directory = self.app_data / "runner-state" / build_id / "runners" / runner_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{state_name}.json"

    def load_state(self, name: str, default: object = None, *, scope: str = "runner") -> object:
        """Load mutable runner- or build-scoped state from Orbit AppData.

        State is separate from immutable run evidence. Use it only for bounded
        continuation data required by a later run, such as a persona's last
        observation or next check. State values must be JSON-safe.

        Args:
            name: Stable state name containing letters, numbers, underscores, or hyphens.
            default: Value returned when no saved state exists.
            scope: ``"runner"`` for runner-isolated state (the default), or
                ``"build"`` for state shared by every runner in this build.

        Returns:
            The saved JSON value or ``default`` when the named state is absent.
        """
        path = self._state_path(name, scope)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Orbit runner state is invalid: {name}") from error
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise RuntimeError(f"Orbit runner state is invalid: {name}")
        return document.get("value", default)

    def save_state(self, name: str, value: object, *, scope: str = "runner") -> dict[str, object]:
        """Atomically save mutable runner- or build-scoped state in Orbit AppData.

        The value is not copied into run evidence. Emit a bounded summary with
        :meth:`emit_result` when a particular state transition needs auditing.

        Args:
            name: Stable state name containing letters, numbers, underscores, or hyphens.
            value: JSON-safe value to retain for a later invocation of this build.
            scope: ``"runner"`` for runner-isolated state (the default), or
                ``"build"`` for state shared by every runner in this build.

        Returns:
            State name, update timestamp, and JSON byte size.
        """
        path = self._state_path(name, scope)
        try:
            encoded_value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as error:
            raise ValueError("state value must be JSON serializable") from error
        document = {
            "schema_version": 1,
            "updated_at": datetime.now(UTC).isoformat(),
            "run_id": self.environment.get("ORBIT_RUN_ID") or None,
            "iteration": self.loop_index,
            "scope": scope,
            "value": json.loads(encoded_value),
        }
        payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        _atomic_write(path, payload)
        return {
            "name": _state_name(name),
            "scope": scope,
            "updated_at": document["updated_at"],
            "size": len(payload),
        }

    def visual_node_inputs(
        self, node_id: str, bindings: dict[str, tuple[str, str]] | None = None
    ) -> dict[str, object]:
        """Return declared upstream values for one generated visual-runner node.

        Args:
            node_id: The generated graph-node identifier requesting inputs.
            bindings: Input names mapped to ``(source_node_id, output_port)``.
                Generated visual runners provide this mapping from their data
                edges, so unrelated node output is never exposed implicitly.

        Returns:
            A dictionary keyed by the node's declared input ports. Missing
            upstream values are omitted, allowing a custom script to apply a
            default explicitly.
        """
        document = self.load_state("orbit-visual-node-outputs", {}, scope="runner")
        if not isinstance(document, dict) or document.get("iteration") != self.loop_index:
            return {}
        values = document.get("outputs", {})
        if not isinstance(values, dict):
            return {}
        if bindings is None:
            return {}
        inputs: dict[str, object] = {}
        for input_name, binding in bindings.items():
            if not isinstance(input_name, str) or not isinstance(binding, tuple) or len(binding) != 2:
                raise ValueError("visual node input bindings must map names to source node ports")
            source_node, source_port = binding
            source_outputs = values.get(source_node)
            if isinstance(source_outputs, dict) and source_port in source_outputs:
                inputs[input_name] = source_outputs[source_port]
        return inputs

    def publish_visual_node_outputs(self, node_id: str, values: dict[str, object]) -> None:
        """Persist JSON-safe outputs from one generated visual-runner node."""
        if not node_id.strip():
            raise ValueError("visual node ID must not be empty")
        if not isinstance(values, dict):
            raise ValueError("visual node outputs must be a JSON object")
        current = self.load_state("orbit-visual-node-outputs", {}, scope="runner")
        if not isinstance(current, dict) or current.get("iteration") != self.loop_index:
            current = {"iteration": self.loop_index, "outputs": {}}
        outputs = current.setdefault("outputs", {})
        if not isinstance(outputs, dict):
            outputs = current["outputs"] = {}
        outputs[node_id] = values
        self.save_state("orbit-visual-node-outputs", current, scope="runner")

    def run_visual_node(
        self,
        kind: str,
        *,
        node_id: str,
        config: dict[str, object],
        inputs: dict[str, object],
    ) -> dict[str, object]:
        """Dispatch one SDK-owned visual operation through its registry.

        Custom Script nodes intentionally remain generated Python. All curated
        operations use this dispatcher so their catalog metadata, validation,
        and runtime implementation have one SDK owner.
        """
        if not node_id.strip():
            raise ValueError("visual node ID must not be empty")
        from orbit_sdk.visual import visual_nodes
        from orbit_sdk.visual.bindings import resolve

        resolved = resolve(self, config, inputs)
        if not isinstance(resolved, dict):  # Defensive boundary for SDK node handlers.
            raise ValueError("visual node configuration must resolve to an object")
        return visual_nodes.execute(kind, self, config=resolved, inputs=inputs)

    def visual_should_run(self, condition: object, *, inputs: dict[str, object]) -> bool:
        """Evaluate a blueprint's safe, declarative node condition."""
        from orbit_sdk.visual.bindings import evaluate

        return evaluate(self, condition, inputs)

    def materialize_assets(self, name: str, files: dict[str, str | bytes]) -> dict[str, object]:
        """Atomically materialize runner-owned files outside the target repository.

        Use this for temporary scripts, fixtures, or adapter configuration that
        belongs to the runner rather than the evaluated project. Orbit emits a
        manifest with content hashes as step evidence.

        Args:
            name: Stable relative name for this runner-managed asset set.
            files: Relative paths and their UTF-8 text or byte content.

        Returns:
            The asset directory, manifest SHA-256, and hashes by file path.
        """
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
        """Persist immutable run evidence in AppData and attach its metadata to the step.

        Args:
            relative_path: Relative evidence path within the current run and iteration.
            content: Text or bytes to retain.
            content_type: MIME type used when the artifact is presented.

        Returns:
            Artifact path, SHA-256, size, content type, and relative path.
        """
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

    def save_data_file(
        self,
        relative_path: str | Path,
        content: str | bytes,
        *,
        label: str = "",
        content_type: str = "application/octet-stream",
    ) -> dict[str, object]:
        """Save a developer-named data file for the current evaluation iteration.

        Call this from any lifecycle phase where the data becomes meaningful.
        The label is display metadata for the evaluation UI, not a filesystem
        name; it can describe why this file was retained. The UI exposes both
        the actual filename and the full AppData path for copying.

        Args:
            relative_path: Relative file path within this run and iteration.
            content: Text or bytes to retain.
            label: Optional human-readable display name for this data file.
            content_type: MIME type used when the file is presented.

        Returns:
            File metadata, including the label, actual filename, and path.
        """
        normalized_label = str(label).strip()
        if len(normalized_label) > 256:
            raise ValueError("data file label must be 256 characters or fewer")
        artifact = self.write_artifact(relative_path, content, content_type=content_type)
        result = {
            **artifact,
            "label": normalized_label,
            "filename": Path(str(artifact["relative_path"])).name,
        }
        self.emit_result({"data_files": [result]})
        return result

    def git_candidate(
        self, paths: list[str] | None = None, *, retain_patch: bool = False
    ) -> dict[str, object]:
        """Summarize the current Git candidate without flooding runner output with its diff.

        Args:
            paths: Optional target-relative paths to limit the Git diff.
            retain_patch: Store the binary diff as an artifact when it is non-empty.

        Returns:
            A candidate fingerprint, changed paths, and optionally patch metadata.
        """
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

    def git_head(self) -> str | None:
        """Return the checked-out commit, or None when the target is not a Git repository.

        Returns:
            Checked-out commit SHA, or ``None`` when no HEAD is available.
        """
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=self.project_root,
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _git(
        self,
        arguments: list[str],
        *,
        environment: dict[str, str] | None = None,
        input: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run one Git plumbing command in the target repository."""
        return subprocess.run(
            ["git", *arguments],
            cwd=self.project_root,
            env=environment or self.environment,
            input=input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def _git_repository_root(self) -> Path:
        try:
            root = self._git(["rev-parse", "--show-toplevel"]).stdout.decode().strip()
        except subprocess.CalledProcessError as error:
            raise ValueError("repository snapshots require a Git worktree") from error
        if Path(root).resolve() != self.project_root:
            raise ValueError("target_repository must be the Git worktree root for repository snapshots")
        return self.project_root

    def _snapshot_manifest(self) -> tuple[Path, Path, dict[str, object]]:
        directory, path = _repository_snapshot_paths(self.project_root)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            manifest = {
                "schema_version": 1,
                "project_root": str(self.project_root),
                "snapshots": [],
            }
        except json.JSONDecodeError as error:
            raise RuntimeError("Orbit repository snapshot history is invalid") from error
        snapshots = manifest.get("snapshots") if isinstance(manifest, dict) else None
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != 1
            or manifest.get("project_root") != str(self.project_root)
            or not isinstance(snapshots, list)
        ):
            raise RuntimeError("Orbit repository snapshot history does not match this repository")
        return directory, path, manifest

    def _temporary_index_environment(self) -> tuple[dict[str, str], Path]:
        descriptor, name = tempfile.mkstemp(prefix="orbit-git-index-")
        os.close(descriptor)
        index_path = Path(name)
        index_path.unlink()
        return {**self.environment, "GIT_INDEX_FILE": str(index_path)}, index_path

    def _empty_directories(self) -> list[str]:
        """Record empty directories, which Git trees deliberately cannot represent."""
        empty: list[str] = []
        for current, directory_names, file_names in os.walk(self.project_root, topdown=False):
            directory = Path(current)
            relative = directory.relative_to(self.project_root)
            if not relative.parts:
                directory_names[:] = [name for name in directory_names if name != ".git"]
                continue
            if ".git" in relative.parts or directory.is_symlink():
                continue
            entries = [*directory_names, *file_names]
            if not entries:
                empty.append(relative.as_posix())
        return sorted(empty)

    def _tree_paths(self, tree: str) -> set[str]:
        output = self._git(["ls-tree", "-r", "-z", tree]).stdout
        paths: set[str] = set()
        for entry in output.split(b"\0"):
            if not entry:
                continue
            try:
                _, encoded_path = entry.split(b"\t", 1)
            except ValueError as error:
                raise RuntimeError("Git returned an invalid tree entry") from error
            paths.add(os.fsdecode(encoded_path))
        return paths

    def snapshot_repository(self, label: str, *, once: bool = False) -> dict[str, object]:
        """Store the complete target worktree as Git objects without creating a commit.

        The snapshot includes tracked, staged, untracked, and ignored files,
        together with the original index tree and HEAD reference. Git's object
        database deduplicates unchanged file blobs; Orbit keeps a private ref
        only so these otherwise-uncommitted objects survive Git garbage
        collection. The ref is not a branch, tag, or commit-history entry.

        Args:
            label: Stable checkpoint name such as ``"baseline"`` or
                ``"iteration-1"``.
            once: Return the existing checkpoint with this label for the run,
                rather than recording another one.

        Returns:
            Immutable snapshot metadata, including its worktree tree hash.
        """
        if not label or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in label
        ):
            raise ValueError("snapshot label may contain only letters, numbers, underscores, and hyphens")
        self._git_repository_root()
        run_id = self.environment.get("ORBIT_RUN_ID", "manual")
        directory, manifest_path, manifest = self._snapshot_manifest()
        snapshots = manifest["snapshots"]
        assert isinstance(snapshots, list)
        if once:
            existing = next(
                (
                    item
                    for item in reversed(snapshots)
                    if isinstance(item, dict) and item.get("run_id") == run_id and item.get("label") == label
                ),
                None,
            )
            if existing is not None:
                return dict(existing)
        head = self.git_head()
        if not head:
            raise ValueError("repository snapshots require a checked-out HEAD commit")
        symbolic_head = subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"],
            cwd=self.project_root,
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        head_ref = symbolic_head.stdout.decode().strip() if symbolic_head.returncode == 0 else None
        index_tree = self._git(["write-tree"]).stdout.decode().strip()
        temporary_environment, temporary_index = self._temporary_index_environment()
        try:
            self._git(["add", "--all", "--force", "--", "."], environment=temporary_environment)
            worktree_tree = (
                self._git(["write-tree"], environment=temporary_environment).stdout.decode().strip()
            )
        finally:
            temporary_index.unlink(missing_ok=True)
            temporary_index.with_name(f"{temporary_index.name}.lock").unlink(missing_ok=True)
        sequence = len(snapshots) + 1
        snapshot_id = f"s{sequence:06d}-{worktree_tree[:12]}"
        project_key = _sha256(str(self.project_root).encode("utf-8"))
        retention_ref = f"refs/orbit/snapshots/{project_key}/{snapshot_id}"
        self._git(["update-ref", retention_ref, worktree_tree])
        record: dict[str, object] = {
            "id": snapshot_id,
            "label": label,
            "recorded_at": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "iteration": self.loop_index,
            "phase": self.phase,
            "head": {"oid": head, "ref": head_ref},
            "index_tree": index_tree,
            "worktree_tree": worktree_tree,
            "retention_ref": retention_ref,
            "empty_directories": self._empty_directories(),
        }
        snapshots.append(record)
        directory.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        )
        self.emit_result({"repository_snapshot": record})
        return record

    def repository_snapshots(self) -> list[dict[str, object]]:
        """List retained repository snapshots, newest first.

        Returns:
            Retained snapshot metadata ordered newest first.
        """
        _, _, manifest = self._snapshot_manifest()
        snapshots = manifest["snapshots"]
        assert isinstance(snapshots, list)
        return [dict(item) for item in reversed(snapshots) if isinstance(item, dict)]

    def _restore_snapshot_head(self, head: dict[str, object]) -> None:
        oid = str(head.get("oid") or "")
        reference = head.get("ref")
        if not oid:
            raise RuntimeError("Orbit repository snapshot has no HEAD object")
        if isinstance(reference, str) and reference:
            self._git(["symbolic-ref", "HEAD", reference])
            self._git(["update-ref", reference, oid])
            return
        self._git(["update-ref", "--no-deref", "HEAD", oid])

    def _remove_paths_not_in_snapshot(self, expected_paths: set[str]) -> None:
        """Remove worktree entries absent from the saved tree, never touching .git."""
        for current, directory_names, file_names in os.walk(
            self.project_root, topdown=False, followlinks=False
        ):
            directory = Path(current)
            relative_directory = directory.relative_to(self.project_root)
            if relative_directory.parts and ".git" in relative_directory.parts:
                continue
            for name in file_names:
                target = directory / name
                relative = target.relative_to(self.project_root).as_posix()
                if relative not in expected_paths:
                    target.unlink(missing_ok=True)
            for name in directory_names:
                target = directory / name
                if target.name == ".git" and directory == self.project_root:
                    continue
                relative = target.relative_to(self.project_root).as_posix()
                if target.is_symlink():
                    if relative not in expected_paths:
                        target.unlink(missing_ok=True)
                elif relative not in expected_paths:
                    try:
                        target.rmdir()
                    except OSError:
                        pass

    def restore_repository_snapshot(self, snapshot_id: str) -> dict[str, object]:
        """Restore a repository snapshot without checking out or creating a commit.

        Restoring returns the target worktree, index, and HEAD reference to the
        recorded state. It also removes files created after the snapshot,
        including ignored and untracked files inside the target repository.
        Call this only while Orbit exclusively owns the target repository.

        Args:
            snapshot_id: Identifier returned by :meth:`snapshot_repository`.

        Returns:
            Restored snapshot metadata and restoration timestamp.
        """
        self._git_repository_root()
        _, _, manifest = self._snapshot_manifest()
        snapshots = manifest["snapshots"]
        assert isinstance(snapshots, list)
        snapshot = next(
            (item for item in snapshots if isinstance(item, dict) and item.get("id") == snapshot_id), None
        )
        if snapshot is None:
            raise KeyError(f"unknown repository snapshot: {snapshot_id}")
        worktree_tree = str(snapshot.get("worktree_tree") or "")
        index_tree = str(snapshot.get("index_tree") or "")
        head = snapshot.get("head")
        if not worktree_tree or not index_tree or not isinstance(head, dict):
            raise RuntimeError(f"Orbit repository snapshot is incomplete: {snapshot_id}")
        expected_paths = self._tree_paths(worktree_tree)
        temporary_environment, temporary_index = self._temporary_index_environment()
        try:
            self._git(["read-tree", "--reset", "-u", worktree_tree], environment=temporary_environment)
        finally:
            temporary_index.unlink(missing_ok=True)
            temporary_index.with_name(f"{temporary_index.name}.lock").unlink(missing_ok=True)
        self._remove_paths_not_in_snapshot(expected_paths)
        for relative in snapshot.get("empty_directories", []):
            if not isinstance(relative, str) or not relative:
                continue
            target = (self.project_root / relative).resolve()
            if target != self.project_root and self.project_root not in target.parents:
                raise RuntimeError("Orbit repository snapshot contains an unsafe empty directory")
            target.mkdir(parents=True, exist_ok=True)
        self._restore_snapshot_head(head)
        self._git(["read-tree", index_tree])
        result = {
            "id": snapshot_id,
            "label": snapshot.get("label"),
            "worktree_tree": worktree_tree,
            "restored_at": datetime.now(UTC).isoformat(),
        }
        self.emit_result({"repository_restore": result})
        return result

    def save_before_each_snapshot(self) -> dict[str, object]:
        """Save this run's baseline once from a ``before_each`` handler.

        Returns:
            Baseline snapshot metadata, reusing an existing baseline for this run.
        """
        if self.phase != "before_each":
            raise ValueError("baseline snapshots may only be saved during before_each")
        return self.snapshot_repository("baseline", once=True)

    def save_first_after_each_snapshot(self) -> dict[str, object] | None:
        """Save the first completed iteration from an ``after_each`` handler.

        Returns:
            First-iteration snapshot metadata, or ``None`` after iteration one.
        """
        if self.phase != "after_each":
            raise ValueError("iteration snapshots may only be saved during after_each")
        if self.loop_index != 1:
            return None
        return self.snapshot_repository("iteration-1", once=True)

    def restore_before_each_snapshot(self) -> dict[str, object]:
        """Restore the baseline saved by :meth:`save_before_each_snapshot` in ``after_all``.

        Returns:
            Restored baseline metadata.
        """
        if self.phase != "after_all":
            raise ValueError("baseline restoration may only be performed during after_all")
        baseline = next(
            (
                item
                for item in self.repository_snapshots()
                if item.get("run_id") == self.environment.get("ORBIT_RUN_ID", "manual")
                and item.get("label") == "baseline"
            ),
            None,
        )
        if baseline is None:
            raise KeyError("this run has no baseline repository snapshot")
        return self.restore_repository_snapshot(str(baseline["id"]))

    # Compatibility aliases for runner assets created before the generic
    # lifecycle vocabulary. New assets should use the methods above.
    save_setup_snapshot = save_before_each_snapshot
    save_first_teardown_snapshot = save_first_after_each_snapshot
    restore_setup_snapshot = restore_before_each_snapshot

    def record_commit_change(self, before: str | None) -> dict[str, object] | None:
        """Retain commit-range evidence when a runner phase advances the target HEAD.

        Args:
            before: Commit SHA observed before the runner action.

        Returns:
            Commit-range evidence when HEAD changed, otherwise ``None``.
        """
        after = self.git_head()
        if not before or not after or before == after:
            return None
        changed = subprocess.run(
            ["git", "diff", "--name-only", f"{before}..{after}"],
            cwd=self.project_root,
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.splitlines()
        commits = subprocess.run(
            ["git", "log", "--format=%H%x1f%s", f"{before}..{after}"],
            cwd=self.project_root,
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.splitlines()
        patch = subprocess.run(
            ["git", "diff", "--binary", f"{before}..{after}"],
            cwd=self.project_root,
            env=self.environment,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout
        commit_records = [
            {"sha": value.split("\x1f", 1)[0], "subject": value.split("\x1f", 1)[1]}
            for value in commits
            if "\x1f" in value
        ]
        result: dict[str, object] = {
            "before": before,
            "after": after,
            "changed_paths": changed,
            "commits": commit_records,
        }
        if patch:
            result["diff_artifact"] = self.write_artifact(
                f"commits/{before[:12]}..{after[:12]}.patch",
                patch,
                content_type="text/x-diff",
            )
        self.emit_result({"commit_change": result})
        return result

    def windows_path(self, value: str | Path) -> str:
        """Convert a WSL-mounted path to a Windows path for a Windows child process.

        Args:
            value: Path below a WSL ``/mnt/<drive>`` mount.

        Returns:
            Equivalent Windows drive path.
        """
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
        if written is not None:
            snapshot_name = f"versions/{sequence:06d}-{written_state['sha256'][:16]}-written.bin"
            _atomic_write(directory / snapshot_name, written)
            written_state["snapshot"] = snapshot_name
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

        Args:
            relative_path: Target-repository-relative file path to update.
            content: UTF-8 text or raw bytes to write.
            encoding: Encoding used when ``content`` is text.

        Returns:
            Change status, content hash, target path, and retained version metadata.
        """
        target, relative, directory, manifest_path, manifest = self._load_file_history(relative_path)
        build = self.build
        managed_prompt_path = str(build.get("managed_prompt_path") or build.get("prompt_bundle") or "")
        requires_human_approval = bool(build.get("require_human_approval_before_apply", False))
        if requires_human_approval and relative == managed_prompt_path:
            # This guard lives in the SDK rather than only in a runner template,
            # so existing saved native-improvement runners cannot bypass the
            # Build-level approval policy.
            current = target.read_bytes() if target.exists() else b""
            result = {
                "changed": False,
                "path": relative,
                "sha256": _sha256(current),
                "version": None,
                "reason": "awaiting_human_approval",
            }
            self.emit_result({"file_update_blocked": result})
            return result
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
        """List retained pre-update versions for a project file, newest first.

        Args:
            relative_path: Target-repository-relative file path.

        Returns:
            Retained version metadata ordered newest first.
        """
        _, _, _, _, manifest = self._load_file_history(relative_path)
        return list(reversed(manifest["history"]))

    def rollback_file(self, relative_path: str | Path, version_id: str) -> dict[str, object]:
        """Restore the pre-update state retained by ``version_id``.

        Rolling back first snapshots the current file as a new version. This
        makes a rollback reversible: call this method again using that newly
        returned version ID to return to the state before the rollback.

        Args:
            relative_path: Target-repository-relative file path to restore.
            version_id: Retained version identifier to restore.

        Returns:
            Restored path, selected version ID, and metadata for the new rollback version.
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
        """Return recorded accepted/rejected proposals for this target, newest first.

        Returns:
            Proposal decision and application events ordered newest first.
        """
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

        Args:
            proposal: JSON-safe proposal payload being decided.
            decision: ``"accepted"`` or ``"rejected"``.
            proposal_id: Optional stable external identifier for the proposal.
            rationale: Optional human-readable decision reason.

        Returns:
            Whether an event was newly recorded and its decision record.
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
        build = self.build
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
            "build_id": build.get("id") or None,
            "build_name": build.get("name") or None,
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

        Args:
            proposal_ids: Accepted proposal identifiers linked to the file update.
            file_update: Metadata returned by :meth:`update_file`.

        Returns:
            Newly recorded proposal-application events.
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
        build = self.build
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
                "build_id": build.get("id") or None,
                "build_name": build.get("name") or None,
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
        """Record that a proposal was selected for this target's improvement history.

        Args:
            proposal: JSON-safe proposal payload to accept.
            proposal_id: Optional stable external proposal identifier.
            rationale: Optional human-readable acceptance reason.

        Returns:
            Whether an event was newly recorded and its decision record.
        """
        return self.record_proposal_decision(
            proposal, "accepted", proposal_id=proposal_id, rationale=rationale
        )

    def reject_proposal(
        self, proposal: dict[str, object], *, proposal_id: str | None = None, rationale: str = ""
    ) -> dict[str, object]:
        """Record that a proposal was not selected for this target's improvement history.

        Args:
            proposal: JSON-safe proposal payload to reject.
            proposal_id: Optional stable external proposal identifier.
            rationale: Optional human-readable rejection reason.

        Returns:
            Whether an event was newly recorded and its decision record.
        """
        return self.record_proposal_decision(
            proposal, "rejected", proposal_id=proposal_id, rationale=rationale
        )

    @property
    def workflow(self) -> dict[str, object]:
        """Return the workflow snapshot supplied by Orbit for this invocation.

        Returns:
            Immutable workflow metadata, or an empty mapping when unavailable.
        """
        return dict(self.resources.get("workflow", {}))

    @property
    def build(self) -> dict[str, object]:
        """Return the build snapshot supplied by Orbit.

        Returns:
            Immutable build metadata, or an empty mapping when unavailable.
        """
        return dict(self.resources.get("build", {}))

    @property
    def test_cases(self) -> list[dict[str, object]]:
        """Return the fixed target test cases selected for this build.

        Returns:
            Selected fixed test-case definitions.
        """
        return list(self.resources.get("test_cases", []))

    def require_test_case_ids(
        self, required_ids: set[str] | list[str] | tuple[str, ...], *, label: str = "required test case"
    ) -> None:
        """Require that the declared fixed cases include every requested ID.

        Args:
            required_ids: Stable test-case IDs that must be selected.
            label: Singular description used in an actionable validation error.
        """
        required = {str(case_id) for case_id in required_ids if str(case_id).strip()}
        selected = {str(case.get("id", "")) for case in self.test_cases}
        missing = sorted(required - selected)
        if missing:
            raise ValueError(f"Missing {label}: {', '.join(missing)}")

    def resource(self, name: str, default: object = None) -> object:
        """Read a named value from Orbit's immutable resource snapshot.

        Args:
            name: Resource name, such as ``"model_profile"``.
            default: Value returned when the resource is absent.

        Returns:
            The requested resource value or ``default`` when it is absent.
        """
        return self.resources.get(name, default)

    def complete_model(self, prompt: str) -> dict[str, str]:
        """Run one target-AI turn using the build's configured model profile.

        The profile contains provider settings only; its credential remains in
        the configured environment variable and is never emitted as evidence.

        Args:
            prompt: Target-AI input to send using the configured model profile.

        Returns:
            Profile name, resolved model name, and target-AI response text.
        """
        profile = self.resource("model_profile", {})
        if not isinstance(profile, dict) or not str(profile.get("model", "")).strip():
            raise ValueError("a configured model profile is required for a target-AI turn")
        from app.providers import AzureOpenAIProvider, BedrockProvider, ModelSettings

        settings = ModelSettings(
            provider=str(profile.get("provider", "azure-openai")),
            model=str(profile["model"]),
            endpoint=str(profile.get("endpoint", "")),
            region=str(profile.get("region", "us-east-1")),
            secret_env=str(profile.get("secret_env", "AZURE_OPENAI_API_KEY")),
            aws_profile=str(profile.get("aws_profile", "")),
        )
        provider = AzureOpenAIProvider() if settings.provider == "azure-openai" else BedrockProvider()
        self.log(f"target model request started: {settings.provider}/{settings.model}")
        self.target_log(
            f"Model request started: {settings.provider}/{settings.model}",
            source="target-model",
        )
        response = provider.complete(settings, prompt)
        self.log(f"target model request completed: {settings.provider}/{settings.model}")
        self.target_log(
            f"Model request completed: {settings.provider}/{settings.model}",
            source="target-model",
        )
        return {
            "profile_name": str(profile.get("profile_name", "")),
            "model": settings.model,
            "response": response,
        }

    def complete_model_json(self, prompt: str, *, description: str = "model response") -> dict[str, object]:
        """Run one target-AI turn and require a JSON object response.

        Use this when a runner's prompt explicitly contracts the model to emit
        structured data. The raw text remains available through
        :meth:`complete_model` for free-form model tasks.
        """
        return self.parse_json_object(self.complete_model(prompt)["response"], description=description)

    @property
    def previous_supervisor_feedback(self) -> dict[str, object]:
        """Return the latest completed supervisor response for this run.

        Runner phases run in separate subprocesses.  Reading the retained run
        record lets the next iteration use the previous iteration's feedback
        without coupling a runner to a target-specific state file.

        Returns:
            Latest completed supervisor response, or an empty mapping when unavailable.
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
        selected_candidates = values.get("iteration_candidates", [])
        winner_ids = {
            str(item.get("id"))
            for item in selected_candidates
            if isinstance(item, dict) and item.get("selected")
        }
        if winner_ids:
            records = sorted(
                records,
                key=lambda record: (
                    isinstance(record, dict) and str(record.get("candidate_id")) in winner_ids,
                    record.get("iteration", 0) if isinstance(record, dict) else 0,
                ),
            )
        for record in reversed(records):
            response = record.get("response") if isinstance(record, dict) else None
            if isinstance(response, dict):
                feedback = dict(response)
                improvements = feedback.get("improvements", [])
                if isinstance(improvements, list):
                    iteration = record.get("iteration", 0)
                    feedback["_orbit_proposal_ids"] = [
                        f"{run_id}:{iteration}:{index}"
                        for index, proposal in enumerate(improvements)
                        if isinstance(proposal, dict)
                        and str(proposal.get("status") or "").lower() == "accepted"
                    ]
                return feedback
        return {}

    @property
    def current_issue_assessment(self) -> dict[str, object]:
        """Return this iteration's first supervisor-assessed actionable issue.

        The post-supervision agent phase uses this as its sole objective.  A
        rejected issue is deliberately returned too, so the runner can record
        an explicit skip rather than treating absence as approval.
        """
        run_id = self.environment.get("ORBIT_RUN_ID", "").strip()
        if not run_id:
            return {}
        try:
            values = json.loads(
                (self.app_data / "data" / "runs" / f"{run_id}.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {}
        for record in reversed(values.get("supervisor_results", [])):
            if not isinstance(record, dict) or record.get("stage") != "issue_assessment":
                continue
            if int(record.get("iteration", 0)) != self.loop_index:
                continue
            response = record.get("response")
            if not isinstance(response, dict):
                continue
            issues = response.get("reported_issues")
            improvements = response.get("improvements")
            # Manager templates commonly express a discovered product problem
            # as an improvement proposal.  It is still an Issue for this
            # lifecycle once the supervisor has scored and decided it. Prefer
            # that user-facing proposal so the agent changes the same Issue
            # shown in Issue Management rather than creating a parallel row.
            candidates = [
                {**improvement, "_orbit_issue_id": f"{run_id}:{self.loop_index}:{index}"}
                for index, improvement in enumerate(improvements)
                if isinstance(improvements, list) and isinstance(improvement, dict)
            ]
            candidates.extend(
                {**issue, "_orbit_issue_id": f"{run_id}:{self.loop_index}:issue:{index}"}
                for index, issue in enumerate(issues)
                if isinstance(issues, list) and isinstance(issue, dict)
            )
            if candidates:
                for issue in candidates:
                    assessment = issue.get("evaluation")
                    if not isinstance(assessment, dict) or assessment.get("approval") != "rejected":
                        return issue
                return candidates[0] if candidates else {}
        return {}

    def log(self, message: str) -> None:
        """Write an Orbit runner-progress message to the workflow log.

        This is for runner lifecycle and adapter progress. It is intentionally
        different from :meth:`target_log`, which records events emitted by the
        evaluated target and appears separately in the run's Logs tab.

        Args:
            message: Human-readable lifecycle progress message.

        Returns:
            ``None``. The message is written to runner output.
        """
        print(f"[orbit:{self.phase}] {message}", flush=True)

    def target_log(
        self,
        message: str,
        *,
        level: str = "info",
        source: str = "",
        timestamp: str | None = None,
    ) -> None:
        """Attach one bounded log line produced by the evaluation target.

        Target logs are kept separately from Orbit's runner and workflow output.
        Call this from an adapter after it has collected a relevant target-side
        event; it is not intended to mirror the runner's own stdout. Orbit adds
        the run ID, iteration, and lifecycle phase before retaining the entry.

        Args:
            message: Non-empty target event text. It is trimmed to 4,000 characters.
            level: One of ``debug``, ``info``, ``warn``, ``warning``, or ``error``.
            source: Optional stable target-service name, trimmed to 256 characters.
            timestamp: Optional ISO-8601 timestamp. UTC time is used when omitted.

        Returns:
            ``None``. The target log entry is attached to current-step evidence.

        Raises:
            ValueError: If the message is empty, level is unsupported, or timestamp
                is not a string.
        """
        if not isinstance(message, str) or not message.strip():
            raise ValueError("target log message must be a non-empty string")
        normalized_level = str(level).strip().lower()
        if normalized_level not in {"debug", "info", "warn", "warning", "error"}:
            raise ValueError("target log level must be debug, info, warn, warning, or error")
        if timestamp is not None and not isinstance(timestamp, str):
            raise ValueError("target log timestamp must be a string")
        self.emit_result(
            {
                "target_logs": [
                    {
                        "timestamp": timestamp or datetime.now(UTC).isoformat(),
                        "level": normalized_level,
                        "source": str(source).strip()[:256],
                        "message": message.strip()[:4000],
                        "run_id": self.environment.get("ORBIT_RUN_ID", ""),
                        "iteration": self.loop_index,
                        "phase": self.phase,
                    }
                ]
            }
        )

    def emit_result(self, values: dict[str, object]) -> None:
        """Attach JSON-safe structured evidence to the current Orbit step.

        Use this for machine-consumed evidence such as scores, metrics, or
        proposal records. Values must be JSON serializable. Repeated result
        objects are merged by key, so prefer a single object for related data;
        use :meth:`target_log` for append-only target logging.

        Args:
            values: JSON-safe evidence object to attach to the current step.

        Returns:
            ``None``. The evidence is emitted to Orbit's runner protocol.
        """
        print("__ORBIT_RESULT__" + json.dumps(values, ensure_ascii=False), flush=True)

    def register_evaluation(
        self,
        feedback: str,
        *,
        subject: str = "agent_change",
        changed_files: list[str] | None = None,
        validation: str = "",
        improvement_fingerprint: str = "",
    ) -> dict[str, object]:
        """Register an AI-agent result that should receive a supervisor evaluation.

        Register only after the agent has completed a meaningful change or
        produced actionable feedback.  Merely running an iteration does not
        create an evaluation, score, or approval decision.

        Args:
            feedback: Concise account of the agent's completed work and its evidence.
            subject: Stable evaluation subject.  ``agent_change`` is the supported
                default for autonomous SDK agents.
            changed_files: Repository-relative files changed by the agent, if any.
            validation: Verification performed by the agent after its work.

        Returns:
            The structured evaluation request emitted for the current step.
        """
        normalized_feedback = feedback.strip()
        if not normalized_feedback:
            raise ValueError("evaluation feedback must not be empty")
        if subject != "agent_change":
            raise ValueError("evaluation subject must be agent_change")
        normalized_files = [
            str(path).strip() for path in (changed_files or []) if isinstance(path, str) and path.strip()
        ]
        request = {
            "subject": subject,
            "feedback": normalized_feedback,
            "changed_files": list(dict.fromkeys(normalized_files)),
            "validation": validation.strip(),
            "improvement_fingerprint": improvement_fingerprint.strip(),
        }
        self.emit_result({"evaluation_request": request})
        return request

    def run_ai_agent(
        self,
        prompt: str,
        *,
        provider: str,
        options: str = "",
        timeout: int = 1_800,
    ) -> dict[str, object]:
        """Run a locally installed coding agent and retain its completion evidence.

        The agent must print ``ORBIT_AGENT_FEEDBACK: <summary>`` as its final
        feedback line to opt its work into evaluation.  This keeps a silent or
        no-op agent run from creating a score for the iteration.
        """
        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise ValueError("AI agent prompt must not be empty")
        # Agent edits are proposals, never writes to the evaluated repository.
        # A proposal branch/worktree gives the coding agent a real Git checkout while
        # preserving the operator's working tree and its uncommitted changes.
        self._git_repository_root()
        run_id = str(self.environment.get("ORBIT_RUN_ID") or "manual")
        worktree_id = f"{run_id}-{self.loop_index}-{uuid.uuid4().hex[:8]}"
        worktree = ORBIT_APP_DATA / "agent-worktrees" / worktree_id
        worktree.parent.mkdir(parents=True, exist_ok=True)
        base_revision = self.git_head()
        if not base_revision:
            raise ValueError("AI agent proposals require a checked-out Git revision")
        branch = f"orbit/agent-proposal/{run_id}/{self.loop_index}-{uuid.uuid4().hex[:8]}"
        self.exec(
            ["git", "worktree", "add", "-b", branch, str(worktree), base_revision],
            cwd=self.project_root,
            target_log_source="ai-agent",
        )
        output = ""
        changed_files: list[str] = []
        patch = ""
        keep_worktree = False
        try:
            output = self.exec(
                build_coding_agent_command(provider, options=options, prompt=normalized_prompt),
                cwd=worktree,
                timeout=timeout,
                target_log_source="ai-agent",
            )
            # Include newly-created files in the review patch without creating
            # a commit.  Intent-to-add is local to this disposable proposal
            # worktree and is finalized only after Issue approval.
            self.exec(["git", "add", "--intent-to-add", "--all"], cwd=worktree)
            changed_files = [
                line
                for line in self.exec(["git", "diff", "--name-only", "--"], cwd=worktree).splitlines()
                if line
            ]
            patch = self.exec(["git", "diff", "--binary", "--"], cwd=worktree)
            feedback = next(
                (
                    line.removeprefix("ORBIT_AGENT_FEEDBACK:").strip()
                    for line in reversed(output.splitlines())
                    if line.startswith("ORBIT_AGENT_FEEDBACK:")
                    and line.removeprefix("ORBIT_AGENT_FEEDBACK:").strip()
                ),
                "",
            )
            keep_worktree = bool(feedback and patch)
        finally:
            if not keep_worktree:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    cwd=self.project_root,
                    env=self.environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    cwd=self.project_root,
                    env=self.environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        artifact = (
            self.write_artifact(f"agent-proposals/{worktree_id}.patch", patch, content_type="text/x-diff")
            if patch
            else None
        )
        result = {
            "provider": provider,
            "feedback": feedback,
            "changed_files": changed_files,
            "output": output[-12_000:],
            "proposal": {
                "worktree_id": worktree_id,
                "base_revision": base_revision,
                "branch": branch if keep_worktree else "",
                "worktree_path": str(worktree) if keep_worktree else "",
                "diff": patch,
                "fingerprint": _sha256(patch.encode("utf-8")) if patch else "",
                "diff_artifact": artifact,
            },
        }
        self.emit_result({"agent_run": result})
        return result

    def playwright_journey(self, cases: list[dict[str, object]] | None = None) -> dict[str, object]:
        """Run bounded, read-only Playwright page checks for the supplied cases.

        The browser process is short lived.  Scheduling, locking, and any
        application-server lifecycle remain Orbit's responsibility.

        Args:
            cases: Optional fixed cases to run. The build's selected cases are used when omitted.

        Returns:
            Per-case pass/fail evidence, screenshots, page HTML, and artifact directory metadata.
        """
        build = self.build
        base_url = str(
            build.get("browser_base_url") or self.environment.get("ORBIT_BROWSER_BASE_URL") or ""
        ).strip()
        if not base_url:
            raise ValueError("browser_base_url is required for a Playwright journey")
        selected_cases = cases if cases is not None else self.test_cases
        if not selected_cases:
            raise ValueError("at least one fixed test case is required for a Playwright journey")
        self.log(f"browser journey started: {len(selected_cases)} case(s) against {base_url}")
        self.target_log(
            f"Playwright journey started: {len(selected_cases)} case(s)",
            source="playwright",
        )
        artifacts = (
            self.app_data
            / "artifacts"
            / self.environment.get("ORBIT_RUN_ID", "manual")
            / f"loop-{self.loop_index}"
        )
        artifacts.mkdir(parents=True, exist_ok=True)
        module = self.environment.get("ORBIT_PLAYWRIGHT_MODULE", "")
        if not module:
            module = str(Path(__file__).resolve().parents[3] / "frontend" / "node_modules" / "playwright")
        payload = {
            "baseUrl": base_url,
            "cases": selected_cases,
            "artifacts": str(artifacts),
            "headless": self.environment.get("ORBIT_BROWSER_HEADLESS", "true") != "false",
            "executablePath": str(build.get("browser_executable_path", "")).strip(),
        }
        script = r"""const fs=require('fs'); const { chromium }=require(process.argv[1]); const input=JSON.parse(process.argv[2]);
(async()=>{const launch={headless:input.headless}; if(input.executablePath)launch.executablePath=input.executablePath; else if(process.env.SIM_BROWSER_BIN)launch.executablePath=process.env.SIM_BROWSER_BIN; const browser=await chromium.launch(launch); const results=[];
for(const item of input.cases){const page=await browser.newPage();const path=String(item.path||'/');const url=new URL(path,input.baseUrl).toString();const id=String(item.id||'case').replace(/[^a-zA-Z0-9_-]/g,'-');const screenshot=`${input.artifacts}/${id}.png`;const html=`${input.artifacts}/${id}.html`;try{await page.goto(url,{waitUntil:'domcontentloaded',timeout:30000});const expected=String(item.expected_text||'').trim();const passed=!expected||await page.getByText(expected,{exact:false}).first().isVisible({timeout:5000});await page.screenshot({path:screenshot,fullPage:true});await fs.promises.writeFile(html,await page.content());results.push({id:item.id,name:item.name,url,passed,expected_text:expected,screenshot,html});}catch(error){try{await page.screenshot({path:screenshot,fullPage:true});await fs.promises.writeFile(html,await page.content());}catch{}results.push({id:item.id,name:item.name,url,passed:false,error:String(error),screenshot,html});}finally{await page.close();}}
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
        passed = sum(bool(item.get("passed")) for item in evidence.get("results", []))
        self.log(f"browser journey completed: {passed}/{len(selected_cases)} case(s) passed")
        self.target_log(
            f"Playwright journey completed: {passed}/{len(selected_cases)} case(s) passed",
            level="info" if passed == len(selected_cases) else "warn",
            source="playwright",
        )
        self.emit_result({"browser_journey": evidence})
        return evidence

    def exec(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
        input: str | None = None,
        target_log_source: str | None = None,
        target_log_exclude_prefixes: tuple[str, ...] = (),
        merge_stderr: bool = True,
    ) -> str:
        """Run one bounded child command and return its captured output.

        A runner phase is deliberately not a scheduler.  Returning the output
        lets a phase turn its one-shot result into Orbit-owned structured
        evidence without starting a persistent child daemon.

        Args:
            command: Executable and arguments, passed without a shell.
            cwd: Child working directory; defaults to the target repository.
            timeout: Maximum duration in seconds; no timeout when omitted.
            env: Environment values that supplement the runner environment.
            input: Optional standard input sent to the child before its output
                is collected.
            target_log_source: When set, forward bounded child-output lines to
                the target-log stream under this source name.
            target_log_exclude_prefixes: Output prefixes retained for the caller
                but excluded from target logs, for structured child results.
            merge_stderr: When ``True`` (the default), include standard error in
                the returned output. Set to ``False`` when a child reserves
                standard output for a machine-readable response; standard error
                is still printed and forwarded to target logs.

        Returns:
            Standard output, plus standard error when ``merge_stderr`` is true.

        Raises:
            subprocess.TimeoutExpired: If the child exceeds ``timeout``.
            SystemExit: If the child exits with a non-zero status.
        """
        self.log(f"exec: {' '.join(command)}")
        process = subprocess.Popen(
            command,
            cwd=cwd or self.target_repository,
            env={**self.environment, **(env or {})},
            text=True,
            stdin=subprocess.PIPE if input is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
        )
        lines: list[str] = []

        if input is not None:
            assert process.stdin is not None
            process.stdin.write(input)
            process.stdin.close()

        def forward_output(stream, *, retain: bool) -> None:
            for line in stream:
                if retain:
                    lines.append(line)
                print(line, end="", flush=True)
                if target_log_source and line.strip() and not line.startswith(target_log_exclude_prefixes):
                    self.target_log(line.strip(), source=target_log_source)

        assert process.stdout is not None
        readers = [
            threading.Thread(
                target=forward_output, args=(process.stdout,), kwargs={"retain": True}, daemon=True
            )
        ]
        if not merge_stderr:
            assert process.stderr is not None
            readers.append(
                threading.Thread(
                    target=forward_output, args=(process.stderr,), kwargs={"retain": False}, daemon=True
                )
            )
        for reader in readers:
            reader.start()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        finally:
            for reader in readers:
                reader.join()
        output = "".join(lines)
        if process.returncode:
            self.log(f"exec failed with exit code {process.returncode}: {' '.join(command)}")
            raise SystemExit(process.returncode)
        self.log(f"exec completed: {' '.join(command)}")
        return output

    def command_from_env(self, command_env: str) -> list[str]:
        """Parse one externally configured command from the runner environment.

        The value may be a shell-style command string or a JSON array of
        strings. The executable must be present; empty arguments remain valid
        because some tools use them intentionally.
        """
        return command_from_environment(self.environment, command_env)

    def run_command_action(
        self,
        *,
        command_env: str,
        action: str,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
        log_source: str | None = None,
        log_exclude_prefixes: tuple[str, ...] = (),
        stdout_only: bool = False,
    ) -> str:
        """Run one action of an externally configured command.

        Args:
            command_env: Environment variable holding the command configuration.
            action: Final argument passed to the external command.
            timeout: Maximum duration in seconds.
            env: Additional environment values for the child command.
            log_source: Optional target-log source for child output.
            log_exclude_prefixes: Child-output prefixes excluded from target logs.
            stdout_only: Return only stdout, preserving stderr for logs. Use for
                commands whose stdout is a structured response.
        """
        return self.exec(
            [*self.command_from_env(command_env), action],
            cwd=self.project_root,
            timeout=timeout,
            env=env,
            target_log_source=log_source,
            target_log_exclude_prefixes=log_exclude_prefixes,
            merge_stderr=not stdout_only,
        )

    def parse_json_object(self, output: str, *, description: str = "command output") -> dict[str, object]:
        """Parse and require exactly one JSON object from command output."""
        try:
            result = json.loads(output)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"{description} did not return JSON") from error
        if not isinstance(result, dict):
            raise RuntimeError(f"{description} must return a JSON object")
        return result

    def run_json_action(
        self,
        *,
        command_env: str,
        action: str,
        input_env: str,
        input_data: dict[str, object],
        timeout: int | None = None,
        log_source: str | None = None,
    ) -> dict[str, object]:
        """Run one external action that returns a JSON object on standard output."""
        payload = json.dumps({**input_data, "action": action}, ensure_ascii=False)
        output = self.run_command_action(
            command_env=command_env,
            action=action,
            timeout=timeout,
            env={input_env: payload},
            log_source=log_source,
            stdout_only=True,
        )
        return self.parse_json_object(output, description=f"Action {action!r}")

    def require_test_cases(self, *, label: str = "fixed test case") -> None:
        """Require at least one declared fixed test case for a runner contract."""
        if not self.test_cases:
            raise ValueError(f"Select at least one {label}")
