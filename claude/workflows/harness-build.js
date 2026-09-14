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
const clip = (text) => (text || '').split('\n').slice(-10).join('\n').slice(0, 2000)
const agentOpts = (agents, role) => (agents && agents[role]) || {}
const launchRefusal = (slug, r) => !r ? 'launch agent returned nothing'
  : !r.plan_ok ? `plan.md refused:\n${r.plan_error}`
  : !r.state_exists ? `no state for ${slug}: run /harness-plan ${slug} first`
  : null
const resumes = (state) => state.subtasks.length > 0
const netSkipped = (state) => state.subtasks.every((s) => s.status === 'done')
const vacuousRefusal = (net) => {
  const zones = (net.zones || []).filter((z) => !z.mutation_red).map((z) => z.zone)
  return zones.length ? `safety net is vacuous for ${zones.join(', ')}: nothing went red under mutation` : null
}
// A batch runs several commands under one spawn, so its failure has to name which one (15.1). A command that did
// not run at all is a refusal too: a batch that silently skipped a step is worse than the spawn it saved.
const batchRefusal = (what, asked, r, optional = []) => {
  if (!r || !r.commands) return `${what}: the runtime returned nothing`
  const bad = r.commands.find((c) => !c.ok && !optional.includes(c.name))
  if (bad) return `${what}: ${bad.name} refused: ${clip(bad.error || bad.output || 'no output')}`
  const gone = asked.find((n) => !optional.includes(n) && !r.commands.some((c) => c.name === n && c.ok))
  return gone ? `${what}: ${gone} did not run` : null
}
const resultOf = (r, name) => ((r && r.commands) || []).find((c) => c.name === name) || {}
const roundRefusal = (round) => (round && round.pending >= 0 ? null : `build loop stopped: ${round && round.error}`)
const briefingFailed = (r) => (resultOf(r, 'briefing').ok ? null
  : { status: 'blocked', reason: 'briefing', last_error: clip(resultOf(r, 'briefing').error) })
const restartCapped = (count, max, stack) => (count > max
  ? { status: 'blocked', reason: 'environment', last_error: clip(`restart of ${stack} requested ${count} times`) } : null)
const restartFailed = (r) => (resultOf(r, 'restart').ok ? null
  : { status: 'blocked', reason: 'environment', last_error: clip(resultOf(r, 'restart').error || resultOf(r, 'restart').output) })
const workerOutcome = (w) => w.status === 'needs' ? { status: 'blocked', reason: 'needs', last_error: clip(w.report), ask: w.ask }
  : w.status === 'failed' ? { status: 'blocked', reason: 'criteria', last_error: clip(w.last_error) }
  : w.status === 'blocked' ? { status: 'blocked', reason: w.reason, last_error: clip(w.report) }
  : null  // done, or a restart the loop serves
const reviewOutcome = (r, w) => (r.status === 'done' && r.commit
  ? { status: 'done', commit: r.commit, lines_added: r.lines_added ?? w.lines_added ?? 0 }
  : { status: 'blocked', reason: 'review', last_error: clip(r.last_error) })
// The third worker result (5.5): an observation, not a status. The sub-task keeps the status it earned and the
// criteria run unchanged. One per sub-task, and that cap is bin/state's at the fold, never this script's.
const notedOf = (worker) => (worker && worker.noted ? { noted: worker.noted } : {})
// The reviewer answers two questions on one diff (4.4): did the worker work around a test, and does this code belong.
// The second verdict is binary — one line to fix, or nothing. A blank convention is a pass, not a soft return.
// Criteria first: `done` is the reviewer's own criteria run coming back green, and a red sub-task is never returned
// for how it is written, or the worker gets two signals in one turn and cannot tell which to fix first.
const conventionReturn = (review) => (review && review.status === 'done'
  ? String(review.convention || '').trim() || null : null)
// A convention return spends an attempt against the same ceiling. An uncounted loop is an unbounded loop.
const returnCapped = (spent, reason) => (spent >= 3
  ? { status: 'blocked', reason: 'convention', last_error: clip(reason) } : null)
// A refusal spends no attempt: the sub-task keeps the count it had.
const attemptsOf = (worker, outcome, previous, spent = 1) => (outcome.reason === 'runtime' ? previous
  : Math.max(1, Math.min(3, Math.max((worker && worker.attempts) || 1, spent))))
