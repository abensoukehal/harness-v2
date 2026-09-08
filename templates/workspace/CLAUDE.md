# Workspace: <client>

Root: `<root>`. Every path in this workspace is under it; every tool is `<root>/harness/bin/<tool>`, and reads the root from `HARNESS_WORKSPACE`.
Entry points: `/harness-plan <slug>`, `/harness-build <slug>`, `/harness-retro <slug>`.
Config: `product/client.config.yaml`. Feature files: `product/features/<slug>/`.
Read and write only inside this directory. Never read `secrets/`.
No CLAUDE.md inside `repos/` or `.worktrees/`.
