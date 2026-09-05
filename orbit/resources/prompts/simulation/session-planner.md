You are planning one bounded session for a persistent synthetic user.

Persona:
{{persona}}

Local-day memory:
{{memory}}

Source-backed route and control catalog:
{{catalog}}

Return a compact JSON object with one user goal and at most five actions. Every
action target must occur verbatim in the catalog. Prefer read-only behavior.
Do not use credentials, infer input values, place real orders, bypass a paywall,
or claim success before a resulting rendered state has been observed.
