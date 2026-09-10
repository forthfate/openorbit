# ADR 0002: Runner-declared lifecycle phases

Status: accepted

## Decision

Run tasks through runner-declared lifecycle phases. The standard order is `before_all → before_each → execute → verify → after_each`; runners may additionally declare `after_all` for process-level work after the loop.

## Current implementation

Builds execute runner assets directly. Legacy workflow assets remain editable, but they are not the execution source for builds. A runner may declare only the phases it needs.

## Planned work

Enforce a complete lifecycle for production runners and guarantee after_each after failure, timeout, cancellation and emergency stop.

## Consequences

Runs are comparable and observable across target projects. The runner can enforce process ownership, scheduling and cleanup consistently.
