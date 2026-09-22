export const meta = {
  name: 'momentum-tax-alpha',
  description: 'Invent and test cross-sectional momentum variants that survive taxes and trading costs',
  phases: [
    { title: 'Explore', detail: 'six independent strategy families tested against the shared panel' },
    { title: 'Verify', detail: 'adversarial replication of each surviving claim' },
  ],
}

const DIR = 'C:\\Users\\mark5\\Desktop\\claudcodechat\\tqqq-study'

const COMMON = `
You are doing quantitative research in ${DIR}. READ ${DIR}\\KIT.md FIRST - it documents the
data panel, the shared engine API, the validated baseline, and the exact reporting rules.

Work by writing Python scripts into ${DIR} and RUNNING them with the Bash tool. Actually execute
code and report real measured numbers. Never report a number you did not compute.

Name every file you create with your assigned PREFIX so you do not collide with other agents.

Hard rules:
- No look-ahead. Signal at month t uses data through t only; you earn month t+1 returns.
- Report gross AND after-cost-after-tax (0.15% of traded value; 35% short-term, 18% long-term).
- Report turnover/yr, CAGR, Sharpe, maxDD for every variant.
- The bar: beat equal-weight AFTER TAX. EW net is 10.83%/yr. The current best momentum
  variant nets 11.59%, i.e. only +0.75%/yr. Beat that.
- Do not overfit. If you grid-search, report how many variants you tried and show the whole
  surface, not just the winner. A broad elevated surface is evidence; one lucky cell is not.
- Validate any winner with a random-portfolio null and a 1987-2006 / 2007-2026 split.
- Reporting a clean negative result is success. Do not manufacture an edge.

Return STRICT JSON only (no prose, no markdown fence) with this shape:
{"family":"...","variants_tried":N,"best":{"desc":"...","gross_cagr":x,"net_cagr":x,
"turnover":x,"sharpe":x,"maxdd":x,"vs_ew_net":x,"oos_net":x,"null_p":x},
"surface_summary":"...","verdict":"WIN|MARGINAL|FAIL","honest_caveats":"...","files":["..."]}
`

const FAMILIES = [
  { key: 'buffer', prefix: 'a1_', title: 'Hysteresis buffering to cut turnover',
    brief: `Cut turnover without losing signal. The baseline sells a fund the moment it drops out of
    the top N, which churns. Test BUFFER/HYSTERESIS rules: hold a position until it falls out of the
    top N*k (k = 1.5, 2, 2.5, 3) or out of the top X percentile; only then replace it with the best
    non-held candidate. Also test a minimum-holding-period rule (do not sell before month 13 unless
    the rank collapses badly) which converts short-term gains into long-term gains. Grid over
    L, N, H and buffer width. Turnover reduction is the whole point - show the turnover/net-CAGR
    frontier.` },
  { key: 'taxexec', prefix: 'a2_', title: 'Tax-aware execution',
    brief: `Keep the baseline signal EXACTLY as is (L=9,N=8,H=3 and a couple of neighbours) and
    attack only the tax bill through execution. Implement and test: (1) HIFO/specific-lot selection
    instead of the current pro-rata basis; (2) deliberate deferral - if a position is within 45 days
    of the 12-month mark and would be sold at a gain, hold it until it qualifies as long-term;
    (3) tax-loss harvesting - preferentially sell losing lots and bank losses against realized gains,
    respecting a 30-day wash-sale rule; (4) carrying forward capital losses across years. Report how
    much each mechanism is worth in basis points per year, separately and combined.` },
  { key: 'signal', prefix: 'a3_', title: 'Better momentum signal',
    brief: `Raise the GROSS edge so more survives tax. Test alternative ranking signals against the
    same selection machinery: (1) blended multi-horizon momentum (average of 3/6/9/12-month ranks);
    (2) risk-adjusted momentum (trailing return divided by trailing volatility); (3) momentum measured
    relative to the cross-sectional mean, z-scored; (4) rank-based rather than return-based scoring;
    (5) "smooth" momentum / frog-in-the-pan (path consistency: fraction of positive months over the
    lookback) used as a tiebreaker or filter; (6) momentum with the most recent month skipped to dodge
    short-term reversal. Report the full comparison table, not just the best.` },
  { key: 'dual', prefix: 'a4_', title: 'Dual momentum and trend overlay',
    brief: `Test absolute/trend overlays on top of relative strength. (1) Dual momentum: hold the top N
    only if their trailing return also beats T-bills, else hold bonds/cash. (2) Individual trend filter:
    only hold a selected fund if it is above its own 10-month moving average, else that slot goes to
    cash or the bond sleeve. (3) Market-regime filter: scale exposure by whether the equal-weight
    universe is above its own 10-month MA. These historically cut drawdowns hard - test whether they
    also help AFTER TAX, noting that moving to cash realises gains. Report the drawdown/return/tax
    three-way tradeoff carefully.` },
  { key: 'weight', prefix: 'a5_', title: 'Position weighting and risk targeting',
    brief: `Keep equal-weight selection as the control and test smarter weighting of the chosen N:
    (1) inverse-volatility weighting; (2) score-proportional weighting (stronger momentum, bigger
    position); (3) volatility targeting at the portfolio level (scale gross exposure to hit a constant
    target vol using cash, no leverage above 1.0 first, then test up to 1.3); (4) risk-parity across
    the sleeve labels in data/groups.json so the portfolio cannot become 8 flavours of the same
    tech bet. Concentration is a real risk in this universe - quantify how correlated the selected
    N typically are, and whether de-correlating helps after tax.` },
  { key: 'timing', prefix: 'a6_', title: 'Rebalance timing, universe and robustness',
    brief: `Attack the plumbing rather than the signal. (1) Does the rebalance calendar month matter -
    test all 12 possible quarterly/annual rebalance offsets and report the spread, which is a direct
    measure of how much luck is in any single calendar choice. (2) Test excluding the bond and
    commodity sleeves so the benchmark confound disappears - is there still an edge among equity
    sectors alone, versus an equity-only equal-weight benchmark? This is the cleanest test that the
    edge is real security selection and not an asset-class tilt. (3) Test sensitivity to universe
    size by randomly dropping 25% of funds many times. (4) Test whether the edge concentrates in a
    few funds or a few years - report the distribution of contribution.` },
]

