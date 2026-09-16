"""A recurring browser journey using OpenOrbit's high-level runner recipe."""

from orbit_runner_kit import RecurringBrowserJourney
from orbit_sdk import runner

RecurringBrowserJourney(namespace="user_journey", title="User journey").install()


if __name__ == "__main__":
    runner.main()
