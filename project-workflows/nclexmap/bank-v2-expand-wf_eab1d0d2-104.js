export const meta = {
  name: 'bank-v2-expand',
  description: 'Expand NCLEX question-bank nodes from 9 items to 16 at spec 2.0 with citations',
  phases: [{ title: 'Expand', detail: '2 nodes per agent' }]
}

const BRIEF = `You are expanding NCLEX question-bank nodes from 9 items to 16.
Working directory: C:/Users/mark5/Desktop/Nclexmap

STEP 1. Read docs/bank-v2/AUTHORING_BRIEF_V2.md IN FULL. It is your operating procedure.
STEP 2. Read docs/QUESTION_BANK_AUTHORING.md - every v1 rule still applies.
STEP 3. Read questions/MOC/MOC-01.json - a completed spec 2.0 node, your worked example
        for item craft, conversions, and citation format.

STEP 4. For each of your nodes:
  a. npx vite-node scripts/node-facts.ts <NODE>
  b. Read the existing node file; classify all 9 items with metadata.question_kind
  c. Read data/sources/<AREA>.json - your verified fact library
  d. Gap against the quota: act 5, interpret 4, teach 2, evaluate 2, recall 2,
     calculate 1 = 16. Levels L1:2 L2:3 L3:6 L4:3 L5:2.
  e. CONVERT surplus items to interpret by replacing verdict phrases with raw findings.
     Keep the generation_id - this is an edit, not a removal. Update the stem, the
     question_kind, and the fingerprint cue_pattern.
  f. Author the remaining new items.
  g. Set "spec_version": "2.0" at the top of the file.

CRITICAL RULES:
- recall items MUST cite a fact_id from data/sources/<AREA>.json, with publisher,
  title, url, accessed and quote copied EXACTLY from the library entry. Every citation
  is compared field-by-field against the library. NEVER write a citation from memory.
- If the library has no fact for a node, use a substitution (recall or calculate ->
  interpret only) with a reason of 20+ characters. Do not invent a citation.
- If a fact fits your key but is mapped to other nodes, you may still cite it - say so
  in your report so the mapping can be widened.
- Do not delete items to hit a number. Delete only for the causes in the brief, and
  record each in "removed" with a reason.
- 16 genuinely different clinical situations. No two sharing setting + condition +
  cue_pattern.

STEP 5. Verify and fix until clean:
  npx vite-node scripts/bank-verify.ts --area <AREA>
  npx vite-node scripts/source-verify.ts
Read output for YOUR nodes only; other nodes belong to other agents running concurrently.
Write only your own node files.

Return a SHORT report: nodes finished, kind mix, conversions made, substitutions with
reasons, removals, and any node where the fact library left you short.`

const BATCHES = args && args.length ? args : [['BCC-01', 'BCC-02']]

phase('Expand')

const results = await parallel(BATCHES.map((nodes) => () =>
  agent(BRIEF + '\n\nYOUR NODES: ' + nodes.join(', '), { label: 'expand:' + nodes.join('+'), phase: 'Expand' })
))

return { agents: BATCHES.length, done: results.filter(Boolean).length }
