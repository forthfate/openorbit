# Source-aware browser journey

Use this runner when a browser journey is valid only if a required source
contract is present in the target repository.

Set `ORBIT_SOURCE_CONTRACT_PATTERN` in the execution environment to a regular
expression understood by `rg` (for example, `tailwindcss|@tailwind`). Optionally
set `ORBIT_SOURCE_CONTRACT_GLOB` to limit the search, such as `*.css`.

The build also requires `browser_base_url` and one or more fixed browser test
cases. The runner first records matching source files, then captures the
rendered Playwright evidence for the selected journeys.
