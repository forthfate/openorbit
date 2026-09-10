# OpenTelemetry operational record

Status: accepted

## Trace model

- One run creates one root trace.
- Workflow, step, remote-invocation and model calls are spans.
- Dashboard rows expose the local trace ID and its exported spans.

## Logs and metrics

- Console output is retained in the local run record; OTEL records subprocess completion and failures as span events.
- Dashboard metrics currently include build/run counts and supervisor-feedback summaries.

## Data protection

- Model secrets are stored only as environment-variable references. Console output and prompt retention are local and are not yet redacted or configurable.

## Planned work

Add ordered redacted OTEL log signals, retention controls, complete operational metrics, policy/Git/Docker events and an explicitly configured remote exporter.
