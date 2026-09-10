# Control room

Status: accepted

## Goal

Provide one local web control room for configuring, running, observing and reviewing autonomous agent evaluation and improvement systems.

## Primary views

| View | Required list-managed content | Required actions |
| --- | --- | --- |
| Dashboard | build/run counts, recent evaluations, supervisor-health summary and local operational events | open a build or run; open quick-start flow |
| Assets | reusable runners, prompts, test-case sets, execution environments and target environments | create, edit and delete assets |
| Builds | repository, runner, prompt, model profile, test-case set, schedule and approval score | quick start, create, clone, edit, test, run and delete |
| Runs | lifecycle phase, console output, supervisor findings, PID and trace ID | inspect, stop one run, emergency stop all |
| Improvements | retained supervisor feedback, scores, proposals and cycle analytics | inspect and filter evidence |
| Settings | locale, theme, model profiles and application prompts | configure and test a model profile |

The list-managed views are list-first. Detail is opened from a row and preserves a link back to the list state.

## Loading states

Every primary view provides an initial-load skeleton for its visible sections.
Skeletons are not shown again during polling or a normal refresh. See the
[control-room loading-state contract](loading-states.md) for the complete
behavior, accessibility, and ownership rules.

## Planned work

Add an approval queue and warnings to the dashboard; build enable/disable controls; and reviewed diff, commit and revert actions for improvements.

## Quick-start entry

Build creation begins with a choice between a quick start and manual
configuration. The dashboard may open the same quick-start flow directly.
Quick starts are specified by the [quick-start product contract](quick-starts.md).

## Localization and theme

- English, Korean and Japanese are supplied by default. Shared text uses locale resources; remaining legacy text is being migrated.
- The selected application locale is the display-language source of truth; an
  unsupported or missing locale falls back to English.
- Static UI controls and messages are supplied by locale resources. Runtime
  content, including translated template metadata, is not added to those
  resources.
- Runner-template and quick-start metadata may be translated on demand with
  the configured System AI and cached by source content and target locale.
  Translation changes display text only: IDs, parameter keys and values,
  source code, URLs, paths, and instantiation payloads always retain their
  original values. The UI must allow the original text to be shown again.
- Dark mode is the default. Shared colors, typography and layout use theme resources; remaining legacy color literals are being migrated.
- A fork must be able to replace locale, theme, workflow and prompt resources without modifying runner core.
