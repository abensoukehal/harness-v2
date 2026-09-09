export const meta = {
  name: 'harness-plan',
  description: 'Ingest one feature and write plan.md, spec-gaps.md and journey.md for validation',
  whenToUse: 'Phases 1-2 of a feature. Args: the feature slug. Run /harness-build after the plan is validated.',
  phases: [
    { title: 'Ingestion', detail: 'targeted code map and conventions' },
    { title: 'Planning', detail: 'sub-tasks, spec gaps, journey' },
  ],
}

// Decisions (14.7). Every branch this script takes on its own lives here as a pure function over data — no agent, no
// command, no closed-over state — so tests/workflow-decisions.test.js lifts this block between the two markers and
// drives, for each one, the input that trips it and the input that does not. Below the block the script sequences.
/* decisions:start */
const slugOf = (a) => (typeof a === 'string' ? a.trim().split(/\s+/)[0] : (a && a.slug)) || ''
const workspaceRefusal = (ws) => (ws && ws.startsWith('/') ? null
  : 'workspace root unknown: HARNESS_WORKSPACE is not set; run harness/bin/link in the workspace and start the session there')
// The runtime may refuse to spawn an agent with zero tool uses (15.2): one retry, then a friction with reason runtime.
const retrying = async (call, label, note) => {
  let refusal = ''
  for (let i = 0; i < 2; i++) {
    try {
      const r = await call()
      if (r) return { result: r }
      refusal = 'returned nothing'
      note(`${label}: the runtime returned nothing${i ? '' : ', retrying once'}`)
    } catch (e) {
      refusal = String(e && e.message).slice(0, 160)
      note(`${label}: the runtime refused (${refusal})${i ? '' : ', retrying once'}`)
    }
  }
  return { friction: `${label} · the runtime refused to start it twice: ${refusal} · runtime` }
}
const agentOpts = (agents, role) => (agents && agents[role]) || (role === 'io' ? { effort: 'low' } : {})  // the io default, spelled out once
const okRefusal = (what, r) => (r && r.ok ? null : `${what}: ${(r && r.error) || 'the runtime returned nothing'}`)
const specRefusal = (feature, remedy, scout) => (scout.spec_exists ? null
  : `${feature}/spec.md is missing: run ${remedy} and fill it in`)
const parseRefusal = (parsed) => (parsed && parsed.ok ? null : `plan.md refused: ${parsed && parsed.error}`)
/* decisions:end */

const slug = slugOf(args)
if (!slug) throw new Error('usage: /harness-plan <slug>')
// The workspace root is passed, never resolved from a working directory (2.2): args.workspace, else HARNESS_WORKSPACE, which
// harness/bin/link writes into .claude/settings.json so every agent inherits it.
const ROOT = { type: 'object', properties: { workspace: { type: 'string' } }, required: ['workspace'] }
const WS = (args && args.workspace) || ((await agent('Run `printf %s "$HARNESS_WORKSPACE"` and return its stdout, exactly, as workspace.', { label: 'workspace root', schema: ROOT, effort: 'low' })) || {}).workspace
const rootProblem = workspaceRefusal(WS)
if (rootProblem) throw new Error(rootProblem)
const BIN = `${WS}/harness/bin`
const T = (name) => `${BIN}/${name} --workspace ${WS}`
const FEATURE = `${WS}/product/features/${slug}`
const IO = `Workspace root: ${WS}. Run the commands exactly as written; they are absolute. Write nothing except what the task says. `

const SCOUT = {
  type: 'object',
  properties: {
    spec_exists: { type: 'boolean' }, plan_exists: { type: 'boolean' }, state_exists: { type: 'boolean' },
    design_files: { type: 'array', items: { type: 'string' } }, agents: { type: 'object' },
  },
  required: ['spec_exists', 'plan_exists', 'state_exists', 'design_files', 'agents'],
}
const INGESTION = {
  type: 'object',
  properties: { stacks: { type: 'array', items: { type: 'string' } }, zones: { type: 'array', items: { type: 'string' } }, summary: { type: 'string' } },
  required: ['stacks', 'zones', 'summary'],
}
const PLANNING = {
  type: 'object',
  properties: {
    kind: { enum: ['ui', 'service', 'mixed'] }, subtask_count: { type: 'integer' }, gap_count: { type: 'integer' },
    journey_steps: { type: 'integer' },
  },
  required: ['kind', 'subtask_count', 'gap_count', 'journey_steps'],
}
const RESULT = {
  type: 'object',
  properties: { ok: { type: 'boolean' }, error: { type: 'string' }, subtask_count: { type: 'integer' } },
  required: ['ok'],
}

