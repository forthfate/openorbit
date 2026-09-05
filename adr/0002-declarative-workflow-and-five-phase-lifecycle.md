# ADR 0002: Declarative workflow and five-phase lifecycle

Status: accepted

## Decision

Use versioned YAML workflow definitions and require `init → setup → run → eval → teardown`.

## Consequences

Runs are comparable and observable across target projects. The runner can enforce process ownership, scheduling and cleanup consistently.
