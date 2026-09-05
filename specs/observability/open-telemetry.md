# OpenTelemetry operational record

Status: accepted

## Trace model

- One evaluation run creates one root trace.
- Lifecycle phases, subprocesses, tool calls, model calls, approvals, policy decisions, commits and rollbacks are child spans or events.
- Dashboard rows expose the trace ID and link to the matching local or remote OTEL backend.

## Logs and metrics

- stdout and stderr are emitted as ordered, redacted OTEL log events associated with the active subprocess span.
- Required metrics include runs, successful evaluations, PRs, proposed improvements, approved improvements, commits, reverts, score delta, duration, token use and estimated cost.
- Console text is retained only within configured local evidence retention limits.

## Data protection

- API keys, bearer tokens, passwords, input values and known PII are redacted before persistence or export.
- Prompt and completion retention is configurable; their hashes, model metadata and usage are always traceable.
- Exporter configuration must not silently fall back from an operator-selected remote collector to an unsafe destination.
