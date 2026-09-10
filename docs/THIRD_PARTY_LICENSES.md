# Third-party direct dependency licenses

Last reviewed: 2026-09-10

This inventory covers OpenOrbit's **directly declared** Python and Node.js
dependencies, including development and documentation dependencies. It groups
modules by SPDX license identifier so each license appears only once. It is not
a replacement for the complete notices of transitive dependencies resolved in
`uv.lock` or `pnpm-lock.yaml`.

## MIT

- Python: FastAPI, PyYAML, LangGraph, pywinpty (Windows only), pytest, Ruff,
  pre-commit, MkDocs Material
- Node runtime: CodeMirror language/theme/view packages, `@uiw/react-codemirror`,
  `@vitejs/plugin-react`, xterm packages, `@xyflow/react`, React, React DOM,
  React Icons, React Markdown, Recharts, Remark GFM, Vite
- Node development: ESLint packages, Tailwind packages, React type packages,
  `globals`, `typescript-eslint`

## Apache-2.0

- Python: OpenTelemetry API, OpenTelemetry SDK, Requests
- Node development: Playwright Test, TypeScript

## BSD-3-Clause

- Python: Uvicorn, HTTPX

## ISC

- Python documentation: MkDocstrings
- Node runtime: Lucide React

## Source of truth and update procedure

- Python direct dependencies are declared in `pyproject.toml`.
- Node direct dependencies are declared in `frontend/package.json`.
- Before adding or upgrading a dependency, verify its package metadata and the
  upstream repository's license text. Record any license family not already
  represented above.
- A release that distributes bundled dependency code should generate a full
  transitive notice inventory from the resolved Python and Node lockfiles.
