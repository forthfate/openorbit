# ADR 0007: Linux Docker isolated parallel evaluation

Status: accepted

## Decision

Reserve Docker parallel evaluation for Linux only, with isolated repository snapshots and constrained, non-privileged containers.

## Current implementation

Orbit only preflights Linux Docker CLI and daemon availability. Docker is not yet an evaluation executor.

## Planned work

Add opt-in Docker build configuration, snapshot/image creation, constrained parallel containers, cleanup and OTEL lifecycle events.

## Context

Parallel improvements must not write over one another or mutate the user's checked-out target repository. Docker is a practical local isolation boundary where the host supports it; Windows support is intentionally deferred.

## Consequences

The control room must preflight Docker, surface image/container/queue state, enforce resource and network limits, export OTEL events and clean up artifacts. Docker availability never authorizes a build automatically.
