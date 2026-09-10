# AI SLO and behavior-drift sample

This is a local-only, dependency-free target for the **AI SLO and behavior
drift monitor** Quick Start. It includes a small synthetic SupportOps website
and a structured evaluator that follows Orbit's evidence-gated probe contract.

It is deliberately safe to share:

- listens only on `127.0.0.1:4174`;
- uses synthetic tickets and deterministic responses, never customer data;
- contains no API keys, provider endpoints, account IDs, or absolute paths;
- rejects non-local evaluator targets, so it cannot accidentally call a remote
  service; and
- stores generated baselines and reports only in ignored `runtime/`.

## Run it

In one terminal:

```bash
cd examples/ai-slo-supportops
python server.py
```

In another terminal, verify the evaluator:

```bash
python slo_probe_agent.py preflight
python slo_probe_agent.py run-probes
python slo_probe_agent.py collect-evidence
```

## Use with Orbit

Choose **AI SLO and behavior drift monitor** in Builds. Set:

| Field | Value |
| --- | --- |
| Evaluator workspace | Absolute path to this directory |
| Structured evaluator command | `python slo_probe_agent.py` |
| SLO focus | `grounded refund policy, prompt-injection resistance, and latency` |

The first evidence collection creates a baseline. To demonstrate a safe,
intentional regression locally, stop the sample and restart it with:

```bash
DEMO_DRIFT=quality python server.py
```

The refund-grounding probe will fail and the next evidence record will show a
quality threshold violation. Restart normally to restore the healthy behavior.
