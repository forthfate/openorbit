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

## UI smoke tests

Start OpenOrbit with the sample data expected by
`frontend/e2e/orbit-ui.spec.ts`, then run from the repository root:

```bash
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 pnpm --filter agent-improvement-console-ui exec playwright test
```

Set `PLAYWRIGHT_BASE_URL` to the URL printed by your running app if it uses
another port. When omitted (or empty), the tests use `http://127.0.0.1:3001`.
This changes the target URL only; the existing scenarios still require their
configured repositories and sample evaluation data.

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
   and create the GitHub Release from the matching changelog entry. The
   frontend-inclusive PyPI wheel is published from the
   `insighta-cloud/openorbit` publishing workflow through Trusted Publishing.
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

## Localization

- Put shared, static UI copy in `frontend/src/locales/index.ts`; do not add new
  user-facing UI strings inline in a component.
- Add every new locale key to the English, Korean, and Japanese dictionaries
  with the same nesting and key name. Group keys by feature rather than adding
  unrelated keys to an existing group.
- Use the selected application locale (`orbit.locale`) as the source of truth.
  `resolveLocale` must continue to fall back to English for an unsupported or
  missing value.
- Use `intlLocales` for locale-sensitive date, time, and number formatting.
- Do not treat runtime content as a locale resource. For example, an AI
  translation of a runner template or quick start is cached display data;
  static controls such as **Translate**, **Show original**, and error messages
  remain locale keys.
- Translation must not change executable or identity-bearing values: IDs,
  parameter keys and values, source code, URLs, paths, and API payloads retain
  their original values.

Contributions are licensed under MIT.
