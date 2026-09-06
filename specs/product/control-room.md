# Control room

Status: accepted

## Goal

Provide one local web control room for configuring, running, observing and reviewing autonomous agent evaluation and improvement systems.

## Primary views

| View | Required list-managed content | Required actions |
| --- | --- | --- |
| Dashboard | active rules/builds, active evaluations, approval queue, warnings, daily counts | drill into a build or run; emergency stop |
| Evaluation builds | prompt revision, model configuration, repository, purpose, criteria, run limit, timezone, interval, approval score | create, clone, edit, validate, enable, disable, run |
| Active evaluations | moving tasks, lifecycle phase, console events, run count, PR count, proposed/approved improvements, PID, trace ID | inspect, stop one run, emergency stop all |
| Improvement results | proposal, policy decision, baseline/current evidence, PDCA state, commit/revert state | approve, reject, inspect diff, commit, revert |

All three management views are list-first. Detail is opened from a row and must preserve a link back to the list state.

## Localization and theme

- Korean and English are supplied by default; all operator-facing text uses locale resources.
- Dark mode is the default. Colors, typography and layout tokens are defined in forkable theme resources.
- A fork must be able to replace locale, theme, workflow and prompt resources without modifying runner core.
