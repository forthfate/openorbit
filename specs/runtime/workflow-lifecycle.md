# Workflow lifecycle

Status: accepted

## Required order

Runner assets declare the lifecycle phases they use. When all standard phases are present, their order is:

1. `before_all`: acquire run ownership; validate input, repository, policy and approved paths.
2. `before_each`: prepare the iteration's catalog, fixture, environment and recovery state.
3. `execute`: invoke bounded tools, models and target subprocesses.
4. `verify`: collect evidence, validate outcomes, score them when applicable, and request a policy decision.
5. `after_each`: persist per-iteration evidence and clean temporary resources.
6. `after_all` (optional): perform process-level work after all iterations.

`after_each` currently runs in the normal loop. It is not yet guaranteed after failure, timeout, cancellation or emergency stop.

## Process ownership

- The Python runner starts commands as argument arrays without a shell.
- A run records PID, process group/tree identity, phase, start/finish timestamps and trace ID durably.
- Unix stop requests signal the process group; Windows terminates the root process.

## Scheduling

Each generated runner step has a timeout and optional minimum interval. Builds declare timezone, repeat interval and total run limit. Retry policy, activity windows and their dashboard controls are planned.

## Server-hosted agents

A build may use the `remote-http` executor to invoke a server-hosted agent. It declares an absolute HTTP(S) endpoint, allowed method, timeout and non-secret payload. Embedded URL credentials are prohibited. The request, response status and trace ID are retained with the run; authentication environment-variable references, response redaction and complete lifecycle staging are planned.

## Planned work

Guarantee cleanup, graceful stop with descendant termination on every platform, retry/activity-window scheduling, and full remote-agent lifecycle handling.
