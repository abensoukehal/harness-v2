export const meta = {
  name: 'harness-retro',
  description: 'Turn one run\'s frictions into engine edits, then test, tag and push the harness',
  whenToUse: 'Phase 6, after delivery. Args: the feature slug. No human review.',
  phases: [
    { title: 'Retro', detail: 'frictions to edits, tests, tag, push' },
    { title: 'Check', detail: 'independent verification of the pushed tree' },
  ],
}

const slug = typeof args === 'string' ? args.trim().split(/\s+/)[0] : args && args.slug
if (!slug) throw new Error('usage: /harness-retro <slug>')
// The workspace root is passed, never resolved from a working directory (2.2): args.workspace, else HARNESS_WORKSPACE, which
// harness/bin/link writes into .claude/settings.json so every agent inherits it.
const ROOT = { type: 'object', properties: { workspace: { type: 'string' } }, required: ['workspace'] }
const WS = (args && args.workspace) || ((await agent('Run `printf %s "$HARNESS_WORKSPACE"` and return its stdout, exactly, as workspace.', { label: 'workspace root', schema: ROOT, effort: 'low' })) || {}).workspace
if (!WS || !WS.startsWith('/')) throw new Error('workspace root unknown: HARNESS_WORKSPACE is not set; run harness/bin/link in the workspace and start the session there')
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
const TREE = { type: 'object', properties: { ok: { type: 'boolean' }, tree: { type: 'string' }, error: { type: 'string' } }, required: ['ok'] }

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
phase('Retro')
// The retro edits its own clone of the engine (14.5); the workspace's harness/ stays at the pin.
const made = await spawn(`Run \`${T('retro-tree')} ${slug}\`. Exit 0: ok true, tree = the last line of its stdout. Otherwise ok false, error = stderr verbatim.`,
  { label: 'engine clone', schema: TREE, effort: 'low' })
if (!made || !made.ok || !made.tree) throw new Error(`no engine clone for the retro: ${made && made.error}`)
const TREE_DIR = made.tree
const retro = await spawn(
  `Workspace root: ${WS}. Feature ${slug}. Engine clone: ${TREE_DIR}; every engine edit, test run, commit and push happens there. Never edit, pull or check out ${WS}/harness. ` +
  `Follow the retro skill on ${FEATURE}/state.json. Return pushed, unpushed, the tag, the files edited, the frictions dropped, the open questions added, and whether a suspected regression was written.`,
  { agentType: 'retro', label: 'retro', schema: RETRO })
if (!retro) {
  await spawn(`Run:\n${T('state')} update ${slug} - <<'EOF'\n${JSON.stringify({ frictions: [RUNTIME('retro')] })}\nEOF`, { label: 'record friction', schema: TREE, effort: 'low' })
  return { status: 'failed', reason: 'runtime', pushed: false, unpushed: false, edits: [], dropped: [], open_questions: [] }
}
log(`retro: ${retro.edits.length} files edited, ${retro.dropped.length} frictions dropped, ${retro.open_questions.length} open questions${retro.unpushed ? ', UNPUSHED' : ''}`)

phase('Check')
const check = await spawn(
  `In ${TREE_DIR}, change nothing. Run \`tests/hygiene.sh --workspace ${WS}\` and \`npm test\`: tests_green when both exit 0. ` +
  `clean = \`git status --porcelain\` prints nothing. tag_exists = \`git tag -l retro/${slug}\` prints the tag. report_exists = ${FEATURE}/report.md exists. ` +
  `harness_at_pin = \`git -C ${WS}/harness rev-parse HEAD\` equals the content of ${WS}/product/harness.pin. detail = the failing lines, ten at most.`,
  { label: 'verify', schema: CHECK, effort: 'low' })
const ok = Boolean(check && check.clean && check.tests_green && check.report_exists && check.harness_at_pin && (check.tag_exists || retro.unpushed))
if (!ok) log(`retro check failed: ${check ? check.detail : 'no result'}`)
return { status: ok ? 'done' : 'failed', ...retro, check }
