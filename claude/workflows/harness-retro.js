export const meta = {
  name: 'harness-retro',
  description: 'Turn one run\'s frictions into engine edits, then test, tag and push the harness',
  whenToUse: 'Phase 6, after delivery. Args: the feature slug. No human review.',
  phases: [
    { title: 'Retro', detail: 'frictions to edits, tests, tag, push' },
    { title: 'Check', detail: 'independent verification of the pushed tree' },
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
const treeRefusal = (made) => (made && made.ok && made.tree ? null
  : `no engine clone for the retro: ${(made && made.error) || 'the runtime returned nothing'}`)
const checkPassed = (check, unpushed) => Boolean(check && check.clean && check.tests_green && check.report_exists
  && check.harness_at_pin && (check.tag_exists || unpushed))
/* decisions:end */

const slug = slugOf(args)
if (!slug) throw new Error('usage: /harness-retro <slug>')
// The workspace root is passed, never resolved from a working directory (2.2): args.workspace, else HARNESS_WORKSPACE, which
// harness/bin/link writes into .claude/settings.json so every agent inherits it.
const ROOT = { type: 'object', properties: { workspace: { type: 'string' } }, required: ['workspace'] }
const WS = (args && args.workspace) || ((await agent('Run `printf %s "$HARNESS_WORKSPACE"` and return its stdout, exactly, as workspace.', { label: 'workspace root', schema: ROOT, agentType: 'io', effort: 'low' })) || {}).workspace
const rootProblem = workspaceRefusal(WS)
if (rootProblem) throw new Error(rootProblem)
const BIN = `${WS}/harness/bin`
const T = (name) => `${BIN}/${name} --workspace ${WS}`
const FEATURE = `${WS}/product/features/${slug}`
const strings = { type: 'array', items: { type: 'string' } }
const RETRO = {
  type: 'object',
  properties: {
    pushed: { type: 'boolean' }, unpushed: { type: 'boolean' }, tag: { type: 'string' },
    edits: strings, dropped: strings, open_questions: strings, suspected_regression: { type: 'boolean' },
  },
  required: ['pushed', 'unpushed', 'edits', 'dropped', 'open_questions'],
}
const CHECK = {
  type: 'object',
  properties: {
    clean: { type: 'boolean' }, tests_green: { type: 'boolean' }, tag_exists: { type: 'boolean' }, report_exists: { type: 'boolean' },
    harness_at_pin: { type: 'boolean' }, detail: { type: 'string' },
  },
  required: ['clean', 'tests_green', 'tag_exists', 'report_exists', 'harness_at_pin'],
}
const TREE = { type: 'object', properties: { ok: { type: 'boolean' }, tree: { type: 'string' }, error: { type: 'string' }, agents: { type: 'object' } }, required: ['ok'] }

let RUNTIME = ''  // the friction the last refusal produced
const spawn = async (prompt, opts) => {
  const r = await retrying(() => agent(prompt, opts), opts.label, log)
  RUNTIME = r.friction || ''
  return r.result || null
}
phase('Retro')
// The retro edits its own clone of the engine (14.5); the workspace's harness/ stays at the pin.
const made = await spawn(`Run \`${T('retro-tree')} ${slug}\`. Exit 0: ok true, tree = the last line of its stdout. Otherwise ok false, error = stderr verbatim. ` +
  `Then run \`${T('agents')}\` and return its JSON verbatim as agents.`,
  { label: 'engine clone', schema: TREE, agentType: 'io', effort: 'low' })  // before the config is read: the io default, spelled out once
const noTree = treeRefusal(made)
if (noTree) throw new Error(noTree)
const TREE_DIR = made.tree
// Model and effort per role are config, never this script (6.3).
const A = (role) => agentOpts(made.agents, role)
const retro = await spawn(
  `Workspace root: ${WS}. Feature ${slug}. Engine clone: ${TREE_DIR}; every engine edit, test run, commit and push happens there. Never edit, pull or check out ${WS}/harness. ` +
  `Follow the retro skill on ${FEATURE}/state.json. Return pushed, unpushed, the tag, the files edited, the frictions dropped, the open questions added, and whether a suspected regression was written.`,
  { agentType: 'retro', label: 'retro', schema: RETRO, ...A('retro') })
if (!retro) {
  await spawn(`Run:\n${T('state')} update ${slug} - <<'EOF'\n${JSON.stringify({ frictions: [RUNTIME] })}\nEOF`, { label: 'record friction', schema: TREE, agentType: 'io', ...A('io') })
  return { status: 'failed', reason: 'runtime', pushed: false, unpushed: false, edits: [], dropped: [], open_questions: [] }
}
log(`retro: ${retro.edits.length} files edited, ${retro.dropped.length} frictions dropped, ${retro.open_questions.length} open questions${retro.unpushed ? ', UNPUSHED' : ''}`)

phase('Check')
const check = await spawn(
  `Change nothing anywhere. Every command below carries the directory it runs in; run them exactly as written, from wherever you are. ` +
  `tests_green when \`${TREE_DIR}/tests/hygiene.sh --harness ${TREE_DIR} --workspace ${WS}\` and \`npm --prefix ${TREE_DIR} test\` both exit 0. ` +
  `clean = \`git -C ${TREE_DIR} status --porcelain\` prints nothing. tag_exists = \`git -C ${TREE_DIR} tag -l retro/${slug}\` prints the tag. ` +
  `report_exists = \`test -f ${FEATURE}/report.md\` exits 0. ` +
  `harness_at_pin = \`git -C ${WS}/harness rev-parse HEAD\` equals \`cat ${WS}/product/harness.pin\`. detail = the failing lines, ten at most. ` +
  `Last, run \`${T('cost')} ${slug}\`; its exit does not change any field above.`,
  { label: 'verify and cost', schema: CHECK, agentType: 'io', ...A('io') })
const ok = checkPassed(check, retro.unpushed)
if (!ok) log(`retro check failed: ${check ? check.detail : 'no result'}`)
return { status: ok ? 'done' : 'failed', ...retro, check }
