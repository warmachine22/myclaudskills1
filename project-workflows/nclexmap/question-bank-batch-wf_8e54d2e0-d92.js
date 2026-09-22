export const meta = {
  name: 'question-bank-batch',
  description: 'Author a batch of NCLEX question-bank nodes, 2 nodes per agent',
  phases: [{ title: 'Author', detail: 'one agent per node pair' }]
}

const BRIEF = `You are authoring items for the NCLEX Map pre-generated question bank.
Repo root: C:/Users/mark5/Desktop/Nclexmap

DO NOT read application source code. Everything you need is in the two files named
below. Reading lib/*.ts wastes your budget and teaches you nothing you need.

STEP 1. Read docs/QUESTION_BANK_AUTHORING.md IN FULL. It is your operating procedure:
file format, hard requirements, diversity rules, and the quality bar.

STEP 2. Read questions/MOC/MOC-01.json. That is the quality exemplar — match it.
Note especially: nine genuinely different clinical situations across different
settings, concrete findings the learner must interpret rather than summary phrases,
every option explained in its own terms, comparable option lengths, and keys spread
across option positions rather than clustered on A.

STEP 3. Get your nodes' authoring facts:
  npx vite-node scripts/node-facts.ts <YOUR NODE IDS>

STEP 4. For EACH node, author exactly 9 items at levels 1,2,2,3,3,3,4,4,5 and write
questions/<AREA>/<NODE_ID>.json. Write each file once, complete, valid JSON.
Do not touch any node that is not yours. Do not modify any other file in the repo.

STEP 5. Verify:
  npx vite-node scripts/bank-verify.ts --area <AREA>
Look only at lines for YOUR node IDs — other agents are writing other nodes
concurrently and their status is not yours to fix. Repair every failure reported
against your nodes and re-run until your nodes show no failures.

THE FAILURES THAT ACTUALLY HAPPEN, IN ORDER OF FREQUENCY:
1. difficulty_profile average outside its band. Compute the mean of the seven axes:
   L1 1.0-2.0, L2 1.5-2.7, L3 2.3-3.6, L4 3.3-4.4, L5 4.0-5.0.
   Safe defaults: L1 all 1s with distractor_plausibility 2 (1.14). L2 all 2s with
   competing_priorities and temporal_complexity 1 (1.71). L3 all 3s with those two at
   2 (2.71). L4 all 4s with competing_priorities 3 and temporal_complexity 3 (3.71).
   L5 all 5s with integration and temporal_complexity 4 (4.57).
2. The review block must repeat the same profile you authored (or within 0.8 of its
   mean) and estimated_level must equal the item's difficulty. It is a genuine
   re-score: if re-reading the item gives a different answer, fix the ITEM.
3. Out-of-vocabulary fingerprint values. setting, care_stage, clinical_judgment_step,
   reasoning_pathway and temporal_pattern accept ONLY the listed values.
4. Two items in a node sharing setting + condition + cue_pattern. Nine different
   clinical situations, not one situation at nine difficulties.
5. A key noticeably longer than its distractors.

Return ONLY: the node files you wrote and the verifier's verdict for each.`

const batches = args

phase('Author')

const results = await parallel(batches.map((nodes) => () =>
  agent(`${BRIEF}\n\nYOUR NODES: ${nodes.join(', ')}`, {
    label: `author:${nodes.join('+')}`,
    phase: 'Author'
  })
))

return { agents: batches.length, done: results.filter(Boolean).length }
