"""A bounded external JSON agent cycle using the high-level runner recipe."""

from orbit_runner_kit import JsonActionCycle
from orbit_sdk import runner

JsonActionCycle("ORBIT_AGENT_COMMAND", "agent_cycle", "External agent").install()

if __name__ == "__main__":
    runner.main()
