# Autonomous persona journey

Runs a persistent product persona through one safe, rendered browser action per
iteration. One model turn produces a structured first-person message, stated
perspective, rationale, and intent. A separate action-planning turn receives
only that message plus rendered safe actions, then chooses one bounded action.
The retained history carries those messages into later turns along with
evidence, learnings, deduplicated issues, and the next intent.

The build requires `browser_base_url` and at least one fixed persona case. The
runner excludes destructive links such as checkout, deletion, sign-out, and
subscription actions.
