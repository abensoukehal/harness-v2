---
name: criteria-runner
description: How to run each exit-criterion kind and return {pass, detail}.
---

# Criteria runner

Before anything: read `ports` from `state.json`, export `PORT_<STACK>` for every stack. Run from the stack's directory inside the worktree. Commands come from the config, never from memory.

## Kinds
- `test <pattern>`: run `test_runner.<stack>` on the pattern under `product/tests/`. Pass: exit 0.
- `http <METHOD> <url> <status> [<json path> = <value>]`: send the request with `${PORT_*}` expanded. Pass: the status matches and, when given, the json path holds the value.
- `browser <script>`: run the script under `product/tests/` with `test_runner.<stack>`. Pass: exit 0. Selectors decide; screenshots never do.
- `log <stack> <present|absent> <regex>`: after the action, search `.run/<slug>/<stack>.log`, or the file named by the stack's `logs`. Pass: presence matches.
- `visual <region> <reference>`: load the visual-diff skill. Pass: divergence under `visual.threshold_pct`.
- `lint`, `typecheck`: run the stack's config command. Pass: exit 0.
- `examples <set> <floor>`: run every input in the set with temperature pinned and the set seeded; check each expected property. Pass: pass rate at or above the floor. Detail: the failing examples.

## Result
Per criterion: `{pass: true|false, detail: "<ten lines at most: the assertion or the diff, no stack trace>"}`.
A runner error (missing command, stack down, file absent) is a fail with the error as detail. Never a skip.
