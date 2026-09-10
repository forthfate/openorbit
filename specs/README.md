# Specifications

These documents define accepted product and engineering contracts. They are not implementation notes.

| Specification | Status | Purpose |
| --- | --- | --- |
| [Control room](product/control-room.md) | accepted | Current control-room views and user operations |
| [Control-room loading states](product/loading-states.md) | accepted | Initial-load skeleton and refresh behavior contract |
| [Quick starts](product/quick-starts.md) | accepted | Declarative packages for creating ready-to-run evaluations |
| [Workflow lifecycle](runtime/workflow-lifecycle.md) | accepted | Required phase order, process ownership and cancellation |
| [Docker parallel execution](runtime/docker-parallel-execution.md) | planned | Linux-only isolated parallel execution design |
| [OpenTelemetry](observability/open-telemetry.md) | accepted | Operational trace, event, log and redaction contract |
| [Evidence loop](improvement/evidence-loop.md) | accepted | Improvement evidence, PDCA, approval, commit and rollback |
| [Model providers](providers/model-providers.md) | accepted | Azure/AWS configuration, hello verification and secret boundaries |

Each specification distinguishes current implementation from planned work where that distinction matters.
