# ADR 0001: Approval-first local control room

Status: accepted

## Decision

Orbit is a local web control room. It uses explicit human approval before high-impact execution, source changes, commit and rollback.

## Consequences

The product favors inspectability and recoverability over unattended change velocity. Remote deployment is an extension, not a precondition.
