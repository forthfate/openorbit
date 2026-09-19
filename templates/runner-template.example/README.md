# Example runner

Copy this directory to OpenOrbit's `runner-templates` app-data directory.
It demonstrates the node-based lifecycle used by current templates:

`before_all` validates a contract, `execute` publishes structured evidence, and
`after_all` finalizes the task. Add graph nodes only when they own a distinct
responsibility and output.