phase('Explore')
const found = await pipeline(
  FAMILIES,
  f => agent(`${COMMON}\n\nYOUR PREFIX: ${f.prefix}\nYOUR FAMILY: ${f.title}\n\n${f.brief}`,
    { label: `explore:${f.key}`, phase: 'Explore' }),
  (raw, f) => {
    let parsed = null
    try { parsed = JSON.parse(String(raw).replace(/^```(json)?/i, '').replace(/```$/, '').trim()) }
    catch (e) { parsed = { family: f.title, verdict: 'UNPARSED', raw: String(raw).slice(0, 2500) } }
    return { family: f, result: parsed }
  }
)

log(`explore phase done: ${found.filter(Boolean).length} families reported`)

const claims = found.filter(Boolean).filter(x =>
  x.result && (x.result.verdict === 'WIN' || x.result.verdict === 'MARGINAL'))

log(`${claims.length} families claim a positive result - sending each to an adversarial verifier`)

phase('Verify')
const verdicts = await parallel(claims.map(c => () => agent(
  `You are an adversarial replicator in ${DIR}. Read ${DIR}\\KIT.md.

An agent claims the following result for the family "${c.family.title}" (files prefixed
${c.family.prefix}):

${JSON.stringify(c.result, null, 1)}

Your job is to REFUTE it. Read their code. Re-implement the core claim INDEPENDENTLY in your own
script named ${c.family.prefix}verify.py - do not import or copy their logic. Then check:
1. Look-ahead bias: does any signal at month t use information from t or later to earn return at t?
   Check index alignment obsessively. This is the most common way results like this are wrong.
2. Is the after-tax number computed correctly, and is the comparison against EW NET (10.83%) and
   not against EW gross?
3. Overfitting: how many variants were tried? Does the result survive on 1987-2006 and 2007-2026
   separately? Is the parameter surface broad or is the winner an isolated cell?
4. Does the claimed edge survive a random-portfolio null with matched N and H?
5. Survivorship or universe artefacts.

Default to refuted when uncertain. Return STRICT JSON only:
{"family":"...","replicated":true|false,"my_net_cagr":x,"their_net_cagr":x,
"lookahead_found":true|false,"verdict":"CONFIRMED|WEAKER|REFUTED","reason":"...","detail":"..."}`,
  { label: `verify:${c.family.key}`, phase: 'Verify' }
)))

return {
  explored: found.filter(Boolean).map(x => ({ family: x.family.title, result: x.result })),
  verified: verdicts.filter(Boolean),
}
