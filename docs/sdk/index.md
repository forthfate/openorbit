# OpenOrbit runner SDK

Use `orbit_sdk` in a runner asset to implement one bounded action for each
OpenOrbit lifecycle phase. OpenOrbit owns scheduling, retries, process control,
and retained run history; runner code reports evidence through `ctx`.

## Minimal runner

```python
from orbit_sdk import runner


@runner.phase("run")
def run(ctx):
    ctx.log("Running one bounded target check")


if __name__ == "__main__":
    runner.main()
```

Available phases are `init`, `setup`, `run`, `eval`, `teardown`, and
`finalize`. A runner process receives exactly one phase invocation.

## Restore a Git-backed target after evaluation

For an evaluation that changes its target repository, retain a baseline in
`setup` and restore it in `finalize`. The SDK writes content-addressed Git
blob/tree objects through a temporary index; it does **not** create a commit,
branch, tag, or entry in the target's history. A private `refs/orbit/snapshots`
ref only keeps the otherwise-uncommitted objects alive for later restoration.

```python
from orbit_sdk import runner


@runner.phase("setup")
def setup(ctx):
    # `setup` can run once per iteration; this records the run baseline once.
    ctx.save_setup_snapshot()


@runner.phase("teardown")
def teardown(ctx):
    # Retain the first evaluated state as an iteration-linked checkpoint.
    ctx.save_first_teardown_snapshot()


@runner.phase("finalize")
def finalize(ctx):
    # Restore the original worktree, staging area, and HEAD state.
    ctx.restore_setup_snapshot()


if __name__ == "__main__":
    runner.main()
```

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
