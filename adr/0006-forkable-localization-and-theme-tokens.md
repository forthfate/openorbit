# ADR 0006: Forkable localization and theme tokens

Status: accepted

## Decision

Store shared operator text in locale resources and shared visual choices in theme tokens, with dark mode as default.

## Current implementation

English, Korean and Japanese locale resources and two dark themes are supplied. Some legacy UI text and colors remain embedded in feature components and CSS.

## Planned work

Move remaining operator-facing text and visual literals into locale and theme resources.

## Consequences

Forks can replace language and branding without rewriting workflow runner behavior.
