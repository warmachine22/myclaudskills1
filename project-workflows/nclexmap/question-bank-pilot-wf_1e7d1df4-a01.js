export const meta = {
  name: 'question-bank-pilot',
  description: 'Pilot: author 6 nodes of the NCLEX question bank to check agent output quality',
  phases: [{ title: 'Author', detail: '3 agents, 2 nodes each' }]
}

const BRIEF = `You are authoring items for the NCLEX Map pre-generated question bank.
Working directory is the repo root: C:/Users/mark5/Desktop/Nclexmap

STEP 1. Read docs/QUESTION_BANK_AUTHORING.md IN FULL. It is your operating procedure
and it contains the file format, the hard requirements, and the quality bar. Follow it
exactly.

STEP 2. Read questions/MOC/MOC-01.json. That is the quality exemplar. Match that
standard: nine genuinely different clinical situations, specific concrete findings,
every option explained in its own terms, comparable option lengths, keys spread across
option positions.

STEP 3. Run this to get your nodes' authoring facts:
  npx vite-node scripts/node-facts.ts <YOUR NODE IDS>

STEP 4. For EACH of your nodes, author exactly 9 items (levels 1,2,2,3,3,3,4,4,5) and
write questions/<AREA>/<NODE_ID>.json. Write each file once, complete. Do not touch any
node that is not yours.

STEP 5. Verify your work:
  npx vite-node scripts/bank-verify.ts --area <AREA>
Read the output for YOUR node IDs only; other nodes are being written by other agents
and their status is not your concern. Fix every failure reported against your nodes and
re-run until your nodes report no failures. Warnings are worth fixing but not blocking.

CRITICAL POINTS THAT CAUSE FAILURES:
- The difficulty_profile average must fall in the band: L1 1.0-2.0, L2 1.5-2.7,
  L3 2.3-3.6, L4 3.3-4.4, L5 4.0-5.0. Compute the mean of the seven axes and check.
- Your "review" block must be a genuine re-score and must agree with the authored
  profile within 0.8 on the mean, with estimated_level equal to the item's level.
- Fingerprint axes setting / care_stage / clinical_judgment_step / reasoning_pathway /
  temporal_pattern accept ONLY the listed vocabulary values. Anything else is rejected.
- Within a node, no two items may share the same setting + condition + cue_pattern.
  Nine different clinical situations, not one situation nine ways.
- The key must never depend on a fact not stated in the stem.
- Option lengths must be comparable; a long key is a giveaway.

Return ONLY a short report: which node files you wrote, and the verifier's verdict for
each of your nodes.`

const BATCHES = [
  ['MOC-02', 'MOC-03'],
  ['MOC-04', 'MOC-05'],
  ['MOC-06', 'MOC-07']
]

phase('Author')

const results = await parallel(BATCHES.map((nodes) => () =>
  agent(`${BRIEF}\n\nYOUR NODES: ${nodes.join(', ')}`, {
    label: `author:${nodes.join('+')}`,
    phase: 'Author'
  })
))

return { batches: BATCHES.length, results: results.filter(Boolean) }