let RUNTIME = ''  // the friction the last refusal produced
const spawn = async (prompt, opts) => {
  const r = await retrying(() => agent(prompt, opts), opts.label, log)
  RUNTIME = r.friction || ''
  return r.result || null
}
const parseStep = () => agent(
  `${IO}Run \`${T('plan')} ${slug}\`. Exit 0: ok true, subtask_count = length of "subtasks" in its JSON. Otherwise ok false, error = its stderr verbatim.`,
  { label: 'parse plan', schema: RESULT, ...A('io') })

phase('Ingestion')
const scout = await spawn(
  `${IO}Report on ${FEATURE}: does ${FEATURE}/spec.md exist, does ${FEATURE}/plan.md exist, does ${FEATURE}/state.json exist, and list the files under ${FEATURE}/design. ` +
  `Then run \`${T('agents')}\` and return its JSON verbatim as agents.`,
  { label: 'scout', schema: SCOUT, effort: 'low' })  // before the config is read: the io default, spelled out once
if (!scout) throw new Error(RUNTIME)
// Model and effort per role are config, never this script (6.3).
const A = (role) => agentOpts(scout.agents, role)
const noSpec = specRefusal(FEATURE, `${T('new')} ${slug}`, scout)
if (noSpec) throw new Error(noSpec)
if (scout.plan_exists) log(`plan.md exists for ${slug}: planning reruns and rewrites it`)

const ingestion = await spawn(
  `Workspace root: ${WS}. Feature ${slug}. Every path below is absolute; use these, resolve none yourself. ` +
  `Run the Ingestion part of your Method on ${FEATURE}/spec.md and ${FEATURE}/design (${scout.design_files.length} files). ` +
  `Write ${WS}/product/code-map/ and ${WS}/product/conventions.md. Return the stacks, the zones and a summary under 300 characters.`,
  { agentType: 'planner', label: 'ingest', schema: INGESTION, ...A('planner') })
if (!ingestion) throw new Error(RUNTIME)
log(`ingested ${ingestion.zones.length} zones across ${ingestion.stacks.join(', ')}`)

phase('Planning')
const planning = await spawn(
  `Workspace root: ${WS}. Feature ${slug}. Every path below is absolute; use these, resolve none yourself. ` +
  `Ingestion found stacks ${ingestion.stacks.join(', ')} and zones ${ingestion.zones.join(', ')}. ${ingestion.summary}\n` +
  `Run the Planning part of your Method. Write ${FEATURE}/plan.md in the exact layout, ${FEATURE}/spec-gaps.md and ${FEATURE}/journey.md. ` +
  'Return kind and the counts. The plan-ready message is rendered from the plan by a tool (13.3); write none.',
  { agentType: 'planner', label: 'plan', schema: PLANNING, ...A('planner') })
if (!planning) throw new Error(RUNTIME)

const init = scout.state_exists ? '' : `${T('state')} init ${slug} ${planning.kind}\n`
const patch = JSON.stringify({ kind: planning.kind, phase: 'planning', ingestion: { stacks: ingestion.stacks, zones: ingestion.zones, summary: ingestion.summary } })
const recorded = await spawn(
  `${IO}Run:\n${init}${T('state')} update ${slug} - <<'EOF'\n${patch}\nEOF\nReturn ok true when every command exits 0, else ok false with the stderr as error.`,
  { label: 'record state', schema: RESULT, ...A('io') })
const notRecorded = okRefusal('state not recorded', recorded)
if (notRecorded) throw new Error(notRecorded)

let parsed = await parseStep()
let malformed = parseRefusal(parsed)
if (malformed) {
  log(malformed)
  await spawn(
    `Workspace root: ${WS}. Feature ${slug}. ${T('plan')} refused ${FEATURE}/plan.md:\n${parsed && parsed.error}\nFix plan.md so it follows the layout exactly. Change nothing else.`,
    { agentType: 'planner', label: 'fix plan', schema: RESULT, ...A('planner') })
  parsed = await parseStep()
  malformed = parseRefusal(parsed)
  if (malformed) throw new Error(`still ${malformed}`)
}
// The plan review is a tool over the parsed plan (13.3): the summary, the three numbers and the graph Ali reads, no model.
const reviewed = await spawn(
  `${IO}Run:\n${T('review')} ${slug}\n${T('notify')} ${slug} plan_ready\nReturn ok true when both exit 0, else ok false with stderr as error.`,
  { label: 'review and notify', schema: RESULT, ...A('io') })
const refusedPlan = okRefusal('the plan review refused the plan', reviewed)
if (refusedPlan) throw new Error(refusedPlan)
await spawn(`${IO}Run \`${T('cost')} ${slug}\`. Return ok by exit code.`, { label: 'cost', schema: RESULT, ...A('io') })
log(`plan ready: ${parsed.subtask_count} sub-tasks, ${planning.gap_count} gaps, ${planning.journey_steps} journey steps`)
return { plan: `${FEATURE}/plan.md`, graph: `${FEATURE}/plan.mmd`, subtasks: parsed.subtask_count, gaps: planning.gap_count, journey_steps: planning.journey_steps }
