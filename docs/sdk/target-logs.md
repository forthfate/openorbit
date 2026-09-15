# Target logs

`ctx.log()` records Orbit runner progress. Use `ctx.target_log()` only for
meaningful events produced by the AI system or service being evaluated. Orbit
stores target logs separately from workflow logs and displays them in the
run's **Logs** tab.

```python
@runner.phase("execute")
def execute(ctx):
    response = call_target_service()
    ctx.target_log(
        "Response accepted",
        level="info",
        source="support-agent-api",
    )
```

## Recorded context

Orbit adds the run ID, iteration, and lifecycle phase automatically. Each
target log also records a timestamp, level, source, and message.

Supported levels are `debug`, `info`, `warn`, `warning`, and `error`.

!!! warning

    Do not forward credentials, personal data, or unbounded raw service output.
    Target-log messages are retained in run history. The SDK limits one message
    to 4,000 characters and Orbit retains up to 200 target-log entries per step.

## When to use it

- Record target-side state transitions, warnings, and errors needed to
  understand an evaluation result.
- Include a stable `source` so multiple target services remain distinguishable.
- Prefer structured results with `ctx.emit_result()` for machine-consumed
  evidence such as scores, metrics, or proposals.

## Child-process output

`ctx.playwright_journey()` and `ctx.complete_model()` automatically record
their start and completion state as target logs. For other bounded external
adapters or agents, opt in to forwarding child output as shown below.

For a bounded external adapter or agent, opt in to forwarding its non-empty
standard-output and standard-error lines to target logs. Orbit retains the
same output in workflow logs, while the `source` keeps the target stream
identifiable.

```python
ctx.exec(
    ["python", "agent.py", "run-once"],
    timeout=300,
    target_log_source="support-agent",
)
```