const overBudget = (review, lines, budget) => Boolean(review && review.justification && lines > (budget ?? Infinity))
const landedCount = (state) => state.subtasks.filter((s) => s.status === 'done').length
const runStatus = (landed, total, delivered, gaps) => !landed ? 'nothing landed'
  : !delivered ? 'partial'
  : (landed < total || gaps) ? 'done with gaps' : 'done'
/* decisions:end */

const slug = slugOf(args)
if (!slug) throw new Error('usage: /harness-build <slug>')
// The workspace root is passed, never resolved from a working directory (2.2): args.workspace, else HARNESS_WORKSPACE, which
// harness/bin/link writes into .claude/settings.json so every agent inherits it.
const ROOT = { type: 'object', properties: { workspace: { type: 'string' } }, required: ['workspace'] }
const WS = (args && args.workspace) || ((await agent('Run `printf %s "$HARNESS_WORKSPACE"` and return its stdout, exactly, as workspace.', { label: 'workspace root', schema: ROOT, agentType: 'io', effort: 'low' })) || {}).workspace
const rootProblem = workspaceRefusal(WS)
if (rootProblem) throw new Error(rootProblem)
const BIN = `${WS}/harness/bin`
const T = (name) => `${BIN}/${name} --workspace ${WS}`
const FEATURE = `${WS}/product/features/${slug}`
const MAX_RESTARTS = 2
const MAX_PARALLEL = 4
const IO = `Workspace root: ${WS}. Run the commands exactly as written; they are absolute. Write nothing except what the task says. `

