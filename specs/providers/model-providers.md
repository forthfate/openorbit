# Model providers

Status: accepted

## Supported providers

- Azure OpenAI through Azure Responses-compatible endpoints.
- AWS Bedrock through the AWS credential chain and `converse`-compatible models.

## Configuration

The dashboard configures provider, model/deployment, endpoint, region and a **secret reference name**. It never stores secret values. A hello action makes a bounded request and creates a local OTEL span; its UI response currently contains the provider response only.

## Policy invocation

The evaluation phase renders the versioned policy prompt with bounded evidence and validates the returned response schema. Source-changing policy actions are not implemented.

## Planned work

Expose hello latency/model metadata/trace ID, configure token and reasoning limits, and enforce policy output safety constraints before any future source-changing action.
