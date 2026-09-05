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

Requirements: Python 3.13+ and Node.js 20+

```bash
git clone https://github.com/forthfate/openorbit.git
cd openorbit

python3.13 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm --prefix frontend install

.venv/bin/uvicorn app.main:app --app-dir backend --reload --port 3000
```

In another terminal:

```bash
npm --prefix frontend run dev
```

Open `http://localhost:5173`.

The bundled launcher builds and serves the local app:

```bash
npm install
npm run run
```

## Operating model

1. Register assets: model profiles, manager prompts, fixed test cases, runners,
   and workflows.
2. Create an evaluation build that connects those assets to a target repository.
3. Start a bounded test or a configured run.
4. Review logs, evidence, OpenTelemetry spans, and supervisor decisions.
5. Approve, stop, or improve the automation with observable evidence.

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
.venv/bin/ruff check orbit/ backend/ tests/
PYTHONPATH=backend .venv/bin/pytest -q
npm --prefix frontend run build
```

Ruff ignores `E501` because embedded runner scripts, execution templates, and
structured prompt schemas intentionally retain long lines. All other selected
`E`, `F`, `I`, and `W` checks run in CI.

## Status

OpenOrbit is an MVP for local, observable AI-automation operations. Review all
workflow commands and approval boundaries before connecting production systems.

## License

[MIT](LICENSE). Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).
