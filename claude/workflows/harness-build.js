export const meta = {
  name: 'harness-build',
  description: 'Build one planned feature unattended: safety net, sub-task loop, QA, delivery',
  whenToUse: 'After plan.md is validated. Args: the feature slug. Relaunching after a crash resumes from state.json.',
  phases: [
    { title: 'Launch', detail: 'parse plan.md, bring the environment up' },
    { title: 'Safety net', detail: 'baseline, regression tests, mutation check' },
    { title: 'Build', detail: 'worker, reviewer and commit per sub-task' },
    { title: 'QA', detail: 'journey, net, baseline diff, visual diff, bounded fixes' },
    { title: 'Delivery', detail: 'push the feature branch, release the environment, report' },
  ],
}

const slug = typeof args === 'string' ? args.trim().split(/\s+/)[0] : args && args.slug
if (!slug) throw new Error('usage: /harness-build <slug>')
// The workspace root is passed, never resolved from a working directory (2.2): args.workspace, else HARNESS_WORKSPACE, which
// harness/bin/link writes into .claude/settings.json so every agent inherits it.
const ROOT = { type: 'object', properties: { workspace: { type: 'string' } }, required: ['workspace'] }
const WS = (args && args.workspace) || ((await agent('Run `printf %s "$HARNESS_WORKSPACE"` and return its stdout, exactly, as workspace.', { label: 'workspace root', schema: ROOT, effort: 'low' })) || {}).workspace
if (!WS || !WS.startsWith('/')) throw new Error('workspace root unknown: HARNESS_WORKSPACE is not set; run harness/bin/link in the workspace and start the session there')
const BIN = `${WS}/harness/bin`
const T = (name) => `${BIN}/${name} --workspace ${WS}`
const FEATURE = `${WS}/product/features/${slug}`
const MAX_RESTARTS = 2
const MAX_PARALLEL = 4
const IO = `Workspace root: ${WS}. Run the commands exactly as written; they are absolute. Write nothing except what the task says. `

const OK = {
  type: 'object',
  properties: { ok: { type: 'boolean' }, error: { type: 'string' }, output: { type: 'string' }, now: { type: 'integer' } },
  required: ['ok'],
}
const LAUNCH = {
  type: 'object',
  properties: {
    plan_ok: { type: 'boolean' }, plan_error: { type: 'string' }, plan: { type: 'object' },
    state_exists: { type: 'boolean' }, state: { type: 'object' },
  },
  required: ['plan_ok', 'state_exists'],
}
const STATE = { type: 'object', properties: { state: { type: 'object' } }, required: ['state'] }
const NET = {
  type: 'object',
  properties: {
    zones: { type: 'array', items: { type: 'object', properties: { zone: { type: 'string' }, mutation_red: { type: 'boolean' } }, required: ['zone', 'mutation_red'] } },
    report: { type: 'string' },
  },
  required: ['zones'],
}
const strings = { type: 'array', items: { type: 'string' } }
// The worker result in the schema dialect agent() accepts: no draft declaration, no $ref, no conditionals. The full contract stays in
// schemas/worker.result.schema.json; bin/state validates an ask against it on update.
const WORKER = {
  type: 'object',
  properties: {
    status: { enum: ['done', 'failed', 'blocked', 'restart', 'needs'] }, report: { type: 'string' }, files: strings, decisions: strings, frictions: strings,
    attempts: { type: 'integer' }, lines_added: { type: 'integer' }, last_error: { type: 'string' },
    reason: { enum: ['oracle', 'budget', 'environment', 'missing_file'] }, stack: { type: 'string' },
    ask: {
      type: 'object',
      properties: {
        where: { type: 'string' }, stuck: { type: 'string' }, tried: strings, question: { type: 'string' },
        options: { type: 'array', items: { type: 'object', properties: { letter: { enum: ['A', 'B', 'C'] }, text: { type: 'string' }, recommended: { type: 'boolean' } }, required: ['letter', 'text', 'recommended'] } },
        still_running: { type: 'string' }, detail: { type: 'string' },
      },
      required: ['where', 'stuck', 'tried', 'question', 'options', 'still_running', 'detail'],
    },
  },
  required: ['status', 'report', 'files', 'decisions', 'frictions', 'attempts'],
}
const REVIEW = {
  type: 'object',
  properties: {
    status: { enum: ['done', 'blocked', 'restart'] }, commit: { type: 'string' }, lines_added: { type: 'integer' }, justification: { type: 'string' },
    last_error: { type: 'string' }, decisions: strings, frictions: strings, report: { type: 'string' },
    stack: { type: 'string' }, reseed: { type: 'boolean' },
  },
  required: ['status', 'report'],
}
const QA = {
  type: 'object',
  properties: {
    failures: { type: 'array', items: { type: 'object', properties: {
      kind: { type: 'string' }, subtask: { type: 'string' }, expected: { type: 'string' }, observed: { type: 'string' }, detail: { type: 'string' },
    }, required: ['kind', 'subtask', 'detail'] } },
  },
  required: ['failures'],
}

