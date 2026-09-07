# ADR 0004: Prompt-defined policy with hard safety boundaries

Status: accepted

## Decision

Versioned policy prompts determine supervisor judgment. Code currently enforces approved workspace boundaries, argument-array process launch by the control room and environment-variable secret references.

## Planned work

Add command allowlists, output redaction, high-impact approval gates and dirty-worktree/conflict refusal before enabling automated source changes.

## Consequences

Policy behavior can evolve and be reviewed without allowing a model to bypass execution safety.
