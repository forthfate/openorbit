# Linux Docker parallel execution

Status: planned

## Scope

Docker execution is planned for Linux hosts with a reachable Docker Engine. Orbit currently provides only a Linux Docker CLI/daemon preflight and never selects Docker automatically.

## Build configuration

The future Docker-enabled build will declare executor type, Dockerfile, snapshot mode, parallelism, network policy, resource limits and image retention. The intended default is one worker, commit snapshot, no network and no image retention.

## Isolation contract

- A future run will copy an immutable repository snapshot into a temporary Docker build context.
- The host repository, Docker socket, privileged mode, host network and arbitrary host-volume mounts are prohibited.
- Each worker receives a unique container ID, run ID, candidate fingerprint and writable workspace inside the container.
- Evidence is exported only through a controlled output directory after redaction.

## Lifecycle

The future lifecycle will verify Linux and capacity, create snapshots and images, schedule constrained containers, aggregate evidence and clean temporary contexts/images. Current preflight verifies only Linux Docker CLI/daemon availability.

## Observability and stop

The future implementation will record Docker lifecycle data in OpenTelemetry and provide graceful then forced emergency stop.
