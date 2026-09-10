# Quick starts

Status: accepted

## Goal

Let an operator create a ready-to-run evaluation without first manually
creating every reusable asset. A quick start is a declarative package that
collects only the inputs it needs and then creates the complete evaluation
configuration.

## Operator flow

1. From **Builds → Create**, choose **Start with Quick Start** or
   **Configure manually**.
2. Select a quick-start card.
3. Supply the manifest-defined parameters. Each field may provide a type,
   default value, description, options and placeholder.
4. Review the input values before creation.
5. Create the configuration. The operator can inspect or run the evaluation
   afterward; creation does not start a run.

The dashboard quick-start action opens this same flow directly.

## Manifest contract

A quick start has a qualified ID, semantic version, publisher, display name,
description, `schema_version`, parameters, assets and build template.

Parameters use lowercase identifiers and may be `string`, `workspace`, `url`,
`select` or a saved `model_profile`. A parameter may be required and may define
`default`, `description`, `placeholder` and `options`. Template values can
reference parameter values with `${parameter_key}`.

The manifest declares these required assets:

- runner source and metadata;
- manager prompt template;
- fixed target-AI test-case set;
- execution environment;
- target environment; and
- build.

It may also declare a model-profile asset. When it does, the form collects the
connection settings and creates a new reusable profile before the evaluation
build is created. Secrets remain environment-variable names; secret values are
never put in a manifest or sent through the API.

## Safety and recovery

Before writing, Orbit validates required parameters, runner syntax, supported
workspace paths, referenced assets and ID conflicts. All generated asset IDs
are instance-scoped. If any write or validation after writing fails, Orbit
restores the prior state and leaves no partial quick-start instance.

Importing a quick start only stores and validates its declaration. It does not
execute runner source or start a process. Imported runner code is visible as a
created asset before any evaluation is run.

## Planned work

Show a full generated-asset preview before creation and validate parameter types
and option values server-side.

## Built-in quick starts

| Quick start | Purpose | Runner |
| --- | --- | --- |
| User journey smoke test | Validate a named browser journey with operator-provided path, actions and success evidence. | Browser journey runner |
| Site exploration review | Explore safe same-site links and assess the rendered experience with evidence. | LangGraph site exploration runner |
| Agent self-improvement | Validate prompt or agent changes in a Git repository against a fixed browser journey and retain rollback-ready evidence. | Native improvement cycle |
| AI SLO and behavior drift monitor | Repeatedly assess structured AI quality, safety, latency, and cost evidence against a fixed baseline and retain supervised improvement decisions. | Evidence-gated probe cycle |
