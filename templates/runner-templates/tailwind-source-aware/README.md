# Tailwind source-aware journey

Validates that the target repository contains a Tailwind stylesheet or config,
then captures Playwright evidence for its rendered fixed browser journeys.

The build requires `browser_base_url` and at least one fixed browser test case.
Tailwind source files are evidence for project context; rendered browser output
remains the evidence for user-visible behavior.
