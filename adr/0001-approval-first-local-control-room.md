# ADR 0001: Approval-first local control room

Status: accepted

## Decision

Orbit is a local web control room. Its target operating model requires explicit human approval before high-impact execution, source changes, commit and rollback.

## Current implementation

Orbit is local-first and exposes approval, rejection, cancellation and emergency-stop controls. Ordinary evaluation runs currently start immediately; source changes, Git commits and rollback automation are not implemented.

## Planned work

Classify high-impact operations, require recorded approval before they begin, and add reviewed commit and rollback operations.

## Consequences

The product favors inspectability and recoverability over unattended change velocity. Remote deployment is an extension, not a precondition.
