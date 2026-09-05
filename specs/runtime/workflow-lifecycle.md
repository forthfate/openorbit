# Workflow lifecycle

Status: accepted

## Required order

Every executable workflow declares exactly one of each phase, in this order:

1. `init`: acquire run ownership; validate input, repository, policy and approved paths.
2. `setup`: prepare catalog, fixture, environment and recovery state.
3. `run`: invoke bounded tools, models and target subprocesses.
4. `eval`: collect evidence, score it and request a policy decision.
5. `teardown`: persist final evidence, release ownership and clean temporary resources.

`teardown` is attempted after success, failure, timeout, cancellation and emergency stop. It may not turn a failed run into success.

## Process ownership

- The Python runner starts commands as argument arrays without a shell.
- A run records PID, process group/tree identity, phase, start/finish timestamps and trace ID durably.
- Stop requests first attempt graceful termination, wait for a configured grace period, then terminate remaining descendants.
- Windows and Unix process-tree behavior is implemented through platform adapters, not workflow shell scripts.

## Scheduling

Each tool step declares timeout, retry policy, maximum invocation count and optional minimum interval. Evaluation builds declare timezone, activity window, repeat interval and total run limit. The dashboard edits and displays every value.

## Server-hosted agents

An evaluation build may use the `remote-http` executor to invoke an uploaded/server-hosted agent. It declares an absolute HTTP(S) endpoint, allowed method, timeout, non-secret payload and an optional authentication environment-variable reference. Embedded URL credentials and secret persistence are prohibited. The request, response status, redacted bounded response evidence and trace ID belong to the same lifecycle record.
