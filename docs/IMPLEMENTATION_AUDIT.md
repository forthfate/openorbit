# Implementation audit

Audited: 2026-09-04. Scope: all tracked source, configuration, resources, tests and frontend files.

## Current handoff memo — 2026-09-05

- Orbit is running locally at `http://127.0.0.1:3001`; it never opens a browser automatically. It prefers port 3000 and advances to the next free port.
- Current Evaluation builds: `insighta-quality-daily`, `jgent-workflow-gate`, and `hosted-agent-smoke`. Temporary UI smoke builds and workflows were removed.
- Active evaluations is a build-facing 1:1 view: only the newest pipeline Run for each existing Evaluation build is shown. Deleted-build Run history is retained on disk but excluded from this view.
- `Phase` is restricted to lifecycle phases (`init`, `setup`, `run`, `eval`, `teardown`). Terminal state is shown only in `Status`; completed history displays the last PID and the process console output.
- The Active evaluations action column owns each Run's stop action. The header emergency stop remains the all-active-runs control.
- Evaluation-build rows open the edit modal; radio, Test/Run, and Delete controls do not. An active build can be inspected but cannot be saved or deleted.
- Prompts are structured and stored per build: a versioned manager template, task instruction, and fixed target-AI test cases. Settings can edit shared manager templates; every Run captures the assembled prompt snapshot.
- On success, the configured manager provider is asked for required JSON (`improvements`, `reported_issues`). Validation outcome, response/error, and OpenTelemetry span events are retained per Run. An unconfigured provider does not turn a successful target pipeline into a failed pipeline.
- UI defaults to English and Midnight. English/Korean/Japanese selections persist in local storage. Dashboard metrics/cards, build flow, active-evaluation detail, settings, and improvement views use the selected locale.
- Latest verification: backend `pytest` 23 passed; frontend build and lint passed; Playwright UI coverage passed (build lifecycle, stop flow, and locale persistence).

## Requirement coverage

| Requirement | Status | Evidence / gap |
| --- | --- | --- |
| Five-phase lifecycle | Partial | YAML and `Workflow.lifecycle_is_complete()` enforce the order. Failed/cancelled execution returns before `teardown`; this needs a `finally` path. |
| OpenTelemetry for all logs | Partial | Workflow/step spans export locally. subprocess stdout/stderr is persisted in run JSON, not emitted as redacted OTEL events. |
| AI feedback loop | Partial | Public prompts, adapters and improvement display exist. No evaluator invokes a provider with evidence or persists returned policy decisions. |
| Improvement commit with rationale | Missing | Improvement records are seed YAML. No Git diff, approval artifact, commit, or revert exists. |
| Prompt-defined improvement policy | Partial | Prompts are versioned, but `ImprovementPolicy` is code-only and not driven by model output. |
| Tool interval | Implemented | `minimum_interval_seconds` is declared and enforced. Dashboard editing is not yet implemented. |
| Dashboard operation | Partial | Four list pages, settings save, hello and emergency stop exist. Build CRUD, prompt editor, row actions and drill-down are absent. |
| Azure and AWS models | Partial | Azure/Bedrock adapter boundaries and hello exist. Bedrock needs optional `boto3`; neither adapter runs an evaluation policy yet. |
| PID management and stop | Partial | PID is persisted; Unix process groups terminate. Windows only terminates the root process; graceful wait and tree termination are needed. |
| Console/task logs | Missing | UI shows phase/PID/trace ID but does not stream stdout/stderr or task events. |
| Metrics and PR counts | Partial | Basic aggregate counts exist. PR, generated/approved-improvement and evidence-derived metrics are absent. |
| PDCA/effect graph | Partial | Seed records render a graph; metrics are not derived from immutable evaluation evidence. |
| i18n/theme | Partial | Navigation strings and token entrypoint exist. Remaining text and legacy color literals are embedded. |
| Windows/Linux portability | Partial | Runner branches by OS, but sample workflow paths are Linux/WSL-specific; platform profiles are needed. |
| Linux Docker parallel execution | Partial | Linux-only Docker preflight, specification and build configuration exist. Snapshot/image build, scheduler, container OTEL logs, constrained execution and cleanup are not yet wired into the runner. |
| Server-hosted agent invocation | Partial | `remote-http` builds can invoke a configured HTTP(S) endpoint with an environment-secret reference and persist bounded response evidence. Dashboard enable/edit/run controls, response redaction policy and full eval/teardown stages remain to be completed. |

## Security review

- Browser clients cannot submit arbitrary commands; versioned workflow files use argument arrays rather than a shell.
- Keys are referenced by environment-variable name, not written to workflow/settings data.
- Production work required: explicit per-build command allowlists, OTEL redaction, human approval records before Git writes, and dirty-worktree refusal.

## Recommended implementation order

1. Add immutable `EvaluationRun` evidence and redacted per-line OTEL console events.
2. Guarantee `teardown` in a runner `finally`; add graceful cancellation and Windows process-tree termination.
3. Add Evaluation Build CRUD, prompt revisions and platform command profiles.
4. Invoke the selected provider during `eval` and validate structured prompt-policy output against hard safety rules.
5. Add candidate diff isolation, baseline/current scoring, approval records, Git commit/revert and PR connector interfaces.
6. Replace seed improvement metrics with evidence-derived records and complete locale/theme extraction.
