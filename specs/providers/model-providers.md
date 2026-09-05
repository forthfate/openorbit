# Model providers

Status: accepted

## Supported providers

- Azure OpenAI through Azure Responses-compatible endpoints.
- AWS Bedrock through the AWS credential chain and `converse`-compatible models.

## Configuration

The dashboard configures provider, model/deployment, endpoint, region, token/reasoning limits and a **secret reference name**. It never stores secret values. A hello action makes a bounded request and records connectivity, latency, model metadata and trace ID.

## Policy invocation

The evaluation phase renders the versioned policy prompt with bounded evidence and requests structured output. The runner validates output schema, allowed action, candidate ownership and safety constraints before acting.
