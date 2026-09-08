# Harness
Autonomous feature implementation engine, running on Claude Code.
Takes a design plus a spec and implements a feature end to end in a client's repos, unattended, without breaking existing behaviour.

Three layers: this engine (project-agnostic), a private product layer per client (docs, tests, plans), and the client's own repos (receive feature code only).
This repo is the engine. It is pinned inside each client workspace and knows nothing about any client.

- `claude/` holds the workflows, agents and skills a workspace links into its `.claude/`.
- `bin/` holds the workspace scripts. `tests/` holds the engine's own checks.
- `harness-v2-spec.md` is the full design. `CLAUDE.md` is the standing contract every change obeys.
