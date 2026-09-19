from orbit_runner_kit import JsonActionCycle
from orbit_sdk import runner

JsonActionCycle(
    "ORBIT_PROBE_COMMAND",
    "probe_gate",
    "Probe matrix",
    actions=("preflight", "prepare", "run-probes", "collect-evidence"),
    payload_key="probes",
).install()

if __name__ == "__main__":
    runner.main()
