export const meta = {
  name: 'harness-plan',
  description: 'Ingest one feature and write plan.md, spec-gaps.md and journey.md for validation',
  whenToUse: 'Phases 1-2 of a feature. Args: the feature slug. Run /harness-build after the plan is validated.',
  phases: [
    { title: 'Ingestion', detail: 'targeted code map and conventions' },
    { title: 'Planning', detail: 'sub-tasks, spec gaps, journey' },
  ],
}

const slug = typeof args === 'string' ? args.trim().split(/\s+/)[0] : args && args.slug
if (!slug) throw new Error('usage: /harness-plan <slug>')
// The workspace root is passed, never resolved from a working directory (2.2): args.workspace, else HARNESS_WORKSPACE, which
// harness/bin/link writes into .claude/settings.json so every agent inherits it.
const ROOT = { type: 'object', properties: { workspace: { type: 'string' } }, required: ['workspace'] }
const WS = (args && args.workspace) || ((await agent('Run `printf %s "$HARNESS_WORKSPACE"` and return its stdout, exactly, as workspace.', { label: 'workspace root', schema: ROOT, effort: 'low' })) || {}).workspace
if (!WS || !WS.startsWith('/')) throw new Error('workspace root unknown: HARNESS_WORKSPACE is not set; run harness/bin/link in the workspace and start the session there')
const BIN = `${WS}/harness/bin`
const T = (name) => `${BIN}/${name} --workspace ${WS}`
const FEATURE = `${WS}/product/features/${slug}`
const IO = `Workspace root: ${WS}. Run the commands exactly as written; they are absolute. Write nothing except what the task says. `

const SCOUT = {
  type: 'object',
  properties: {
    spec_exists: { type: 'boolean' }, plan_exists: { type: 'boolean' }, state_exists: { type: 'boolean' },
    design_files: { type: 'array', items: { type: 'string' } },
  },
  required: ['spec_exists', 'plan_exists', 'state_exists', 'design_files'],
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
    journey_steps: { type: 'integer' }, message: { type: 'string' },
  },
  required: ['kind', 'subtask_count', 'gap_count', 'journey_steps', 'message'],
}
const RESULT = {
  type: 'object',
  properties: { ok: { type: 'boolean' }, error: { type: 'string' }, subtask_count: { type: 'integer' } },
  required: ['ok'],
}

// The runtime may refuse to spawn an agent with zero tool uses (15.2): one retry, then a friction with reason runtime. Never an attempt.
const spawn = async (prompt, opts) => {
  for (let i = 0; i < 2; i++) {
    try {
      const r = await agent(prompt, opts)
      if (r) return r
      log(`${opts.label}: the runtime returned nothing${i ? '' : ', retrying once'}`)
    } catch (e) {
      log(`${opts.label}: the runtime refused (${String(e && e.message).slice(0, 100)})${i ? '' : ', retrying once'}`)
    }
  }
  return null
}
const RUNTIME = (label) => `${label} · the runtime refused to start it twice · runtime`
const parseStep = () => agent(
  `${IO}Run \`${T('plan')} ${slug}\`. Exit 0: ok true, subtask_count = length of "subtasks" in its JSON. Otherwise ok false, error = its stderr verbatim.`,
  { label: 'parse plan', schema: RESULT, effort: 'low' })

phase('Ingestion')
const scout = await spawn(
  `${IO}Report on ${FEATURE}: does spec.md exist, does plan.md exist, does state.json exist, and list the files under design/.`,
  { label: 'scout', schema: SCOUT, effort: 'low' })
if (!scout) throw new Error(RUNTIME('scout'))
if (!scout.spec_exists) throw new Error(`${FEATURE}/spec.md is missing: run ${T('new')} ${slug} and fill it in`)
if (scout.plan_exists) log(`plan.md exists for ${slug}: planning reruns and rewrites it`)

const ingestion = await spawn(
  `Workspace root: ${WS}. Feature ${slug}. Run the Ingestion part of your Method on ${FEATURE}/spec.md and ${FEATURE}/design/ (${scout.design_files.length} files). ` +
  `Write ${WS}/product/code-map/ and ${WS}/product/conventions.md. Return the stacks, the zones and a summary under 300 characters.`,
  { agentType: 'planner', label: 'ingest', schema: INGESTION })
if (!ingestion) throw new Error(RUNTIME('ingest'))
log(`ingested ${ingestion.zones.length} zones across ${ingestion.stacks.join(', ')}`)

phase('Planning')
const planning = await spawn(
  `Workspace root: ${WS}. Feature ${slug}. Ingestion found stacks ${ingestion.stacks.join(', ')} and zones ${ingestion.zones.join(', ')}. ${ingestion.summary}\n` +
  `Run the Planning part of your Method. Write ${FEATURE}/plan.md in the exact layout, ${FEATURE}/spec-gaps.md and ${FEATURE}/journey.md. ` +
  'Return kind, the counts, and the plan-ready message in the communicate skill shape as "message".',
  { agentType: 'planner', label: 'plan', schema: PLANNING })
if (!planning) throw new Error(RUNTIME('plan'))

const init = scout.state_exists ? '' : `${T('state')} init ${slug} ${planning.kind}\n`
const patch = JSON.stringify({ kind: planning.kind, phase: 'planning', ingestion: { stacks: ingestion.stacks, zones: ingestion.zones, summary: ingestion.summary } })
const recorded = await spawn(
  `${IO}Run:\n${init}${T('state')} update ${slug} - <<'EOF'\n${patch}\nEOF\nReturn ok true when every command exits 0, else ok false with the stderr as error.`,
  { label: 'record state', schema: RESULT, effort: 'low' })
if (!recorded || !recorded.ok) throw new Error(`state not recorded: ${recorded && recorded.error}`)

let parsed = await parseStep()
if (!parsed || !parsed.ok) {
  log(`plan.md refused: ${parsed && parsed.error}`)
  await spawn(
    `Workspace root: ${WS}. Feature ${slug}. ${T('plan')} refused ${FEATURE}/plan.md:\n${parsed && parsed.error}\nFix plan.md so it follows the layout exactly. Change nothing else.`,
    { agentType: 'planner', label: 'fix plan', schema: RESULT })
  parsed = await parseStep()
  if (!parsed || !parsed.ok) throw new Error(`plan.md still malformed:\n${parsed && parsed.error}`)
}
await spawn(
  `${IO}Run:\n${T('state')} update ${slug} - <<'EOF'\n${JSON.stringify({ plan_message: planning.message })}\nEOF\n${T('notify')} ${slug} plan_ready\nReturn ok true when both exit 0, else ok false with stderr as error.`,
  { label: 'notify', schema: RESULT, effort: 'low' })
await spawn(`${IO}Run \`${T('cost')} ${slug}\`. Return ok by exit code.`, { label: 'cost', schema: RESULT, effort: 'low' })
log(`plan ready: ${parsed.subtask_count} sub-tasks, ${planning.gap_count} gaps, ${planning.journey_steps} journey steps`)
return { plan: `${FEATURE}/plan.md`, subtasks: parsed.subtask_count, gaps: planning.gap_count, journey_steps: planning.journey_steps, message: planning.message }
