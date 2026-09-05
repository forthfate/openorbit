# ADR 0007: Linux Docker isolated parallel evaluation

Status: accepted

## Decision

Support opt-in Docker parallel evaluation on Linux only. Each run builds from an isolated repository snapshot and uses constrained, non-privileged containers.

## Context

Parallel improvements must not write over one another or mutate the user's checked-out target repository. Docker is a practical local isolation boundary where the host supports it; Windows support is intentionally deferred.

## Consequences

The control room must preflight Docker, surface image/container/queue state, enforce resource and network limits, export OTEL events and clean up artifacts. Docker availability never authorizes a build automatically.
