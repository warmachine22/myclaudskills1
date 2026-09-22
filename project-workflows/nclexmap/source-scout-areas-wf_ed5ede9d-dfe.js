export const meta = {
  name: 'source-scout-areas',
  description: 'Build verified fact libraries for the six remaining NCLEX content areas',
  phases: [{ title: 'Scout', detail: 'one agent per area' }]
}

const BRIEF = `You are building a VERIFIED FACT LIBRARY for one NCLEX content area.
Working directory: C:/Users/mark5/Desktop/Nclexmap

STEP 1. Read docs/bank-v2/SOURCE_SCOUT_BRIEF.md IN FULL. It is your operating procedure:
file format, allowed domains, what makes a good fact, what to avoid.

STEP 2. Read docs/bank-v2/PLAN.md for why this exists.

STEP 3. See your area's nodes. Get the node list with: ls questions/<AREA>/
Then: npx vite-node scripts/node-facts.ts <your node ids>

STEP 4. Search and FETCH. The single rule that matters:
  ** Open the page and read it. Never record a fact from memory. **
Use WebSearch to find pages, then WebFetch to actually read them. Copy quotes verbatim.

Do NOT waste attempts on cdc.gov, stacks.cdc.gov, jointcommission.org or ahrq.gov --
all four return 403 to automated requests. Tested. Use StatPearls (ncbi.nlm.nih.gov) as
your workhorse, plus medlineplus.gov, dailymed.nlm.nih.gov, ismp.org, who.int,
psnet.ahrq.gov, uspreventiveservicestaskforce.org, ncsbn.org, fda.gov. ismp.org DOES
work -- if one URL returns nothing, try another on that domain before writing it off.
You may name CDC in your claim prose as the upstream authority; the url must be
something we can fetch.

STEP 5. Write data/sources/<AREA>.json. Target: at least two facts applicable to every
node in your area, and spread them -- do not let one node hoard facts while neighbours
get two. One fact may legitimately serve several nodes.

STEP 6. Verify:
  npx vite-node scripts/source-verify.ts --area <AREA>
  npx vite-node scripts/source-verify.ts --area <AREA> --fetch --sample 20
Fix everything reported. A FAIL means your quote is not on the page as recorded -- fix
the quote or drop the fact. Never leave a failing quote in the file.

Note: the verifier now decodes HTML entities, so a verbatim quote spanning an embedded
&#x000a0; will match correctly. You do not need to avoid those spans.

Write ONLY your own area's file. Other agents are writing theirs concurrently.

Return a SHORT report: fact count, publishers, how many nodes have 2+ facts, and
honestly name any node you could not cover well.`

const AREAS = ['MOC', 'HPM', 'PSY', 'BCC', 'RRP', 'PA']

phase('Scout')

const results = await parallel(AREAS.map((area) => () =>
  agent(BRIEF + '\n\nYOUR AREA: ' + area, { label: 'scout:' + area, phase: 'Scout' })
))

return { areas: AREAS, done: results.filter(Boolean).length }
