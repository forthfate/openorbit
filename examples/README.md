# Runner samples

These samples are portable starting points for **Assets → Runners**. Copy a
sample's source into a runner, then connect it to an evaluation build. They do
not contain a product name, a local absolute path, or a background scheduler.

| Sample | Use when | Evaluation-build requirements |
| --- | --- | --- |
| `browser-user-journey-runner.py` | You want recurring, observable browser checks. | Browser base URL and at least one fixed test case. |
| `external-command-runner.py` | You already have a command-line automation tool. | `ORBIT_ADAPTER_COMMAND` configured in the runner environment. |
| `inspect_behavior.py` | You want to inspect the bundled behavior definition locally. | A repository checkout with the Python package available. |
| `ai-slo-supportops/` | You want a safe local target for the AI SLO and behavior-drift Quick Start. | Python 3 only; no provider credentials for the fixture itself. |

## Browser user journey

Create fixed test cases with a route (`path`) and, optionally, text that must
be visible (`expected_text`). The sample rechecks failed cases before rotating
to the next fixed case. It stores only bounded planning state in OpenOrbit
AppData and attaches screenshots and page evidence to each run.

## External command adapter

Configure `ORBIT_ADAPTER_COMMAND` as a JSON array when arguments contain
spaces or special characters:

```text
["/opt/automation/bin/check"]
```

Or use a shell-like command string:

```text
python -m my_automation
```

The external program should implement `status`, `prepare`, `run-once`, and
`collect-evidence` as one-shot actions. It must not start a daemon or schedule
its own repeat loop. The sample captures each action's output as an immutable
OpenOrbit artifact.

## Local inspection

Run the behavior-inspection sample from a repository checkout after installing
the project dependencies:

```bash
uv run python examples/inspect_behavior.py
```

For every sample, adapt only the configuration and bounded work for your
project. Keep lifecycle ownership with OpenOrbit: `init` and `finalize` run
once per process; `setup`, `run`, `eval`, and `teardown` run once per iteration.

## AI SLO and behavior-drift demo

[`ai-slo-supportops/`](ai-slo-supportops/README.md) is a complete local sample:
a synthetic support website and an evaluator agent that returns structured SLO
evidence. It is deliberately local-only and has no credentials, real customer
data, external provider endpoint, or background scheduler.
