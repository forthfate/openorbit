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

## Releases

Every release follows the same protected sequence so that a version tag always
identifies a verified `main` commit.

1. Create `release/vX.Y.Z` from the current `main` branch.
2. Update the version in `package.json`, `frontend/package.json`, and
   `pyproject.toml`, then add the release entry to `CHANGELOG.md`.
3. Open a pull request from the release branch to `main` and wait for all
   GitHub Actions checks to pass.
4. Merge the pull request, then wait for the CI run triggered on `main` to
   pass as well.
5. Create an annotated `vX.Y.Z` tag at that verified `main` commit, push it,
   and create the GitHub Release from the matching changelog entry. The release
   workflow builds the frontend-inclusive wheel, attaches it to that release,
   and publishes it to PyPI through Trusted Publishing.
6. Delete superseded tags only after the new tag and GitHub Release are
   available. Never move or overwrite an existing release tag.

The release branch is the only place where release-preparation changes are
made. A tag must never be created from an unmerged branch or before `main` CI
has completed successfully.

## Rules

- Keep public behavior bundles independent of proprietary source, prompts, and fixtures.
- Put declarative behavior contracts in `orbit/resources/definitions/`, prompt templates in
  `orbit/resources/prompts/`, and non-secret sample inputs in `orbit/resources/fixtures/`.
- Commands must be token arrays; do not introduce shell-string execution.
- Add tests for behavior or schema changes.

Contributions are licensed under MIT.
