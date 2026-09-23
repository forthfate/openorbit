# Selenium external journey

Connect an existing Selenium adapter while OpenOrbit owns lifecycle scheduling,
evidence collection, and supervision. Set `ORBIT_SELENIUM_COMMAND` to a command
that accepts `status`, `prepare`, `run-once`, and `collect-evidence` actions.

Each adapter call is bounded to one lifecycle phase and its output is retained
as Selenium journey evidence.
