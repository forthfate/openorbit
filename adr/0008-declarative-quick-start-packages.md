# ADR 0008: Declarative quick-start packages

Status: accepted

## Decision

Use versioned, declarative quick-start manifests to create a build
and its required assets. A manifest declares its input parameters, placeholders,
asset templates and build template; it does not run an arbitrary installation
hook.

The control room validates all inputs first, shows the requested configuration
for review, then creates the runner, prompt template, test-case set, execution
environment, target environment, optional model profile and build as
one recoverable operation.

## Consequences

Quick starts can be supplied by OpenOrbit or imported from external developers
without each provider adding control-room UI code. Parameter placeholders and
typed options make the setup form self-describing.

An unsuccessful instantiation restores the previous local asset state. Runner
source remains an explicit, reviewable asset and is never executed merely by
importing a manifest. A user must still explicitly start an evaluation after
creation.
