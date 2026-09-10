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
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal

PROJECT_ROOT = Path(os.environ.get("ORBIT_TARGET_REPOSITORY", Path.cwd())).resolve()
ORBIT_APP_DATA = Path(os.environ.get("ORBIT_APP_DATA", Path.home() / ".local" / "share" / "orbit")).resolve()

# Accept pre-1.0 lifecycle names in existing runner files while emitting the
# canonical names everywhere else.
PHASE_ALIASES = {
    "init": "before_all",
    "setup": "before_each",
    "run": "execute",
    "eval": "verify",
    "teardown": "after_each",
    "finalize": "after_all",
}


def canonical_phase(name: str) -> str:
    """Return the canonical lifecycle key for a current or legacy phase."""
    return PHASE_ALIASES.get(name, name)


@dataclass(frozen=True)
class GraphNode:
    """A declarative visual-workflow node attached to a runner function."""

    id: str
    title: str
    phase: str | None
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    description: str | None = None


@dataclass(frozen=True)
class GraphEdge:
    """A directed relationship between visual-workflow nodes."""

    source: str
    target: str
    kind: Literal["execution", "data", "condition", "loop", "error"] = "execution"
    label: str | None = None
    source_port: str | None = None
    target_port: str | None = None


class Graph:
    """Declare a runner's visual workflow without changing its execution.

    ``graph`` is intentionally declarative: decorators only retain metadata.
    Orbit may inspect :meth:`definition` before a run, then overlay runtime
    status onto the same node IDs after a run.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []

    def step(
        self,
        id: str | None = None,
        *,
        title: str | None = None,
        phase: str | None = None,
        inputs: tuple[str, ...] | list[str] = (),
        outputs: tuple[str, ...] | list[str] = (),
        description: str | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Annotate one function as a visual workflow node.

        ``phase`` is an optional display group, not a hard-coded lifecycle
        enum, so a runner can evolve its lifecycle without changing this API.
        """

        def register(handler: Callable[..., Any]) -> Callable[..., Any]:
            node_id = id or handler.__name__
            if not node_id or node_id in self._nodes:
                raise ValueError(f"graph node ID must be unique: {node_id!r}")
            node = GraphNode(
                id=node_id,
                title=title or handler.__name__.replace("_", " ").title(),
                phase=phase,
                inputs=tuple(inputs),
                outputs=tuple(outputs),
                description=description,
            )
            self._nodes[node_id] = node
            setattr(handler, "__orbit_graph_node__", node)
            return handler

        return register

    def connect(
        self,
        source: str,
        target: str,
        *,
        kind: Literal["execution", "data", "condition", "loop", "error"] = "execution",
        label: str | None = None,
        source_port: str | None = None,
        target_port: str | None = None,
    ) -> GraphEdge:
        """Declare a typed arrow; ``loop`` and ``condition`` model control flow."""
        edge = GraphEdge(source, target, kind, label, source_port, target_port)
        self._edges.append(edge)
        return edge

    def definition(self) -> dict[str, object]:
        """Return JSON-safe graph data for a visual client or source inspector."""
        return {
            "nodes": [
                {
                    "id": node.id,
                    "title": node.title,
                    "phase": node.phase,
                    "inputs": list(node.inputs),
                    "outputs": list(node.outputs),
                    "description": node.description,
                }
                for node in self._nodes.values()
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "kind": edge.kind,
                    "label": edge.label,
                    "source_port": edge.source_port,
                    "target_port": edge.target_port,
                }
                for edge in self._edges
            ],
        }


