export const meta = {
  name: 'bank-v2-authoring-pilot',
  description: 'Pilot: expand four nodes from 9 items to 16 at spec 2.0 with citations',
  phases: [{ title: 'Expand', detail: '2 agents, 2 nodes each' }]
}

const BRIEF = `You are expanding NCLEX question-bank nodes from 9 items to 16.
Working directory: C:/Users/mark5/Desktop/Nclexmap

STEP 1. Read docs/bank-v2/AUTHORING_BRIEF_V2.md IN FULL. It is your operating procedure.
STEP 2. Read docs/QUESTION_BANK_AUTHORING.md - every v1 rule still applies.
STEP 3. Read questions/MOC/MOC-01.json as the quality exemplar for item craft.

STEP 4. For each of your nodes:
  a. npx vite-node scripts/node-facts.ts <NODE> - what the node covers
  b. Read the existing node file and classify all 9 items with metadata.question_kind
  c. Read data/sources/<AREA>.json - your verified fact library
  d. Work out the gap against the quota: act 5, interpret 4, teach 2, evaluate 2,
     recall 2, calculate 1 = 16. Levels L1:2 L2:3 L3:6 L4:3 L5:2.
  e. CONVERT surplus act items to interpret by replacing verdict phrases with raw
     findings. This is an edit, keeping the generation_id - not a removal.
  f. Author the remaining new items.
  g. Set "spec_version": "2.0" at the top of the file.

CRITICAL RULES:
- recall items MUST cite a fact_id that exists in data/sources/<AREA>.json. Copy the
  publisher, title, url, accessed and quote fields exactly from the library entry.
  NEVER invent a citation or write one from memory. If the library has nothing for
  this node, use a substitution and record the reason.
- Substitutions are only allowed from recall or calculate, only to interpret, and need
  a reason of 20+ characters.
- Do not delete items to hit a number. Delete only for the causes in the brief, and
  record each one in the "removed" array with a reason.
- 16 genuinely different clinical situations. No two items sharing setting + condition
  + cue_pattern.

STEP 5. Verify and fix until clean:
  npx vite-node scripts/bank-verify.ts --area <AREA>
  npx vite-node scripts/source-verify.ts
Read the output for YOUR nodes only. Other nodes belong to other agents.

Return a SHORT report: nodes finished, final kind mix per node, any conversions you
made, any substitutions with reasons, anything removed, and any node where the fact
library left you short.`

const BATCHES = [['MOC-01', 'MOC-02'], ['PPT-11', 'SIPC-04']]

phase('Expand')

const results = await parallel(BATCHES.map((nodes) => () =>
  agent(BRIEF + '\n\nYOUR NODES: ' + nodes.join(', '), { label: 'expand:' + nodes.join('+'), phase: 'Expand' })
))

return { batches: BATCHES.length, results: results.filter(Boolean) }
