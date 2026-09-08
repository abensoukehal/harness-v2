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
  properties: { clean: { type: 'boolean' }, tests_green: { type: 'boolean' }, tag_exists: { type: 'boolean' }, report_exists: { type: 'boolean' }, detail: { type: 'string' } },
  required: ['clean', 'tests_green', 'tag_exists', 'report_exists'],
}

phase('Retro')
const retro = await agent(
  `Workspace root: ${WS}. Feature ${slug}. Follow the retro skill on ${FEATURE}/state.json. Return pushed, unpushed, the tag, the files edited, the frictions dropped, the open questions added, and whether a suspected regression was written.`,
  { agentType: 'retro', label: 'retro', schema: RETRO })
if (!retro) throw new Error('retro returned nothing')
log(`retro: ${retro.edits.length} files edited, ${retro.dropped.length} frictions dropped, ${retro.open_questions.length} open questions${retro.unpushed ? ', UNPUSHED' : ''}`)

phase('Check')
const check = await agent(
  `In ${WS}/harness, change nothing. Run \`npm ci --no-fund --no-audit\` when node_modules is missing, then \`tests/hygiene.sh\` and \`npm test\`: tests_green when both exit 0. ` +
  `clean = \`git status --porcelain\` prints nothing. tag_exists = \`git tag -l retro/${slug}\` prints the tag. report_exists = ${FEATURE}/report.md exists. detail = the failing lines, ten at most.`,
  { label: 'verify', schema: CHECK, effort: 'low' })
const ok = Boolean(check && check.clean && check.tests_green && check.report_exists && (check.tag_exists || retro.unpushed))
if (!ok) log(`retro check failed: ${check ? check.detail : 'no result'}`)
return { status: ok ? 'done' : 'failed', ...retro, check }