// The runtime may refuse to spawn an agent with zero tool uses (15.2): one retry, then a friction with reason runtime. Never an attempt.
let refusal = ''
const spawn = async (prompt, opts) => {
  for (let i = 0; i < 2; i++) {
    try {
      const r = await agent(prompt, opts)
      if (r) return r
      refusal = 'returned nothing'
      log(`${opts.label}: the runtime returned nothing${i ? '' : ', retrying once'}`)
    } catch (e) {
      refusal = String(e && e.message).slice(0, 160)
      log(`${opts.label}: the runtime refused (${refusal})${i ? '' : ', retrying once'}`)
    }
  }
  return null
}
const RUNTIME = (label) => `${label} · the runtime refused to start it twice: ${refusal} · runtime`
const io = (task, opts = {}) => agent(IO + task, { effort: 'low', schema: OK, ...opts })
const readState = async (phaseName) => {
  const r = await spawn(`${IO}Run \`${T('state')} get ${slug}\` and return its JSON verbatim as state.`, { label: 'read state', schema: STATE, effort: 'low', phase: phaseName })
  if (!r) throw new Error('state could not be read')
  return r.state
}
const update = async (patch, phaseName) => {
  const r = await io(`Run:\n${T('state')} update ${slug} - <<'EOF'\n${JSON.stringify(patch)}\nEOF\nExit 0: ok true, now = the "now" value it prints. Otherwise ok false, error = stderr verbatim.`, { label: 'update state', phase: phaseName })
  if (!r || !r.ok) throw new Error(`state update refused: ${r && r.error}`)
  return r.now
}
const refused = async (label, phaseName) => {
  await update({ frictions: [RUNTIME(label)] }, phaseName)
  log(`${label}: recorded as a friction, reason runtime`)
}
const clip = (text) => (text || '').split('\n').slice(-10).join('\n').slice(0, 2000)

// Launch
phase('Launch')
const launch = await spawn(
  `${IO}Run \`${T('plan')} ${slug}\`. Non-zero exit: plan_ok false, plan_error = its stderr verbatim. Exit 0: plan_ok true, plan = its stdout parsed as JSON, verbatim. ` +
  `Then run \`${T('state')} get ${slug}\`: non-zero exit gives state_exists false; otherwise state_exists true and state = its JSON verbatim.`,
  { label: 'launch', schema: LAUNCH, effort: 'low' })
