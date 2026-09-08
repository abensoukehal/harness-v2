# Harness

Project-agnostic engine that implements features in client repos it does not own.
Runs on Claude Code. Knows nothing about any client. Leaves no trace of itself in
client code.

## File hygiene
- Every file holds only the current instruction set. No changelog, no dates, no
  ticket ids, no wording that points at an earlier state. History lives in git
  commits; the commit message carries the why.
- Write instructions in the imperative, present tense.
- Edit, never stack. One subject, one rule, one location. To change behaviour,
  rewrite the existing rule. Add a rule only for a subject no file covers.
- Every file has a size cap. Near the cap, consolidate. Never open a new file to
  hold the overflow.
- Total instruction text across this repo stays under 40,000 characters. Past
  that, record the problem in OPEN_QUESTIONS.md instead of writing more.
- Never generate an aggregate file. Agents that need the same block load the
  same file.
- A file that grows across three consecutive retros while no other file shrinks
  goes to OPEN_QUESTIONS.md as a design problem.
- Hygiene is a grep, `tests/hygiene.sh`, never an agent's judgement of its own
  writing. Never commit a tree that fails it.

## Autonomy
- The build workflow takes no user input mid-run. Take every decision the plan
  leaves open, execute it, record it in decisions.md with its source.
- Cite the ground for every decision: the spec, the design, an existing pattern
  in client code, or own judgement with a stated reason. Never present judgement
  as spec.
- A worker that cannot proceed marks the subtask BLOCKED and the run moves on.
  BLOCKED is computed from the plan, never declared by an agent.
- Park, never halt. One blocked subtask parks; every runnable subtask continues.
- A report is never a question. It ends with what happened and states what is
  still running.
- At a human checkpoint use the ask format: lettered options, one line each,
  recommendation marked, plain words above a `Detail:` line, everything
  technical below it.

## Tests are the oracle
- Tests written before implementation are frozen. The implementer never edits
  them. A test that looks wrong is a stop.

## Reduction
- When replacing a path, delete the old one in the same subtask.
- Grep the module's existing helpers before writing a new one.

## Confidentiality
- No CLAUDE.md inside any client repo.
- Nothing in this repo names a client, a client repo, or a client service.
