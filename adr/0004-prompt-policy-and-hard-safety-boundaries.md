# ADR 0004: Prompt-defined policy with hard safety boundaries

Status: accepted

## Decision

Versioned policy prompts determine improvement judgment. Code enforces non-negotiable safety boundaries: command allowlists, secret redaction, approval, ownership and Git conflict refusal.

## Consequences

Policy behavior can evolve and be reviewed without allowing a model to bypass execution safety.
