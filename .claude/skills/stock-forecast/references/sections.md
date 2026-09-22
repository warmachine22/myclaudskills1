# What each section must contain

The renderer builds structure; you supply judgment. A section whose commentary is
empty renders without it — which looks like a page that had nothing to say. Fill
every one.

## 1. The call
`thesis` — 2–4 sentences. The rating, the single strongest reason for it, and the
strongest argument against it. If you cannot state the bear case in your own
thesis, you have not done the work.

## 2. What this company does
`company_explainer` — plain language, no jargon, from the profile and segments.
A reader who has never heard of the company should finish knowing how it makes
money and which segment matters. Quote the company's own framing where it is
revealing (an investor deck's chosen headline tells you what management wants
tracked).

## 3. Price and technical setup
`section_commentary.technicals` — what the setup means, not a restatement of the
numbers beside it. Volatility context matters: "5% below the high" means
something different at 15% annualised vol than at 45%.

## 4. Financial history and projections
`section_commentary.financials` — the trajectory, whether margins held while
revenue grew, and how well-supported the forward estimates are. **Always flag a
fiscal year resting on fewer than 5 analysts** — it is a placeholder, not a
forecast.

## 5. Fair value
`section_commentary.fair_value` — the fair-value engine's guardrails are
reproduced verbatim by the renderer; your job is to say what the number means and
what it does not. "36% below its own historical multiple" is not "cheap in
absolute terms," and the difference must be explicit. If the back-test is
non-monotonic, say so here — it is the strongest evidence against the valuation
dimension carrying its weight.

If the engine **refused**, the section says so, the dimension is marked
unavailable, and no fair value is invented.

## 6. The earnings call
- `said_vs_delivered[]` — one row per quarter: `{quarter, guided, delivered, verdict, quote}`. Build it by comparing quarter N−1's *Outlook and guidance* against quarter N's *Financial highlights*. Verdicts: beat / met / missed / mixed / dropped / pending. Include the guidance quote where it is specific.
- `qa_read` — who asked, who got a straight answer, what was deflected, and what the questions clustered on. A cluster is a signal: analysts converging on one topic means the market has an unresolved question. Note what was *not* asked too.
- `deck_findings[]` — `{finding, page}`. See the warning below.
- `section_commentary.earnings_call` — what the call and deck together say about management's framing.

## 7. Estimates and the street
`section_commentary.revisions` and `.reactions`. The revision trend is usually the
cleanest signal on the page. The reaction table often contradicts it — many
companies beat every quarter and still fall on the day — and that contradiction is
worth stating plainly rather than smoothing.

## 8. Our forecast
`target_price` — see `scorecard.md`. Show the arithmetic.

## 9. What would change our mind
`falsifiers[]` — specific, observable, and dated where possible. "Competition
increases" is not a falsifier. "Two or more large cloud providers guide capex
down" is. Each one should be checkable from a future run of this same skill.

## 10. Sources
Built automatically from `bundle.provenance`, the cross-checks and any collection
errors. Nothing to write.

---

## The deck warning

`decks.py audit` reports how many pages have **no extractable text**. It does not
report whether the *data* is extractable, and those are different questions.

Verified on NVDA's July 2026 roadshow deck: the audit said "all decks scrape
cleanly, text extraction is sufficient" — 2 of 25 pages invisible. Yet the entire
Data Center revenue table on slide 18 ($48B → $115B → $194B, hyperscale vs ACIE
split) is an **image**. None of those figures appear in the extracted text, which
captured only the surrounding narrative paragraph. The charts on slide 16
extracted as an unlabelled number soup.

**Always look at the contact sheets, whatever the audit says.** The audit tells
you which pages are certainly unreadable; it cannot tell you which pages are
sufficiently read.

## Honesty rules — binding

- Forecast, not prediction. The page commits to a call and shows what would
  falsify it.
- Every number on the page comes from `bundle.json`. If you want to state a
  figure you cannot find there, don't.
- Quotes are real quotes with speaker and quarter, or they are absent.
- Estimates are labelled estimates. Adjusted ≠ GAAP; state the basis.
- Base rates are what happened, with the effective sample size.
- Market sentiment is market-wide and never presented as ticker-specific.
- Guardrails from `fair-value` are reproduced, never summarised away.
- No investment advice. Say it once, plainly, and let the analysis stand.