const RUN = {
  type: 'object',
  properties: {
    commands: { type: 'array', items: { type: 'object', properties: {
      name: { type: 'string' }, ok: { type: 'boolean' }, output: { type: 'string' }, error: { type: 'string' },
    }, required: ['name', 'ok'] } },
  },
  required: ['commands'],
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
    attempts: { type: 'integer' }, lines_added: { type: 'integer' }, last_error: { type: 'string' }, noted: { type: 'string' },
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
    convention: { type: 'string' },
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

let RUNTIME = ''  // the friction the last refusal produced, recorded by refused()
const spawn = async (prompt, opts) => {
  const r = await retrying(() => agent(prompt, opts), opts.label, log)
  RUNTIME = r.friction || ''
  return r.result || null
}
// One io spawn carries ~52k of context whatever it is asked, so consecutive commands with no agent between them
// travel together (6.2, 6.3). agentType 'io' is the restricted-tool agent: no skill catalogue, no tool catalogue.
const step = (name, command, want, optional) => ({ name, command, want, optional: Boolean(optional) })
const getState = (name) => step(name, `${T('state')} get ${slug}`, 'ok by exit code; output = its JSON verbatim')
const setState = (name, patch) => step(name, `${T('state')} update ${slug} - <<'EOF'\n${JSON.stringify(patch)}\nEOF`,
  'ok by exit code; output = the "now" value it prints')
const runAll = async (label, steps, phaseName) => {
  const listed = steps.map((s, i) => `${i + 1}. name: ${s.name}\n   run:\n${s.command}\n   return: ${s.want}`).join('\n')
  const r = await spawn(
    `${IO}Run these ${steps.length} commands in order, and stop at the first one that exits non-zero.\n${listed}\n` +
    'Return one entry per command you ran, in order: name exactly as given above, ok by its exit code, output as that ' +
    'command\'s return line asks for, and error = its stderr verbatim when it did not exit 0. ' +
    'Report no entry for a command you never reached.',
    { label, schema: RUN, agentType: 'io', ...A('io'), phase: phaseName })
  const problem = batchRefusal(label, steps.filter((s) => !s.optional).map((s) => s.name), r, steps.filter((s) => s.optional).map((s) => s.name))
  if (problem) throw new Error(problem)
  return r
}
const brief = (id) => step('briefing', `${T('briefing')} ${slug} ${id}`, 'ok by exit code; output = its stdout verbatim', true)
const stateFrom = (r, name) => JSON.parse(resultOf(r, name).output)
const refused = async (label, phaseName) => {
  await runAll(`${label} friction`, [setState('friction', { frictions: [RUNTIME] })], phaseName)
  log(`${label}: recorded as a friction, reason runtime`)
}
// Launch
phase('Launch')
const launch = await spawn(
  `${IO}Run \`${T('plan')} ${slug}\`. Non-zero exit: plan_ok false, plan_error = its stderr verbatim. Exit 0: plan_ok true, plan = its stdout parsed as JSON, verbatim. ` +
  `Then run \`${T('state')} get ${slug}\`: non-zero exit gives state_exists false; otherwise state_exists true and state = its JSON verbatim.`,
  { label: 'launch', schema: LAUNCH, agentType: 'io', effort: 'low' })  // before the config is parsed: the io default, spelled out once
const launchProblem = launchRefusal(slug, launch)
if (launchProblem) throw new Error(launchProblem)
const plan = launch.plan
const cfg = plan.config
// Model and effort per role come from the config, never from this script (6.3); harness/bin/agents resolved them and bin/plan passed them through.
const A = (role) => agentOpts(cfg.agents, role)
let state = launch.state
const resuming = resumes(state)
if (resuming) log(`state holds ${state.subtasks.length} sub-tasks: state wins over plan.md`)
const opening = await runAll('launch', [
  resuming
    ? step('net-check', `${T('net')} check ${slug}`, 'ok by exit code; output = stdout and stderr')
    : setState('plan-in', { kind: plan.kind, subtasks: plan.subtasks.map(({ role, ...rest }) => rest), phase: 'safety_net' }),
  step('environment', `${T(resuming ? 'resume' : 'up')} ${slug}`, 'ok by exit code; output = the last 20 lines of stdout and stderr'),
  step('baseline', `${T('baseline')} ${slug}`, 'ok by exit code; output = stdout and stderr'),
  getState('state'),
], 'Launch')
log(`client baseline: ${(resultOf(opening, 'baseline').output || '').split('\n').filter(Boolean).join('; ')}`)
state = stateFrom(opening, 'state')
const byId = () => Object.fromEntries(state.subtasks.map((s) => [s.id, s]))
const repoOf = (id) => cfg.stacks[byId()[id].stack].repo

const summary = { blocked: [], skipped: [], gaps: [], delivered: false }
try {
  // Safety net
  phase('Safety net')
  if (netSkipped(state)) {
    log('every sub-task is done: safety net skipped')
  } else {
    const net = await spawn(
      `Workspace root: ${WS}. Feature ${slug}. Every path below is absolute; use these, resolve none yourself. ` +
      `Follow your Method on ${FEATURE}. Zones come from ${WS}/product/code-map. Write the net under ${WS}/product/tests. ` +
      `Return every zone with mutation_red, and a report under ten lines.`,
      { agentType: 'test-writer', label: 'safety net', schema: NET, ...A('test-writer') })
    if (!net) { await refused('safety net', 'Safety net'); throw new Error('the runtime refused to start the test-writer twice; nothing to build on') }
    const vacuous = vacuousRefusal(net)
    if (vacuous) throw new Error(vacuous)
    await runAll('freeze the net', [
      step('net-freeze', `${T('net')} freeze ${slug}`, 'ok by exit code; output = stdout and stderr'),
      setState('phase', { phase: 'build' }),
    ], 'Safety net')
    log(`safety net: ${net.zones.length} zones pinned, baseline recorded, tests frozen`)
  }

  // Build
  phase('Build')
  // A restart request from a worker or a reviewer (11.1, 19.1): served, respawned, no attempt spent, two per sub-task.
  const serveRestart = async (id, result, count) => {
    const capped = restartCapped(count, MAX_RESTARTS, result.stack)
    if (capped) return { outcome: capped }
    const flags = (result.reseed ? ' --reseed' : '') + ` --subtask ${id}`
    const served = await runAll(`${id} restart ${result.stack}`, [
      step('restart', `${T('restart')} ${slug} ${result.stack}${flags}`, 'ok by exit code; output = the last 20 lines', true),
      brief(id),
    ], 'Build')
    const outcome = restartFailed(served) || briefingFailed(served)
    if (outcome) return { outcome }
    log(`${id} restarted ${result.stack}${result.reseed ? ' with reseed' : ''}, respawning`)
    return { briefing: resultOf(served, 'briefing').output }
  }

  const runSubtask = async (id) => {
    let restarts = 0
    let spent = 0
    let started = 0
    let mission = ''
    let worker = null
    let review = null
    let outcome = { status: 'blocked', reason: 'worker', last_error: '' }
    try {
      while (true) {
        if (!mission) {
          const begun = await runAll(`${id} start`, [
            setState('running', { subtasks: [{ id, status: 'running' }] }),
            brief(id),
          ], 'Build')
          started = Number(resultOf(begun, 'running').output) || started
          const noBrief = briefingFailed(begun)
          if (noBrief) { outcome = noBrief; break }
          mission = resultOf(begun, 'briefing').output
        }
        worker = await spawn(mission, { agentType: 'worker', label: `${id} worker`, phase: 'Build', schema: WORKER, ...A('worker') })
        spent += 1
        if (!worker) { await refused(`${id} worker`, 'Build'); outcome = { status: 'skipped', reason: 'runtime' }; break }
        if (worker.status === 'restart') {
          const served = await serveRestart(id, worker, ++restarts)
          if (served.outcome) { outcome = served.outcome; break }
          mission = served.briefing
          continue
        }
        const stopped = workerOutcome(worker)
        if (stopped) { outcome = stopped; break }
        review = await spawn(
          `${mission}\n\n# Worker report\n${worker.report}\nFiles touched: ${(worker.files || []).join(', ')}`,
          { agentType: 'reviewer', label: `${id} review`, phase: 'Build', schema: REVIEW, ...A('reviewer') })
        if (review && review.status === 'restart') {
          const served = await serveRestart(id, review, ++restarts)
          if (served.outcome) { outcome = served.outcome; break }
          mission = served.briefing
          continue
        }
        if (!review) { await refused(`${id} review`, 'Build'); outcome = { status: 'skipped', reason: 'runtime' }; break }
        const returned = conventionReturn(review)
        if (returned) {
          const capped = returnCapped(spent, returned)
          if (capped) { outcome = capped; break }
          log(`${id} returned for conventions: ${returned}`)
          mission = `${mission}\n\n# Convention return\nThe criteria are green. ${returned}\nChange what that line asks for and nothing else.`
          continue
        }
        outcome = reviewOutcome(review, worker)
        break
      }
    } catch (e) {
      outcome = { status: 'blocked', reason: 'error', last_error: clip(String(e && e.message)) }
    }
    const tag = (lines) => (lines || []).map((l) => (l.startsWith(id) ? l : `${id} · ${l}`))
    const { lines_added, ...rest } = outcome
    const item = { id, ...rest, ...notedOf(worker), attempts: attemptsOf(worker, outcome, byId()[id].attempts, spent) }
    if (outcome.status === 'done') Object.assign(item, { cost: { tokens_in: 0, tokens_out: 0, duration_s: 0, lines_added: outcome.lines_added }, _since: started })
    await runAll(`${id} result`, [setState('result', {
      subtasks: [item],
      decisions: [...tag(worker && worker.decisions), ...tag(review && review.decisions)],
      frictions: [...tag(worker && worker.frictions), ...tag(review && review.frictions), ...(overBudget(review, lines_added, byId()[id].line_budget) ? [`${id} · over line budget · ${review.justification}`] : [])],
    })], 'Build')
    if (outcome.status === 'blocked') summary.blocked.push(`${id}: ${outcome.reason}`)
    if (outcome.status === 'skipped') summary.skipped.push(`${id}: ${outcome.reason}`)
    log(`${id} ${outcome.status}${outcome.commit ? ' ' + outcome.commit.slice(0, 8) : ''}${outcome.reason ? ' (' + outcome.reason + ')' : ''}`)
  }

  const NEXT = { type: 'object', properties: { ready: strings, skipped: strings, pending: { type: 'integer' }, error: { type: 'string' } }, required: ['ready', 'skipped', 'pending'] }
  while (true) {
    const round = await spawn(`${IO}Run \`${T('next')} ${slug}\` and return its JSON verbatim; on a non-zero exit return ready [], skipped [], pending -1 and stderr as error.`,
      { label: 'next round', schema: NEXT, agentType: 'io', ...A('io'), phase: 'Build' })
    const stopped = roundRefusal(round)
    if (stopped) throw new Error(stopped)
    round.skipped.forEach((id) => { summary.skipped.push(id); log(`${id} skipped: a dependency is blocked or skipped`) })
    if (!round.ready.length) break
    await parallel(round.ready.map((id) => () => runSubtask(id)))
  }
  state = stateFrom(await runAll('read the build', [getState('state'), setState('phase', { phase: 'qa' })], 'Build'), 'state')

  if (!landedCount(state)) {
    await runAll('nothing landed', [setState('undelivered', { delivered: false })], 'Build')
    log('nothing landed: QA and delivery skipped')
  } else {
    // QA
    phase('QA')
    const runQA = () => agent(
      `Workspace root: ${WS}. Feature ${slug}. Every path below is absolute; use these, resolve none yourself. ` +
      `Global QA per your Method: the journey ${FEATURE}/journey.md, the safety net under ${WS}/product/tests, every criterion in ${FEATURE}/state.json, ` +
      `the client suite against client_test_baseline in that state, and ` +
      (plan.comparable === false
        ? `no visual diff: the config declares design.comparable false, so capture no screen and report no visual failure.`
        : `the visual diff on the screens in ${FEATURE}/design.`) +
      ` Return the failures.`,
      { agentType: 'qa', label: 'global qa', schema: QA, ...A('qa') })
    let fixes = 0
    let qa = await runQA()
    if (!qa) { await refused('global qa', 'QA'); qa = { failures: [{ kind: 'qa', subtask: 'none', detail: 'global QA did not run: the runtime refused to start it twice' }] }; fixes = cfg.max_fixes }
    while (qa.failures.length && fixes < cfg.max_fixes) {
      for (const f of qa.failures) {
        if (fixes >= cfg.max_fixes) break
        fixes += 1
        const st = byId()[f.subtask]
        if (!st) { log(`fix ${fixes}/${cfg.max_fixes}: ${f.subtask} is not a sub-task, left as a gap`); continue }
        const briefed = await runAll(`${f.subtask} briefing`, [brief(f.subtask)], 'QA')
        const mission = `${resultOf(briefed, 'briefing').output}\n\n# QA failure to fix\nkind: ${f.kind}\nexpected: ${f.expected || ''}\nobserved: ${f.observed || ''}\n${f.detail}\nFix this failure only.`
        const w = await spawn(mission, { agentType: 'worker', label: `fix ${f.subtask}`, schema: WORKER, ...A('worker') })
        let r = null
        if (w && w.status === 'done') {
          r = await spawn(`${mission}\n\n# Worker report\n${w.report}`, { agentType: 'reviewer', label: `fix ${f.subtask} review`, schema: REVIEW, ...A('reviewer') })
        }
        log(`fix ${fixes}/${cfg.max_fixes}: ${f.subtask} ${f.kind} ${r && r.status === 'done' ? 'fixed' : 'not fixed'}`)
      }
      qa = (await runQA()) || { failures: [] }
    }
    summary.gaps = qa.failures.map((f) => `${f.subtask} ${f.kind}: ${f.detail.split('\n')[0]}`)
    if (summary.gaps.length) log(`QA stopped at ${fixes} fixes; ${summary.gaps.length} failures remain as known gaps`)

    // Delivery
    phase('Delivery')
    // bin/deliver refuses a run with nothing landed or an unchanged branch, and records the refusal itself (10), so
    // its exit is read, never thrown on: the batch carries it as the one step allowed to fail.
    const shipped = await runAll('deliver', [
      getState('state'),
      setState('phase', { phase: 'delivery' }),
      step('push', `${T('deliver')} ${slug}`, 'ok by exit code; output = stdout and stderr', true),
    ], 'Delivery')
    state = stateFrom(shipped, 'state')
    summary.delivered = Boolean(resultOf(shipped, 'push').ok)
    if (!summary.delivered) log(`not delivered: ${clip(resultOf(shipped, 'push').error || resultOf(shipped, 'push').output)}`)
  }
} finally {
  // Its own spawn, on purpose: it runs while the run is unwinding, and an environment left up costs more than a spawn.
  await runAll('cleanup', [step('cleanup', `${T('cleanup')} ${slug}`, 'ok by exit code')], 'Delivery')
}

const landed = landedCount(state)
const status = runStatus(landed, state.subtasks.length, summary.delivered, summary.gaps.length)
// bin/cost writes the wall time from the runs' own spans, so the phase write, the cost and the report are one batch.
const closing = await runAll('report', [
  setState('phase', { phase: 'finished' }),
  step('cost', `${T('cost')} ${slug}`, 'ok by exit code; output = stdout'),
  step('report', `${T('report')} ${slug}`, 'ok by exit code; output = its full stdout'),
  step('notify', `${T('notify')} ${slug} run_finished`, 'ok by exit code'),
], 'Delivery')
log(`${slug}: ${status}`)
return { status, report: resultOf(closing, 'report').output, blocked: summary.blocked, skipped: summary.skipped, gaps: summary.gaps }
