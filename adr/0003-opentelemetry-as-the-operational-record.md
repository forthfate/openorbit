# ADR 0003: OpenTelemetry as the operational record

Status: accepted

## Decision

OpenTelemetry is the canonical record for workflow, process, model, approval and Git operational events.

## Consequences

The dashboard correlates all operational data with trace IDs. Ad-hoc file logs may exist only as evidence projections, not the source of operational truth.
