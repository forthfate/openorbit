# OpenOrbit runner SDK

Use `orbit_sdk` in a runner asset to implement one bounded action for each
OpenOrbit lifecycle phase. OpenOrbit owns scheduling, retries, process control,
and retained run history; runner code reports evidence through `ctx`.

## Minimal runner

```python
from orbit_sdk import runner


@runner.phase("execute")
def execute(ctx):
    ctx.log("Running one bounded target check")


if __name__ == "__main__":
    runner.main()
```

Available phases are `before_all`, `before_each`, `execute`, `verify`,
`after_each`, and `after_all`. A runner process receives exactly one phase
invocation.

## Restore a Git-backed target after evaluation

For an evaluation that changes its target repository, retain a baseline in
`before_each` and restore it in `after_all`. The SDK writes content-addressed Git
blob/tree objects through a temporary index; it does **not** create a commit,
branch, tag, or entry in the target's history. A private `refs/orbit/snapshots`
ref only keeps the otherwise-uncommitted objects alive for later restoration.

```python
from orbit_sdk import runner


@runner.phase("before_each")
def before_each(ctx):
    # `before_each` can run once per iteration; this records the run baseline once.
    ctx.save_before_each_snapshot()


@runner.phase("after_each")
def after_each(ctx):
    # Retain the first evaluated state as an iteration-linked checkpoint.
    ctx.save_first_after_each_snapshot()


@runner.phase("after_all")
def after_all(ctx):
    # Restore the original worktree, staging area, and HEAD state.
    ctx.restore_before_each_snapshot()


if __name__ == "__main__":
    runner.main()
```

## Declare a visual workflow graph

Import `graph` alongside `runner` to annotate visual nodes without changing
the runner's execution behavior. A node may belong to any phase name; the
visual client groups nodes by the supplied value instead of assuming a fixed
lifecycle. Typed arrows represent execution, data, conditions, loops, and
error handling.

```python
from orbit_sdk import graph, runner


@graph.step("collect-evidence", phase="before_each", outputs=["evidence"])
def collect_evidence(ctx):
    ...


@graph.step("verify-outcome", phase="verify", inputs=["evidence"])
def verify_outcome(ctx):
    ...


graph.connect("collect-evidence", "verify-outcome", kind="data", label="evidence")
graph.connect("verify-outcome", "collect-evidence", kind="loop", label="next iteration")
```

Call `graph.definition()` to obtain JSON-safe `nodes` and `edges` for a
source inspector or visual client. Node IDs are stable join keys for future
runtime status, logs, timings, and artifacts.

Snapshots include tracked, staged, untracked, and ignored files, plus file
modes and symbolic links. They also preserve empty directories in Orbit's
private snapshot manifest. The target must be a Git worktree root and remain
exclusively owned by the evaluation while restoration is possible. Submodule
contents are not recursively snapshotted.

Use `ctx.snapshot_repository(label)` and
`ctx.restore_repository_snapshot(snapshot_id)` when a runner needs additional
named checkpoints. Snapshot metadata includes the run ID, iteration, phase,
and tree hashes; `ctx.repository_snapshots()` lists retained checkpoints.

## Save an iteration data file

Call `save_data_file` at any point a runner wants to retain and expose data for
the currently selected iteration. `label` is a display name, not the actual
filename; the Cycle Improvement AI proposal-decision history shows it beside
independently copyable file name and AppData path.

```python
ctx.save_data_file(
    "reports/verification.json",
    json.dumps(report),
    label="Verification report after retry",
    content_type="application/json",
)
```

## Local preview and build

Start a local documentation site:

```bash
pnpm run docs:serve
```

Build static files for hosting or embedding elsewhere:

```bash
pnpm run docs:build
```

The generated site is written to `site/`. The API reference is generated from
the SDK module and its docstrings at build time.
