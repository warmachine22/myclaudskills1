export const meta = {
  name: 'bank-v2-batch',
  description: 'PPT source top-up plus four authoring agents expanding eight MOC nodes',
  phases: [{ title: 'Sources', detail: 'PPT drug-label top-up' }, { title: 'Expand', detail: '4 agents, 2 nodes each' }]
}

const AUTHOR = `You are expanding NCLEX question-bank nodes from 9 items to 16.
Working directory: C:/Users/mark5/Desktop/Nclexmap

STEP 1. Read docs/bank-v2/AUTHORING_BRIEF_V2.md IN FULL - your operating procedure.
STEP 2. Read docs/QUESTION_BANK_AUTHORING.md - every v1 rule still applies.
STEP 3. Read questions/MOC/MOC-01.json - a completed spec 2.0 node, your worked example.

STEP 4. For each node: read it, classify all 9 items with metadata.question_kind, read
data/sources/<AREA>.json, then close the gap to the quota: act 5, interpret 4, teach 2,
evaluate 2, recall 2, calculate 1 = 16. Levels L1:2 L2:3 L3:6 L4:3 L5:2.
CONVERT surplus act items to interpret by replacing verdict phrases with raw findings -
keep the generation_id, this is an edit not a removal. Then author the rest.
Set "spec_version": "2.0" at the top of the file.

CRITICAL:
- recall items MUST cite a fact_id from data/sources/<AREA>.json with publisher, title,
  url, accessed and quote copied EXACTLY. Every citation is compared field-by-field
  against the library. NEVER write a citation from memory.
- No fact for a node? Use a substitution (recall or calculate -> interpret only) with a
  reason of 20+ characters. Do not invent a citation.
- Do not delete to hit a number. Removals need a cause from the brief, recorded in
  "removed" with a reason.
- 16 genuinely different clinical situations.

STEP 5. Verify and fix until clean:
  npx vite-node scripts/bank-verify.ts --area <AREA>
  npx vite-node scripts/source-verify.ts
Read output for YOUR nodes only. Write only your own node files.

Return a SHORT report: nodes finished, kind mix, conversions, substitutions with
reasons, removals, and any node where the fact library left you short.`

const TOPUP = `You are TOPPING UP an existing verified fact library.
Working directory: C:/Users/mark5/Desktop/Nclexmap

Read docs/bank-v2/SOURCE_SCOUT_BRIEF.md IN FULL first.

YOUR FILE: data/sources/PPT.json - 122 verified facts already. ADD to it. Preserve
every existing fact byte-for-byte. Do not remove or rewrite any.

WHY: an audit found 1,136 of our 1,190 facts come from one host, and DailyMed has
contributed ZERO. Pharmacology is 16% of the blueprint and cites no drug label at all.

PRIORITY ORDER - do group A first and write the file even if you run short on time:

GROUP A: dailymed.nlm.nih.gov drug labels. The actual FDA-approved label. High-yield
nursing drugs: insulin, heparin, warfarin, digoxin, furosemide, potassium chloride,
morphine, naloxone, vancomycin, metformin, levothyroxine, phenytoin, lithium. Record
monitoring parameters, adverse effects, boxed warnings, administration cautions.
Aim for ~20 facts here.

GROUP B, if time allows: calculation support from
  https://www.ncbi.nlm.nih.gov/books/NBK593207/ (Nursing Skills ch.5 Math Calculations)
  https://www.ncbi.nlm.nih.gov/books/NBK430724/ (StatPearls Dose Calculation)
Mark supports_kinds: ["calculate"].

RULES: fetch and READ every page, quotes verbatim, never from memory. New ids must not
collide. PPT-11 already has 27 facts - do not add more there unless genuinely apt.

VERIFY: npx vite-node scripts/source-verify.ts --area PPT --fetch --sample 20

Return: facts added, how many from DailyMed, which nodes gained coverage.`

const NODES = [['MOC-07', 'MOC-08'], ['MOC-09', 'MOC-10'], ['MOC-11', 'MOC-12'], ['MOC-13', 'MOC-14']]

phase('Sources')
const topup = agent(TOPUP, { label: 'topup:PPT', phase: 'Sources' })

phase('Expand')
const authored = await parallel([
  () => topup,
  ...NODES.map((nodes) => () =>
    agent(AUTHOR + '\n\nYOUR NODES: ' + nodes.join(', '), { label: 'expand:' + nodes.join('+'), phase: 'Expand' }))
])

return { done: authored.filter(Boolean).length, of: NODES.length + 1 }
