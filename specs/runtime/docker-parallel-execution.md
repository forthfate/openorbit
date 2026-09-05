# Linux Docker parallel execution

Status: accepted

## Scope

Docker execution is available only on Linux hosts with a reachable Docker Engine. It is opt-in per evaluation build and never silently replaces a local executor.

## Build configuration

Each Docker-enabled evaluation build declares executor type, Dockerfile, snapshot mode, parallelism, network policy, resource limits and image retention. Default posture is one worker, commit snapshot, no network, no image retention.

## Isolation contract

- A run copies an immutable repository snapshot into a temporary Docker build context.
- The host repository, Docker socket, privileged mode, host network and arbitrary host-volume mounts are prohibited.
- Each worker receives a unique container ID, run ID, candidate fingerprint and writable workspace inside the container.
- Evidence is exported only through a controlled output directory after redaction.

## Lifecycle

`init` verifies Linux, Docker CLI/daemon and capacity, then reserves scheduler slots. `setup` creates the snapshot and image. `run` schedules up to `max_parallelism` containers. `eval` aggregates isolated evidence. `teardown` stops remaining containers, removes temporary contexts and removes images according to retention policy.

## Observability and stop

Docker build, container lifecycle, streamed stdout/stderr, resource limits, exit code and cleanup are OpenTelemetry records. Emergency stop cancels queued work, sends graceful stop to active containers, then force-kills after the grace period.