graph = Graph()


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

    def __post_init__(self) -> None:
        self.phase = canonical_phase(self.phase)

    @property
    def resources(self) -> dict[str, object]:
        """Return the immutable resource snapshot provided for this invocation.

        The snapshot can contain the workflow, build, fixed test
        cases, model profile, and execution-environment settings. Prefer the
        typed convenience properties when one is available.
        """
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
        """Return a private, runner-managed AppData directory for a named asset set."""
        if not name or any(part in {"", ".", ".."} for part in Path(name).parts):
            raise ValueError("managed asset name must be a relative, non-empty path")
        directory = self.app_data / "runner-assets" / _sha256(str(self.project_root).encode()) / name
        directory.mkdir(parents=True, exist_ok=True)
        return directory

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
        """Return the checked-out commit, or None when the target is not a Git repository."""
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
        """List retained repository snapshots, newest first."""
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
        """Save this run's baseline once from a ``before_each`` handler."""
        if self.phase != "before_each":
            raise ValueError("baseline snapshots may only be saved during before_each")
        return self.snapshot_repository("baseline", once=True)

    def save_first_after_each_snapshot(self) -> dict[str, object] | None:
        """Save the first completed iteration from an ``after_each`` handler."""
        if self.phase != "after_each":
            raise ValueError("iteration snapshots may only be saved during after_each")
        if self.loop_index != 1:
            return None
        return self.snapshot_repository("iteration-1", once=True)

    def restore_before_each_snapshot(self) -> dict[str, object]:
        """Restore the baseline saved by :meth:`save_before_each_snapshot` in ``after_all``."""
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
        """Retain commit-range evidence when a runner phase advances the target HEAD."""
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
        """Return the workflow snapshot supplied by Orbit for this invocation."""
        return dict(self.resources.get("workflow", {}))

    @property
    def build(self) -> dict[str, object]:
        """Return the build snapshot supplied by Orbit."""
        return dict(self.resources.get("build", {}))

    @property
    def test_cases(self) -> list[dict[str, object]]:
        """Return the fixed target test cases selected for this build."""
        return list(self.resources.get("test_cases", []))

    def resource(self, name: str, default: object = None) -> object:
        """Read a named value from Orbit's immutable resource snapshot.

        Args:
            name: Resource name, such as ``"model_profile"``.
            default: Value returned when the resource is absent.
        """
        return self.resources.get(name, default)

    def complete_model(self, prompt: str) -> dict[str, str]:
        """Run one target-AI turn using the build's configured model profile.

        The profile contains provider settings only; its credential remains in
        the configured environment variable and is never emitted as evidence.
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
        return {
            "profile_name": str(profile.get("profile_name", "")),
            "model": settings.model,
            "response": provider.complete(settings, prompt),
        }

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
                        and str(proposal.get("status") or "").lower() in {"adopted", "accepted"}
                    ]
                return feedback
        return {}

    def log(self, message: str) -> None:
        """Write an Orbit runner-progress message to the workflow log.

        This is for runner lifecycle and adapter progress. It is intentionally
        different from :meth:`target_log`, which records events emitted by the
        evaluated target and appears separately in the run's Logs tab.
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
        """
        print("__ORBIT_RESULT__" + json.dumps(values, ensure_ascii=False), flush=True)

    def playwright_journey(self, cases: list[dict[str, object]] | None = None) -> dict[str, object]:
        """Run bounded, read-only Playwright page checks for the supplied cases.

        The browser process is short lived.  Scheduling, locking, and any
        application-server lifecycle remain Orbit's responsibility.
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

        Args:
            command: Executable and arguments, passed without a shell.
            cwd: Child working directory; defaults to the target repository.
            timeout: Maximum duration in seconds; no timeout when omitted.
            env: Environment values that supplement the runner environment.

        Returns:
            Combined standard output and standard error from the child.

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
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        lines: list[str] = []

        def forward_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.append(line)
                print(line, end="", flush=True)

        reader = threading.Thread(target=forward_output, daemon=True)
        reader.start()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        finally:
            reader.join()
        output = "".join(lines)
        if process.returncode:
            raise SystemExit(process.returncode)
        return output


class Runner:
    """Register lifecycle handlers and dispatch the phase requested by Orbit."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[RunnerContext], None]] = {}

    def phase(
        self, name: str
    ) -> Callable[[Callable[[RunnerContext], None]], Callable[[RunnerContext], None]]:
        """Register a function as a handler for one runner lifecycle phase.

        Args:
            name: Lifecycle phase name, normally one of ``before_all``,
                ``before_each``, ``execute``, ``verify``, ``after_each``, or
                ``after_all``. Legacy names are accepted for compatibility.

        Returns:
            A decorator that leaves the registered handler unchanged.
        """

        def register(handler: Callable[[RunnerContext], None]) -> Callable[[RunnerContext], None]:
            self._handlers[canonical_phase(name)] = handler
            return handler

        return register

    def main(self) -> None:
        """Dispatch the phase passed by Orbit and retain any commit-range evidence.

        Place ``runner.main()`` behind an ``if __name__ == "__main__"`` guard
        in every runner asset. Orbit supplies the ``--phase`` argument and
        process environment; callers should not invoke this method directly.
        """
        parser = argparse.ArgumentParser(description="Orbit runner phase")
        parser.add_argument("--phase", required=True)
        args = parser.parse_args()
        phase = canonical_phase(args.phase)
        handler = self._handlers.get(phase)
        if handler is None:
            raise SystemExit(f"runner does not define phase: {args.phase}")
        context = RunnerContext(
            phase,
            Path(os.environ["ORBIT_TARGET_REPOSITORY"]),
            os.environ.get("ORBIT_EXECUTION_MODE", "run"),
            int(os.environ.get("ORBIT_LOOP_INDEX", "1")),
        )
        before = context.git_head()
        try:
            handler(context)
        finally:
            try:
                context.record_commit_change(before)
            except (OSError, subprocess.CalledProcessError) as error:
                context.log(f"Could not retain commit-change evidence: {error}")


runner = Runner()
