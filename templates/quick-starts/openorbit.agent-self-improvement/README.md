# Agent self-improvement

Improve a managed prompt from retained responses of the real target AI. Requires a Git repository, prompt file, configured model profile, and one locally installed coding agent: Codex, Claude Code, or Kiro.

The Quick Start stores the selected agent and optional CLI arguments on the
created Build. Each iteration asks that agent to inspect, implement, and
validate an improvement without interactive questions. The agent must finish
with an `ORBIT_AGENT_FEEDBACK:` line for OpenOrbit to register a scoreable
agent result; a run with no such feedback keeps its supervisor feedback but
does not receive a score or decision.
