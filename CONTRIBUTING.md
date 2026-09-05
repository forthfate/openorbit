# Contributing

## Development

Python 3.11+ and Node 20+ are required.

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/ruff check orbit/ backend/ tests/
npm --prefix frontend install
npm --prefix frontend run build
```

For the packaged local-app path, run `npm install` at the repository root and
then `npx orbit-agent-console run --no-open`.

On Windows, activate the environment with `.venv\\Scripts\\Activate.ps1` and
use `.venv\\Scripts\\python.exe`.

## Pre-commit

The repository checks Python with Ruff, React with ESLint, and validates the
React application with a Vite production build before each commit.

```bash
.venv/bin/pre-commit install
.venv/bin/pre-commit run --all-files
```

The React hook needs `npm --prefix frontend install` to have been run once.

## Rules

- Keep public behavior bundles independent of proprietary source, prompts, and fixtures.
- Put declarative behavior contracts in `orbit/resources/definitions/`, prompt templates in
  `orbit/resources/prompts/`, and non-secret sample inputs in `orbit/resources/fixtures/`.
- Commands must be token arrays; do not introduce shell-string execution.
- Add tests for behavior or schema changes.

Contributions are licensed under MIT.
