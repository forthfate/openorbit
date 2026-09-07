# ADR 0003: OpenTelemetry run correlation

Status: accepted

## Decision

OpenTelemetry spans correlate workflow, process and model operations with a run trace ID.

## Current implementation

Orbit exports workflow, step, remote-invocation and model spans to a local JSONL OTEL exporter. Run metadata, console output and evidence are retained with the local run record.

## Planned work

Emit redacted console logs and all approval, policy, Git and Docker events as OTEL telemetry, then support an operator-configured remote collector.

## Consequences

The dashboard correlates each run with its trace ID. Local run records remain the detailed evidence source until log-signal export and remote collection are available.
