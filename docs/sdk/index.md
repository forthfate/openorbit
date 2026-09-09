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
