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

const slug = typeof args === 'string' ? args : args && args.slug
if (!slug) throw new Error('usage: /harness-build <slug>')
const FEATURE = `product/features/${slug}`
const MAX_NEEDS = 3
const MAX_PARALLEL = 4
const IO = 'Run shell commands in the workspace root. Write nothing except what the task says. '

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
    baseline: { type: 'object' },
    zones: { type: 'array', items: { type: 'object', properties: { zone: { type: 'string' }, mutation_red: { type: 'boolean' } }, required: ['zone', 'mutation_red'] } },
    report: { type: 'string' },
  },
  required: ['baseline', 'zones'],
}
const strings = { type: 'array', items: { type: 'string' } }
const WORKER = {
  type: 'object',
  properties: {
    status: { enum: ['done', 'blocked', 'needs'] }, attempts: { type: 'integer' }, files: strings, decisions: strings, frictions: strings,
    reason: { type: 'string' }, last_error: { type: 'string' }, needs_path: { type: 'string' }, needs_why: { type: 'string' },
    lines_added: { type: 'integer' }, report: { type: 'string' },
  },
  required: ['status', 'report'],
}
const REVIEW = {
  type: 'object',
  properties: {
    status: { enum: ['done', 'blocked'] }, commit: { type: 'string' }, lines_added: { type: 'integer' }, justification: { type: 'string' },
    last_error: { type: 'string' }, decisions: strings, frictions: strings, report: { type: 'string' },
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
const REPORT = { type: 'object', properties: { report: { type: 'string' } }, required: ['report'] }

const io = (task, opts = {}) => agent(IO + task, { effort: 'low', schema: OK, ...opts })
const readState = async (phaseName) => {
  const r = await agent(`${IO}Run \`harness/bin/state get ${slug}\` and return its JSON verbatim as state.`, { label: 'read state', schema: STATE, effort: 'low', phase: phaseName })
  if (!r) throw new Error('state could not be read')
  return r.state
}
const update = async (patch, phaseName) => {
  const r = await io(`Run:\nharness/bin/state update ${slug} - <<'EOF'\n${JSON.stringify(patch)}\nEOF\nExit 0: ok true, now = the "now" value it prints. Otherwise ok false, error = stderr verbatim.`, { label: 'update state', phase: phaseName })
  if (!r || !r.ok) throw new Error(`state update refused: ${r && r.error}`)
  return r.now
}
const clip = (text) => (text || '').split('\n').slice(-10).join('\n').slice(0, 2000)

// Launch
phase('Launch')
const launch = await agent(
  `${IO}Run \`harness/bin/plan ${slug}\`. Non-zero exit: plan_ok false, plan_error = its stderr verbatim. Exit 0: plan_ok true, plan = its stdout parsed as JSON, verbatim. ` +
  `Then run \`harness/bin/state get ${slug}\`: non-zero exit gives state_exists false; otherwise state_exists true and state = its JSON verbatim.`,
  { label: 'launch', schema: LAUNCH, effort: 'low' })
if (!launch) throw new Error('launch agent returned nothing')
if (!launch.plan_ok) throw new Error(`plan.md refused:\n${launch.plan_error}`)
if (!launch.state_exists) throw new Error(`no state for ${slug}: run /harness-plan ${slug} first`)
const plan = launch.plan
const cfg = plan.config
const roles = Object.fromEntries(plan.subtasks.map((s) => [s.id, s.role]))
const model = (role) => (cfg.models && cfg.models[role] ? { model: cfg.models[role] } : {})
let state = launch.state
const resuming = state.subtasks.length > 0
if (resuming) {
  log(`state holds ${state.subtasks.length} sub-tasks: state wins, plan.md supplies roles only`)
} else {
  const subtasks = plan.subtasks.map(({ role, ...rest }) => rest)
  await update({ kind: plan.kind, subtasks, phase: 'safety_net' })
}
const env = await io(`Run \`harness/bin/${resuming ? 'resume' : 'up'} ${slug}\`. ok by exit code; output = the last 20 lines of stdout and stderr.`, { label: resuming ? 'resume' : 'environment up' })
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
    const net = await agent(
      `Feature ${slug}. Follow your Method on ${FEATURE}. Zones come from product/code-map/. Return baseline per stack, every zone with mutation_red, and a report under ten lines.`,
      { agentType: 'test-writer', label: 'safety net', schema: NET, ...model('worker') })
    if (!net) throw new Error('test-writer returned nothing')
    const vacuous = net.zones.filter((z) => !z.mutation_red).map((z) => z.zone)
    if (vacuous.length) throw new Error(`safety net is vacuous for ${vacuous.join(', ')}: nothing went red under mutation`)
    await update({ baseline: net.baseline, phase: 'build' })
    log(`safety net: ${net.zones.length} zones pinned, baseline recorded`)
  }

  // Build
  phase('Build')
  const runSubtask = async (id) => {
    const started = await update({ subtasks: [{ id, status: 'running' }] }, 'Build')
    const spentBefore = budget.spent()
    let files = byId()[id].files || []
    let needs = 0
    let worker = null
    let review = null
    let outcome = { status: 'blocked', reason: 'worker', last_error: '' }
    try {
      while (true) {
        const brief = await io(`Run \`harness/bin/briefing ${slug} ${id}\`; output = its stdout verbatim.`, { label: `${id} briefing`, phase: 'Build' })
        if (!brief || !brief.ok) { outcome = { status: 'blocked', reason: 'briefing', last_error: clip(brief && brief.error) }; break }
        worker = await agent(brief.output, { agentType: `${roles[id]}-worker`, label: `${id} ${roles[id]}`, phase: 'Build', schema: WORKER, ...model('worker') })
        if (!worker) { outcome = { status: 'blocked', reason: 'worker', last_error: 'worker returned nothing' }; break }
        if (worker.status === 'needs') {
          needs += 1
          if (needs > MAX_NEEDS || !worker.needs_path) { outcome = { status: 'blocked', reason: 'needs', last_error: clip(`${worker.needs_path}: ${worker.needs_why}`) }; break }
          files = [...files, worker.needs_path]
          await update({ subtasks: [{ id, files }] }, 'Build')
          log(`${id} needs ${worker.needs_path}: added, respawning`)
          continue
        }
        if (worker.status === 'blocked') { outcome = { status: 'blocked', reason: worker.reason || 'worker', last_error: clip(worker.last_error) }; break }
        review = await agent(
          `${brief.output}\n\n# Worker report\n${worker.report}\nFiles touched: ${(worker.files || []).join(', ')}`,
          { agentType: 'reviewer', label: `${id} review`, phase: 'Build', schema: REVIEW, ...model('reviewer') })
        if (!review || review.status !== 'done' || !review.commit) {
          outcome = { status: 'blocked', reason: 'review', last_error: clip(review && review.last_error) }
          break
        }
        outcome = { status: 'done', commit: review.commit, lines_added: review.lines_added ?? worker.lines_added ?? 0 }
        break
      }
    } catch (e) {
      outcome = { status: 'blocked', reason: 'error', last_error: clip(String(e && e.message)) }
    }
    const tag = (lines) => (lines || []).map((l) => (l.startsWith(id) ? l : `${id} · ${l}`))
    const item = { id, ...outcome, attempts: Math.max(1, Math.min(3, (worker && worker.attempts) || 1)) }
    if (outcome.status === 'done') Object.assign(item, { tokens_in: 0, tokens_out: budget.spent() - spentBefore, _since: started })
    await update({
      subtasks: [item],
      decisions: [...tag(worker && worker.decisions), ...tag(review && review.decisions)],
      frictions: [...tag(worker && worker.frictions), ...tag(review && review.frictions), ...(review && review.justification ? [`${id} · over line budget · ${review.justification}`] : [])],
    }, 'Build')
    if (outcome.status === 'blocked') summary.blocked.push(`${id}: ${outcome.reason}`)
    log(`${id} ${outcome.status}${outcome.commit ? ' ' + outcome.commit.slice(0, 8) : ''}${outcome.reason ? ' (' + outcome.reason + ')' : ''}`)
  }

  while (true) {
    state = await readState('Build')
    const map = byId()
    const pending = state.subtasks.filter((s) => s.status === 'pending')
    const stuck = state.subtasks.filter((s) => s.status === 'running')
    if (stuck.length) {
      await update({ subtasks: stuck.map((s) => ({ id: s.id, status: 'blocked', reason: 'error', last_error: 'left running by a failed round' })) }, 'Build')
      stuck.forEach((s) => summary.blocked.push(`${s.id}: error`))
      continue
    }
    if (!pending.length) break
    const dead = (id) => ['blocked', 'skipped'].includes(map[id].status)
    const toSkip = pending.filter((s) => (s.depends_on || []).some(dead))
    if (toSkip.length) {
      await update({ subtasks: toSkip.map((s) => ({ id: s.id, status: 'skipped', reason: `depends on ${s.depends_on.filter(dead).join(', ')}` })) }, 'Build')
      toSkip.forEach((s) => { summary.skipped.push(s.id); log(`${s.id} skipped: depends on ${s.depends_on.filter(dead).join(', ')}`) })
      continue
    }
    const ready = pending.filter((s) => (s.depends_on || []).every((d) => map[d].status === 'done'))
    if (!ready.length) throw new Error(`no runnable sub-task among ${pending.map((s) => s.id).join(', ')}`)
    const batch = []
    const repos = new Set()
    for (const s of ready) {
      const repo = repoOf(s.id)
      if (!repos.has(repo) && batch.length < MAX_PARALLEL) { repos.add(repo); batch.push(s.id) }
    }
    await parallel(batch.map((id) => () => runSubtask(id)))
  }

  // QA
  phase('QA')
  await update({ phase: 'qa' })
  const runQA = () => agent(
    `Feature ${slug}. Global QA per your Method: ${FEATURE}/journey.md, the safety net, every criterion in ${FEATURE}/state.json, the client suite against baseline, visual diff on design/. Return the failures.`,
    { agentType: 'qa', label: 'global qa', schema: QA, ...model('qa') })
  let qa = (await runQA()) || { failures: [] }
  let fixes = 0
  while (qa.failures.length && fixes < cfg.max_fixes) {
    for (const f of qa.failures) {
      if (fixes >= cfg.max_fixes) break
      fixes += 1
      const st = byId()[f.subtask]
      if (!st) { log(`fix ${fixes}/${cfg.max_fixes}: ${f.subtask} is not a sub-task, left as a gap`); continue }
      const brief = await io(`Run \`harness/bin/briefing ${slug} ${f.subtask}\`; output = its stdout verbatim.`, { label: `${f.subtask} briefing` })
      const mission = `${brief && brief.output}\n\n# QA failure to fix\nkind: ${f.kind}\nexpected: ${f.expected || ''}\nobserved: ${f.observed || ''}\n${f.detail}\nFix this failure only.`
      const w = await agent(mission, { agentType: `${roles[f.subtask]}-worker`, label: `fix ${f.subtask}`, schema: WORKER, ...model('worker') })
      let r = null
      if (w && w.status === 'done') {
        r = await agent(`${mission}\n\n# Worker report\n${w.report}`, { agentType: 'reviewer', label: `fix ${f.subtask} review`, schema: REVIEW, ...model('reviewer') })
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
  const pushes = Object.values(state.worktrees).map((wt) =>
    `git -C ${wt} push origin ${state.branch}` + (cfg.mode === 'direct_merge' ? ` && git -C ${wt} push origin ${state.branch}:${cfg.target_branch}` : ''))
  const delivery = await io(`Run, stopping at the first failure:\n${pushes.join('\n')}\nok when every command exits 0; output = the last 20 lines of output.`, { label: 'push' })
  summary.delivered = Boolean(delivery && delivery.ok)
  if (!summary.delivered) {
    await update({ frictions: [`delivery · push refused · ${clip(delivery && delivery.output)}`] })
    log('push refused: recorded as a friction')
  }
} finally {
  await io(`Run \`harness/bin/cleanup ${slug}\`.`, { label: 'cleanup', phase: 'Delivery' })
}

state = await readState('Delivery')
const wall = state.subtasks.reduce((n, s) => n + (s.duration_s || 0), 0)
await update({ phase: 'finished', wall_time_s: wall })
const status = !summary.delivered ? 'partial' : (summary.blocked.length || summary.skipped.length || summary.gaps.length) ? 'done with gaps' : 'done'
const report = await agent(
  `Load the communicate skill. Feature ${slug}, status "${status}". Read ${FEATURE}/state.json, ${FEATURE}/spec-gaps.md, ${FEATURE}/decisions.md and product/cost-log.md. ` +
  `Known gaps from QA: ${JSON.stringify(summary.gaps)}. Write the end-of-run report in the exact shape, then append the cost line to product/cost-log.md ` +
  `(tokens = ${budget.spent()}, wall_time_s = ${wall}, subtasks = ${state.subtasks.length}, blocked = ${summary.blocked.length}). Return the report as "report".`,
  { label: 'report', schema: REPORT, ...model('io') })
log(`${slug}: ${status}`)
return { status, report: report && report.report, blocked: summary.blocked, skipped: summary.skipped, gaps: summary.gaps, tokens_out: budget.spent() }
