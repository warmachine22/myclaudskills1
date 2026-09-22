export const meta = {
  name: 'source-scout-pilot',
  description: 'Pilot: build the verified fact library for two areas to test the source-first method',
  phases: [{ title: 'Scout', detail: '2 agents, one area each' }]
}

const BRIEF = `You are building a VERIFIED FACT LIBRARY for one NCLEX content area.
Working directory: C:/Users/mark5/Desktop/Nclexmap

STEP 1. Read docs/bank-v2/SOURCE_SCOUT_BRIEF.md IN FULL. It is your operating procedure:
the file format, the allowed domains, what makes a good fact, and what to avoid.

STEP 2. Read docs/bank-v2/PLAN.md for why this exists.

STEP 3. See your area's nodes:
  npx vite-node scripts/node-facts.ts <your node ids>
(Get the list with: ls questions/<AREA>/)

STEP 4. Search and FETCH. The single rule that matters:
  ** Open the page and read it. Never record a fact from memory. **
Use WebSearch to find pages, then WebFetch to actually read them. Copy quotes verbatim.

CRITICAL - do NOT waste attempts on cdc.gov, stacks.cdc.gov, jointcommission.org or
ahrq.gov. All four return 403 to automated requests. This was tested. Use StatPearls
(ncbi.nlm.nih.gov) as your workhorse, plus medlineplus.gov, dailymed.nlm.nih.gov,
ismp.org, who.int, psnet.ahrq.gov, uspreventiveservicestaskforce.org, ncsbn.org.
You may name CDC in your claim prose as the upstream authority, but the url must be
one we can fetch.

STEP 5. Write data/sources/<AREA>.json. Target: at least two facts applicable to every
node in your area. One fact may serve several nodes.

STEP 6. Verify:
  npx vite-node scripts/source-verify.ts --area <AREA>
  npx vite-node scripts/source-verify.ts --area <AREA> --fetch --sample 15
Fix everything it reports. A FAIL on the fetch check means your quote is not on the page
as recorded - fix the quote or drop the fact. Never leave a failing quote in the file.

Return a SHORT report: fact count, publishers used, how many of your nodes have 2+ facts,
and honestly name any node you could not cover well.`

// Areas come from the invocation. This was hardcoded, so passing args silently ran the
// pilot areas again instead of the six that were actually outstanding.
const AREAS = Array.isArray(args) && args.length ? args : ['SIPC', 'PPT']

phase('Scout')

const results = await parallel(AREAS.map((area) => () =>
  agent(`${BRIEF}\n\nYOUR AREA: ${area}`, { label: `scout:${area}`, phase: 'Scout' })
))

return { areas: AREAS, results: results.filter(Boolean) }
