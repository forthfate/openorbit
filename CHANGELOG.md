# Changelog

All notable changes to OpenOrbit are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project uses [Semantic Versioning](https://semver.org/).

## [0.5.1] - 2026-09-08

### Fixed

- Frontend release labels now use the packaged release version, so a release build cannot retain an earlier Git tag.
- Supervisor review now includes setup-phase managed-prompt evidence, allowing directly evidenced prompt-only improvements to be adopted and applied on the next iteration.

## [0.5.0] - 2026-09-08

### Added

- Supervisor results now include a concise summary of observed evaluated-AI behavior, with display-only translation support.
- Manager prompt templates retain version history, preserve unsaved drafts, and create a new version on every save.
- The dashboard now surfaces four Quick Starts, opens the selected Quick Start directly, and links to the repository, release notes, and local OpenAPI documentation.

### Changed

- Supervisors can adopt evidence-backed, low-risk, reversible prompt-only improvements without waiting for repeated candidate fingerprints; code, infrastructure, policy, and insufficiently evidenced changes remain proposed.
- Improvement analytics and dashboard charts use localized labels and themed tooltips. Active-evaluation charts now retain short runs that overlap a chart interval.
- Proposal history, workflow logs, evaluation results, and Cycle Improvement AI headers have clearer, more compact presentation.

### Fixed

- Restored AI model profiles in Assets and aligned Settings with the shared profile component.
- Workflow log output preserves separate log lines.

## [0.4.1] - 2026-09-07

### Changed

- Evaluation Builds and evaluation execution history now share the same pagination component, layout, and range display.

## [0.4.0] - 2026-09-07

### Added

- Runner-template and Quick Start catalogs can translate all visible template metadata at once, with cached display-only translations and an option to restore the originals.
- Added icons to catalog translation/import actions and the Evaluation Build duplicate action for clearer controls.

## [0.3.0] - 2026-09-07

### Added

- Evaluation run detail now records and displays timestamps for individual log lines; the Logs tab presents one continuous output stream while Workflow logs retain phase-specific inspection.
- The README now includes a product tour with English demo data, standalone/BYOA guidance, Chat Assistant usage, development-partner attribution, and Git-based installation instructions.
- Source and Git installations build the bundled control-room UI into the wheel; Python CI reuses the verified frontend artifact.

### Changed

- OpenOrbit is positioned as a local control plane for continuously evaluating, supervising, and improving AI systems.
- Evaluation Builds now display localized created and last-started timestamps.
- Interface text is consolidated through locale resources, including evaluation-run filtering and status labels.

### Fixed

- Failed runner phases now stop evaluation runs and correctly mark them as failed instead of completed.
- Evaluation Build selection and the Last started column are restored.

## [0.2.0] - 2026-09-07

### Added

- Declarative Quick Start packages can now create reusable evaluation assets and a configured evaluation build from a guided setup flow.
- The Evaluation Builds test action opens a live run-detail dialog with execution status and logs, while test sessions remain out of Evaluation runs history.
- The sidebar displays the current number of queued, approval-pending, and running evaluation runs, capped at `99+`.

### Changed

- Local evaluation builds and workspace browsing may use any existing local directory; the prior fixed workspace-root restriction was removed.

### Fixed

- Evaluation runners now expand home-directory paths such as `~/projects/example` before checking that the working directory exists.
- Release lockfile verification now includes the project version, preventing `uv sync --locked` failures after a version bump.

## [0.1.0] - 2026-09-07

### Added

- Evaluation-result views now show every iteration in newest-first order with filters for iteration, decision, score, content, proposal attempt and status, and issue severity and status.
- Evaluation-run details include reordered tabs, line-numbered supervisor, workflow, and iteration logs, and workflow/log timestamps.
- Cycle Improvement AI now analyzes a selected evaluation build, shows proposal-decision evidence as a run-and-iteration tree, and can request a Markdown PDCA diagnosis from the configured System AI model.
- Tooltips and localized labels were added across the evaluation and cycle-analysis views.

### Changed

- Proposal decision history is derived directly from supervisor results recorded by evaluation runs rather than a separate runner-owned decision ledger.
- The settings label **Chat assistant model** is now **System AI model**; the selected profile is shared by chat and cycle diagnosis.
- Runner templates were generalized for reuse across projects and runner comments were standardized in English.
- Page headers now provide descriptions and visual separation, and common select controls use a consistent compact style.

### Fixed

- Multi-line evaluation-build purposes render consistently in the edit modal.
- Evaluation result filtering, proposal history, and system-AI cycle diagnosis now use localized labels and Markdown output.

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
[0.1.0]: https://github.com/forthfate/openorbit/releases/tag/v0.1.0
[0.2.0]: https://github.com/forthfate/openorbit/releases/tag/v0.2.0
[0.3.0]: https://github.com/forthfate/openorbit/releases/tag/v0.3.0
[0.4.0]: https://github.com/forthfate/openorbit/releases/tag/v0.4.0
[0.4.1]: https://github.com/forthfate/openorbit/releases/tag/v0.4.1
