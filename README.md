# OpenOrbit

> **The open control plane for recurring AI automations.**

OpenOrbit is an open-source, local control plane for running, supervising, and
improving AI-powered automations. It connects reusable runners, workflows,
evaluation builds, and supervisor models so operators can inspect evidence,
review decisions, and stop unsafe work from one place.

## Features

- Create reusable Python runners for project-specific automation.
- Define lifecycle workflows: `init → setup → run → eval → teardown → finalize`.
- Combine repositories, workflows, model profiles, manager prompts, and fixed
  test cases into reusable evaluation builds.
- Run local processes or remote HTTP executors with approval gates, timeouts,
  process identity, and emergency stop.
- Inspect phase logs, all-run output, structured evidence, supervisor responses,
  proposed improvements, and reported issues.
- Explore each execution as an OpenTelemetry trace tree.
- Keep operational assets and history in local platform AppData, not in Git.

## Quick start

## Requirements and dependencies

| Requirement | Version | Used for |
| --- | --- | --- |
| Python | 3.13+ | OpenOrbit API, runner SDK, and local workflows |
| Node.js | 24+ | React control room and bundled Playwright integration |
| Git | 2.40+ recommended | Repository validation and native improvement cycles |
| Chromium system libraries | Platform-specific | Required only when running browser journeys on Linux |

The Python runtime dependencies are `fastapi`, `uvicorn`, `PyYAML`,
`opentelemetry-api`, `opentelemetry-sdk`, and `requests`. Development installs
also include `pytest`, `httpx`, `ruff`, and `pre-commit`. The frontend package
manifest contains the React, Vite, Playwright, CodeMirror, and charting
dependencies. Install everything with the following commands.

```bash
git clone https://github.com/forthfate/openorbit.git
cd openorbit

uv sync --extra dev
corepack enable
pnpm install

uv run uvicorn app.main:app --app-dir backend --reload --port 3000
```

In another terminal:

```bash
pnpm --filter agent-improvement-console-ui run dev
```

Open `http://localhost:5173`.

## API

OpenOrbit provides a GitLab-inspired, versioned local API. Evaluation builds
are exposed as **projects** and their executions as **pipelines**:

- Interactive OpenAPI/Swagger documentation: `http://localhost:3000/api/docs`
- OpenAPI JSON contract: `http://localhost:3000/api/openapi.json`
- Versioned API base: `http://localhost:3000/api/v1`

See [the API reference](docs/API.md) for endpoints, pagination, examples, and
the local-first security boundary.

The bundled launcher builds and serves the local app:

```bash
pnpm install
pnpm run run
```

## Install and run

The published packages include the built control-room UI, so Node.js is not
needed when installing the Python package.

```bash
pip install openorbit
orbit run
```

For an npm installation, the same command is available globally (Python 3.13+
must still be installed because the API runs on Python):

```bash
npm install --global openorbit
orbit run
```

For a one-off npm execution, use `npx openorbit run`, or retain the command
name with `npx --package=openorbit orbit run`. Plain `npx orbit run` cannot be
used because the unscoped `orbit` package is already owned by another project.

By default the control room is available at `http://127.0.0.1:3000`. Use
`orbit run --port 8787 --host 0.0.0.0` to change the listener, or
`orbit run --open` to open it in a browser. Package releases must run
`pnpm run build` before the Python wheel is built; npm does this automatically
through its `prepack` hook.

## Operating model

1. Register assets: model profiles, manager prompts, fixed test cases, runners,
   and workflows.
2. Create an evaluation build that connects those assets to a target repository.
3. Start a bounded test or a configured run.
4. Review logs, evidence, OpenTelemetry spans, and supervisor decisions.
5. Approve, stop, or improve the automation with observable evidence.

## Sharing runner templates

In **Assets → Runners → Create**, use **Import template** to add a shared
runner template from a JSON file. Imported templates are validated as Python,
stored only in the local AppData catalog, and then appear alongside the built-in
templates for creating new runners.

```json
{
  "id": "shared-browser-check",
  "name": "Shared browser check",
  "description": "Runs a bounded browser check with OpenOrbit.",
  "source": "from orbit_sdk import runner\n\n@runner.phase('run')\ndef run(ctx):\n    ctx.log('Run one bounded check')\n\nif __name__ == '__main__': runner.main()\n"
}
```

Template IDs must be lowercase hyphenated identifiers. Built-in templates are
versioned with the repository; imported templates remain local to the user.

## Versioned runner file updates

Runner code can safely modify a target-repository file through
`RunnerContext.update_file()`. Before each changed write, OpenOrbit preserves
the old bytes outside the repository and records the run ID, phase, iteration,
UTC timestamp, and SHA-256 hashes. This makes an iteration's change reversible
without requiring the target project to use Git.

```python
@runner.phase("run")
def run(ctx):
    update = ctx.update_file("config/settings.json", '{"enabled": true}\n')
    if update["changed"]:
        ctx.log(f"Saved rollback version {update['version']['id']}")

@runner.phase("teardown")
def teardown(ctx):
    for version in ctx.file_versions("config/settings.json"):
        ctx.log(f"{version['id']}: iteration {version['iteration']}")
```

Restore the state immediately before a recorded version with
`ctx.rollback_file("config/settings.json", version_id)`. A rollback retains the
file's current state as a new version too, so it can itself be undone. Version
history is stored under OpenOrbit AppData in `file-history/`, not in the target
repository.

Improvement runners can also record a review decision with
`ctx.accept_proposal(proposal)` or `ctx.reject_proposal(proposal)`. These are
deduplicated, timestamped events with the proposal content, iteration, phase,
run ID, and evaluation-build identity. The native improvement-cycle template
uses this ledger and updates its configured prompt file only from proposals
explicitly marked `adopted`. Inspect events through
`GET /api/v1/improvements/proposal-decisions` when building a review timeline.

## Data and security

OpenOrbit stores operational state in platform AppData:

- Windows: `%LOCALAPPDATA%\Orbit`
- macOS: `~/Library/Application Support/Orbit`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/orbit`

Set `ORBIT_APP_DATA` to use another location. Secrets are not stored by
OpenOrbit; model profiles retain only the environment-variable name that holds
the secret. Do not expose the local service to the public Internet without an
authentication and network-security boundary.

## Development

```bash
uv run ruff check orbit/ backend/ tests/
PYTHONPATH=backend uv run pytest -q
pnpm --filter agent-improvement-console-ui run build
```

Ruff ignores `E501` because embedded runner scripts, execution templates, and
structured prompt schemas intentionally retain long lines. All other selected
`E`, `F`, `I`, and `W` checks run in CI.

## Status

OpenOrbit is an MVP for local, observable AI-automation operations. Review all
workflow commands and approval boundaries before connecting production systems.

## License

[MIT](LICENSE). Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).
