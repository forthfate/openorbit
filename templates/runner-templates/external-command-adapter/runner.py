"""A bounded external command adapter using the high-level runner recipe."""

from orbit_runner_kit import CommandActionCycle
from orbit_sdk import runner

CommandActionCycle("ORBIT_ADAPTER_COMMAND").install()

if __name__ == "__main__":
    runner.main()
