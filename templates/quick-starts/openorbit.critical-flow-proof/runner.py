from orbit_runner_kit import RecurringBrowserJourney
from orbit_sdk import runner

RecurringBrowserJourney(namespace="continuous_journey", title="Critical flow").install()

if __name__ == "__main__":
    runner.main()
