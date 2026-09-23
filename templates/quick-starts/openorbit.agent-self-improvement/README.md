# Agent self-improvement

Evaluate a managed AI prompt with retained responses from the real target AI,
then let a locally installed coding agent (Codex, Claude Code, or Kiro) make
one evidence-backed self-improvement in an isolated worktree.

The Quick Start stores the selected agent and optional CLI arguments on the
created Build. The source repository is not changed automatically: OpenOrbit
retains the resulting diff, validation evidence, and supervisor assessment for
review. The agent must finish with an `ORBIT_AGENT_FEEDBACK:` line for
OpenOrbit to register a scoreable agent result; a run with no such feedback
keeps its supervisor feedback but does not receive a score or decision.