if (!launch) throw new Error('launch agent returned nothing')
if (!launch.plan_ok) throw new Error(`plan.md refused:\n${launch.plan_error}`)
if (!launch.state_exists) throw new Error(`no state for ${slug}: run /harness-plan ${slug} first`)
const plan = launch.plan
const cfg = plan.config
const model = (role) => (cfg.models && cfg.models[role] ? { model: cfg.models[role] } : {})
let state = launch.state
const resuming = state.subtasks.length > 0
if (resuming) {
  log(`state holds ${state.subtasks.length} sub-tasks: state wins over plan.md`)
  const net = await io(`Run \`${T('net')} check ${slug}\`; ok by exit code; output = stdout and stderr.`, { label: 'net check' })
  if (!net || !net.ok) throw new Error(`refusing to start: ${net && (net.error || net.output)}`)
} else {
  const subtasks = plan.subtasks.map(({ role, ...rest }) => rest)
  await update({ kind: plan.kind, subtasks, phase: 'safety_net' })
}
const env = await io(`Run \`${T(resuming ? 'resume' : 'up')} ${slug}\`. ok by exit code; output = the last 20 lines of stdout and stderr.`, { label: resuming ? 'resume' : 'environment up' })
if (!env || !env.ok) throw new Error(`environment failed at the environment step:\n${env && env.output}`)
state = await readState('Launch')
const byId = () => Object.fromEntries(state.subtasks.map((s) => [s.id, s]))
const repoOf = (id) => cfg.stacks[byId()[id].stack].repo

