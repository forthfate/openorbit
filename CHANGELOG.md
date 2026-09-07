# Changelog

All notable changes to OpenOrbit are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project uses [Semantic Versioning](https://semver.org/).

## [0.0.5] - 2026-09-07

### Added

- Global, stacked notifications with success, warning, and error states. Notifications remain visible while navigating between pages, can be dismissed individually, and expire independently after ten seconds.
- Reusable **Execution Environment** assets for local or remote HTTP execution, browser executable paths, and browser library paths.
- Reusable **Target Environment** assets for repositories, browser base URLs, and native-runner managed prompt files.
- Environment asset CRUD APIs with protection against deleting an environment that an evaluation build still references.
- A visible warning around the operational manager prompt contract.

### Changed

- Evaluation builds now compose reusable execution environments, target environments, execution plans, manager templates, fixed test sets, model profiles, and evaluation scheduling/approval policy.
- The global operational manager prompt is now the active supervisor contract. The selected manager template is inserted at `__ORBIT_MANAGER_AI_PROMPT__`.
- Removed prompt-source-file and inline evaluation-criteria inputs from new evaluation builds. Existing records retain compatibility data during migration.
- Native improvement runners now read their managed prompt-file target from the target environment rather than treating it as a general supervisor prompt source.
- Existing evaluation builds are automatically migrated to per-build reusable environment assets while preserving their runtime compatibility.
- Chat launcher coordinates are clamped to the current viewport so a previously dragged global chat control cannot remain off-screen after a window-size change.

### Fixed

- CI now builds and transfers the frontend distribution before Python packaging, preventing the missing `frontend/dist` Hatch build failure.
- Added the direct CodeMirror view dependency required by the Python editor frontend build.

[0.0.5]: https://github.com/forthfate/openorbit/releases/tag/v0.0.5
