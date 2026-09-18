# Example Quick Start

Copy this directory to OpenOrbit's `quick-starts` app-data directory, then
create it from the Quick Starts page. The manifest creates a runner, prompt,
fixed test case, execution environment, target environment, and build.

The runner intentionally uses three independently executable graph nodes:
validate, run, and finalize. Extend it with additional nodes only for distinct
responsibilities with their own evidence or outputs.
