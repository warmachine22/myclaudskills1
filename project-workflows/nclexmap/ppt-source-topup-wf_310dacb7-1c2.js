export const meta = {
  name: 'ppt-source-topup',
  description: 'Top up the PPT fact library with drug-label and calculation facts before PPT nodes are authored',
  phases: [{ title: 'Topup', detail: 'one agent, PPT only' }]
}

phase('Topup')

const result = await agent(`You are TOPPING UP an existing verified fact library.
Working directory: C:/Users/mark5/Desktop/Nclexmap

Read docs/bank-v2/SOURCE_SCOUT_BRIEF.md IN FULL first - it is your operating procedure.

YOUR FILE: data/sources/PPT.json  (Pharmacological and Parenteral Therapies)
It already holds 122 verified facts. ADD to it. Do not remove or rewrite existing
facts. Preserve every existing entry exactly as it is.

WHY: an audit found that 1,136 of our 1,190 facts come from one host
(www.ncbi.nlm.nih.gov) and that DailyMed has contributed ZERO facts. Pharmacology is
16% of the NCLEX blueprint and our bank currently cites no drug label at all. Also,
the calculate quota has thin support - there is no citable dosage formula in the
library yet.

TARGET - roughly 30-40 new facts in two groups:

GROUP A: drug labels from dailymed.nlm.nih.gov
  The actual FDA-approved label, which is what a textbook would itself cite. Pick
  high-yield nursing drugs: insulin, heparin, warfarin, digoxin, furosemide,
  potassium chloride, morphine, naloxone, vancomycin, metformin, levothyroxine,
  phenytoin, lithium. Record monitoring parameters, key adverse effects, boxed
  warnings, administration cautions. Map each to the PPT nodes it serves.

GROUP B: calculation support
  - https://www.ncbi.nlm.nih.gov/books/NBK593207/  Nursing Skills (Open RN) ch.5
    Math Calculations - dimensional analysis, conversions, weight-based dosing,
    IV infusion rates
  - https://www.ncbi.nlm.nih.gov/books/NBK430724/  StatPearls, Dose Calculation
    Dimensional Analysis
  - https://www.ncbi.nlm.nih.gov/books/NBK595000/  Nursing Pharmacology 2e (Open RN)
  Mark these supports_kinds: ["calculate"] where appropriate.

RULES:
- Fetch and READ every page. Copy quotes verbatim. Never record a fact from memory.
- Keep the existing JSON structure and every existing fact untouched.
- New fact ids must not collide with existing ones.
- Spread applies_to_nodes sensibly; PPT-11 already carries 27 facts, so do not add
  more there unless genuinely apt.

VERIFY before finishing:
  npx vite-node scripts/source-verify.ts --area PPT
  npx vite-node scripts/source-verify.ts --area PPT --fetch --sample 20
Fix anything that fails. A FAIL means your quote is not on the page as recorded.

Return a SHORT report: facts added, how many from DailyMed, how many support
calculate, and which PPT nodes gained coverage.`, { label: 'topup:PPT', phase: 'Topup' })

return { result }
