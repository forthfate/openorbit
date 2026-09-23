# Autonomous persona journey

Runs a persistent product persona through one safe, rendered browser action per
iteration. The persona observes visible same-origin links, chooses one bounded
action through the configured model, and retains evidence, learnings,
deduplicated issues, and the next intent.

The build requires `browser_base_url` and at least one fixed persona case. The
runner excludes destructive links such as checkout, deletion, sign-out, and
subscription actions.
