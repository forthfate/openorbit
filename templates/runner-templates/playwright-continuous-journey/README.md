# Playwright continuous journey

Runs one focused Playwright journey per iteration. Failed cases are retried
before the runner advances to the next fixed journey, while evidence and the
next-iteration handoff remain available to supervision.

The build requires `browser_base_url` and at least one fixed browser test case.