const summary = { blocked: [], skipped: [], gaps: [], delivered: false }
try {
  // Safety net
  phase('Safety net')
  if (state.subtasks.every((s) => s.status === 'done')) {
    log('every sub-task is done: safety net skipped')
  } else {
    const base = await io(`Run \`${T('baseline')} ${slug}\`; ok by exit code; output = stdout and stderr.`, { label: 'client baseline' })
    if (!base || !base.ok) throw new Error(`client baseline could not be recorded: ${base && (base.error || base.output)}`)
    log(`client baseline: ${(base.output || '').split('\n').filter(Boolean).join('; ')}`)
    const net = await spawn(
      `Workspace root: ${WS}. Feature ${slug}. Follow your Method on ${FEATURE}. Zones come from ${WS}/product/code-map/. Return every zone with mutation_red, and a report under ten lines.`,
      { agentType: 'test-writer', label: 'safety net', schema: NET, ...model('worker') })
    if (!net) { await refused('safety net', 'Safety net'); throw new Error('the runtime refused to start the test-writer twice; nothing to build on') }
    const vacuous = net.zones.filter((z) => !z.mutation_red).map((z) => z.zone)
    if (vacuous.length) throw new Error(`safety net is vacuous for ${vacuous.join(', ')}: nothing went red under mutation`)
    const frozen = await io(`Run \`${T('net')} freeze ${slug}\`; ok by exit code; output = stdout and stderr.`, { label: 'net freeze' })
    if (!frozen || !frozen.ok) throw new Error(`safety net could not be frozen: ${frozen && (frozen.error || frozen.output)}`)
    await update({ phase: 'build' })
    log(`safety net: ${net.zones.length} zones pinned, baseline recorded, tests frozen`)
  }

  // Build
  phase('Build')
  // A restart request from a worker or a reviewer (11.1, 19.1): served, respawned, no attempt spent, two per sub-task.
  const serveRestart = async (id, result, count) => {
    if (count > MAX_RESTARTS) return { status: 'blocked', reason: 'environment', last_error: clip(`restart of ${result.stack} requested ${count} times`) }
    const flags = (result.reseed ? ' --reseed' : '') + ` --subtask ${id}`
    const r = await io(`Run \`${T('restart')} ${slug} ${result.stack}${flags}\`; ok by exit code; output = the last 20 lines.`, { label: `restart ${result.stack}`, phase: 'Build' })
    if (!r || !r.ok) return { status: 'blocked', reason: 'environment', last_error: clip(r && (r.error || r.output)) }
    log(`${id} restarted ${result.stack}${result.reseed ? ' with reseed' : ''}, respawning`)
    return true
  }

  const runSubtask = async (id) => {
    const started = await update({ subtasks: [{ id, status: 'running' }] }, 'Build')
    let restarts = 0
    let worker = null
    let review = null
    let outcome = { status: 'blocked', reason: 'worker', last_error: '' }
    try {
      while (true) {
        const brief = await io(`Run \`${T('briefing')} ${slug} ${id}\`; output = its stdout verbatim.`, { label: `${id} briefing`, phase: 'Build' })
        if (!brief || !brief.ok) { outcome = { status: 'blocked', reason: 'briefing', last_error: clip(brief && brief.error) }; break }
        worker = await spawn(brief.output, { agentType: 'worker', label: `${id} worker`, phase: 'Build', schema: WORKER, ...model('worker') })
        if (!worker) { await refused(`${id} worker`, 'Build'); outcome = { status: 'skipped', reason: 'runtime' }; break }
        if (worker.status === 'restart') {
          const served = await serveRestart(id, worker, ++restarts)
          if (served !== true) { outcome = served; break }
          continue
        }
        if (worker.status === 'needs') { outcome = { status: 'blocked', reason: 'needs', last_error: clip(worker.report), ask: worker.ask }; break }
        if (worker.status === 'failed') { outcome = { status: 'blocked', reason: 'criteria', last_error: clip(worker.last_error) }; break }
        if (worker.status === 'blocked') { outcome = { status: 'blocked', reason: worker.reason, last_error: clip(worker.report) }; break }
        review = await spawn(
          `${brief.output}\n\n# Worker report\n${worker.report}\nFiles touched: ${(worker.files || []).join(', ')}`,
          { agentType: 'reviewer', label: `${id} review`, phase: 'Build', schema: REVIEW, ...model('reviewer') })
        if (review && review.status === 'restart') {
          const served = await serveRestart(id, review, ++restarts)
          if (served !== true) { outcome = served; break }
          continue
        }
        if (!review) { await refused(`${id} review`, 'Build'); outcome = { status: 'skipped', reason: 'runtime' }; break }
        if (review.status !== 'done' || !review.commit) {
          outcome = { status: 'blocked', reason: 'review', last_error: clip(review.last_error) }
          break
        }
        outcome = { status: 'done', commit: review.commit, lines_added: review.lines_added ?? worker.lines_added ?? 0 }
        break
      }
    } catch (e) {
      outcome = { status: 'blocked', reason: 'error', last_error: clip(String(e && e.message)) }
    }
    const tag = (lines) => (lines || []).map((l) => (l.startsWith(id) ? l : `${id} · ${l}`))
    const { lines_added, ...rest } = outcome
    const item = { id, ...rest, attempts: outcome.reason === 'runtime' ? byId()[id].attempts : Math.max(1, Math.min(3, (worker && worker.attempts) || 1)) }
    if (outcome.status === 'done') Object.assign(item, { cost: { tokens_in: 0, tokens_out: 0, duration_s: 0, lines_added: outcome.lines_added }, _since: started })
    await update({
      subtasks: [item],
      decisions: [...tag(worker && worker.decisions), ...tag(review && review.decisions)],
      frictions: [...tag(worker && worker.frictions), ...tag(review && review.frictions), ...(review && review.justification ? [`${id} · over line budget · ${review.justification}`] : [])],
    }, 'Build')
    if (outcome.status === 'blocked') summary.blocked.push(`${id}: ${outcome.reason}`)
    if (outcome.status === 'skipped') summary.skipped.push(`${id}: ${outcome.reason}`)
    log(`${id} ${outcome.status}${outcome.commit ? ' ' + outcome.commit.slice(0, 8) : ''}${outcome.reason ? ' (' + outcome.reason + ')' : ''}`)
  }

  const NEXT = { type: 'object', properties: { ready: strings, skipped: strings, pending: { type: 'integer' }, error: { type: 'string' } }, required: ['ready', 'skipped', 'pending'] }
  while (true) {
    const round = await spawn(`${IO}Run \`${T('next')} ${slug}\` and return its JSON verbatim; on a non-zero exit return ready [], skipped [], pending -1 and stderr as error.`,
      { label: 'next round', schema: NEXT, effort: 'low', phase: 'Build' })
    if (!round || round.pending < 0) throw new Error(`build loop stopped: ${round && round.error}`)
    round.skipped.forEach((id) => { summary.skipped.push(id); log(`${id} skipped: a dependency is blocked or skipped`) })
    if (!round.ready.length) break
    await parallel(round.ready.map((id) => () => runSubtask(id)))
  }
  state = await readState('Build')

  if (!state.subtasks.some((s) => s.status === 'done')) {
    await update({ delivered: false })
    log('nothing landed: QA and delivery skipped')
  } else {
    // QA
    phase('QA')
    await update({ phase: 'qa' })
    const runQA = () => agent(
      `Workspace root: ${WS}. Feature ${slug}. Global QA per your Method: ${FEATURE}/journey.md, the safety net, every criterion in ${FEATURE}/state.json, the client suite against client_test_baseline, visual diff on design/. Return the failures.`,
      { agentType: 'qa', label: 'global qa', schema: QA, ...model('qa') })
    let fixes = 0
    let qa = await runQA()
    if (!qa) { await refused('global qa', 'QA'); qa = { failures: [{ kind: 'qa', subtask: 'none', detail: 'global QA did not run: the runtime refused to start it twice' }] }; fixes = cfg.max_fixes }
    while (qa.failures.length && fixes < cfg.max_fixes) {
      for (const f of qa.failures) {
        if (fixes >= cfg.max_fixes) break
        fixes += 1
        const st = byId()[f.subtask]
        if (!st) { log(`fix ${fixes}/${cfg.max_fixes}: ${f.subtask} is not a sub-task, left as a gap`); continue }
        const brief = await io(`Run \`${T('briefing')} ${slug} ${f.subtask}\`; output = its stdout verbatim.`, { label: `${f.subtask} briefing` })
        const mission = `${brief && brief.output}\n\n# QA failure to fix\nkind: ${f.kind}\nexpected: ${f.expected || ''}\nobserved: ${f.observed || ''}\n${f.detail}\nFix this failure only.`
        const w = await spawn(mission, { agentType: 'worker', label: `fix ${f.subtask}`, schema: WORKER, ...model('worker') })
        let r = null
        if (w && w.status === 'done') {
          r = await spawn(`${mission}\n\n# Worker report\n${w.report}`, { agentType: 'reviewer', label: `fix ${f.subtask} review`, schema: REVIEW, ...model('reviewer') })
        }
        log(`fix ${fixes}/${cfg.max_fixes}: ${f.subtask} ${f.kind} ${r && r.status === 'done' ? 'fixed' : 'not fixed'}`)
      }
      qa = (await runQA()) || { failures: [] }
    }
    summary.gaps = qa.failures.map((f) => `${f.subtask} ${f.kind}: ${f.detail.split('\n')[0]}`)
    if (summary.gaps.length) log(`QA stopped at ${fixes} fixes; ${summary.gaps.length} failures remain as known gaps`)

    // Delivery
    phase('Delivery')
    state = await readState('Delivery')
    await update({ phase: 'delivery' })
    // bin/deliver refuses a run with nothing landed or an unchanged branch, and records the refusal itself (10).
    const delivery = await io(`Run \`${T('deliver')} ${slug}\`; ok by exit code; output = stdout and stderr.`, { label: 'push' })
    summary.delivered = Boolean(delivery && delivery.ok)
    if (!summary.delivered) log(`not delivered: ${clip(delivery && (delivery.error || delivery.output))}`)
  }
} finally {
  await io(`Run \`${T('cleanup')} ${slug}\`.`, { label: 'cleanup', phase: 'Delivery' })
}

state = await readState('Delivery')
const wall = state.subtasks.reduce((n, s) => n + ((s.cost && s.cost.duration_s) || 0), 0)
await update({ phase: 'finished', wall_time_s: wall })
const landed = state.subtasks.filter((s) => s.status === 'done').length
const status = !landed ? 'nothing landed' : !summary.delivered ? 'partial' : (landed < state.subtasks.length || summary.gaps.length) ? 'done with gaps' : 'done'
await io(`Run \`${T('cost')} ${slug}\`; ok by exit code; output = stdout.`, { label: 'cost' })
const report = await io(`Run \`${T('report')} ${slug}\` and return its full stdout as output; then run \`${T('notify')} ${slug} run_finished\`. ok when the report exits 0.`, { label: 'report' })
if (!report || !report.ok) throw new Error(`report failed: ${report && report.error}`)
log(`${slug}: ${status}`)
return { status, report: report.output, blocked: summary.blocked, skipped: summary.skipped, gaps: summary.gaps }
