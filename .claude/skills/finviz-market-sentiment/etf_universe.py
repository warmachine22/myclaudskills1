#!/usr/bin/env python3
"""The 3x leveraged long universe, and the theme vocabulary that maps news to it.

Every entry here is a LONG (bull) product. Nothing inverse belongs in this file
- the recommendation layer only ever fires on bullish sentiment, so an inverse
fund would be recommended in exactly the wrong direction.

Verified against issuer product pages (MicroSectors, MAX ETNs) and fund
listings in August 2026. Three tickers from the original candidate list were
rejected; see REJECTED below for why.
"""

# --------------------------------------------------------------------------
# Theme vocabulary. Scores files may only use these tags.
# --------------------------------------------------------------------------

THEMES = {
    # breadth / style
    "broad_market": "whole-market direction, index moves, risk appetite",
    "high_beta": "speculative risk-on, junk rally, momentum chasing",
    "smallcap": "Russell 2000, small caps specifically",
    "midcap": "mid caps specifically",
    # technology
    "megacap_tech": "the mega-cap complex: AAPL MSFT GOOGL AMZN META NVDA etc",
    "tech": "technology sector broadly",
    "semis": "semiconductors, chips, foundries, chip equipment",
    "software_internet": "software, internet platforms, e-commerce",
    "ai": "AI models, AI capex, data centers, AI demand",
    # financials
    "financials": "banks, brokers, insurers, asset managers broadly",
    "banks": "large money-center banks",
    "banks_regional": "regional and community banks",
    # energy / materials
    "energy": "energy sector, integrated oil, oilfield services",
    "oil_gas": "crude prices, oil & gas exploration and production",
    "gold": "gold price, safe-haven bid, dollar debasement",
    "miners": "mining equities specifically",
    # healthcare
    "healthcare": "healthcare sector broadly, payers, providers",
    "biotech": "biotech, clinical trials, FDA decisions",
    "pharma": "large pharma, drug pricing, GLP-1",
    # industrial / transport
    "industrials": "industrial and manufacturing activity, ISM, capex",
    "defense": "defense spending, aerospace, geopolitical conflict",
    "transport": "freight, rail, trucking, logistics",
    "airlines": "airlines specifically",
    "travel": "travel, leisure, hotels, cruise, booking",
    "autos": "automakers, EVs, auto suppliers",
    # consumer / real assets
    "consumer": "consumer spending, discretionary demand",
    "retail": "retailers specifically",
    "housing": "homebuilders, housing demand, mortgages",
    "real_estate": "REITs, commercial and residential property",
    "utilities": "utilities, power demand, grid",
    # rates
    "rates_down": "falling yields, dovish Fed, bond rally, easing",
    # regions
    "china": "China, Hong Kong",
    "korea": "South Korea",
    "europe": "Europe, ECB, European equities",
    "mexico": "Mexico, USMCA, nearshoring",
    "emerging": "emerging markets broadly",
}

# --------------------------------------------------------------------------
# The universe. structure ETN = unsecured issuer credit risk, not a fund.
# --------------------------------------------------------------------------

UNIVERSE = {
    # ---- broad US equity ----
    "SPXL": ("Direxion Daily S&P 500 Bull 3X", "ETF", 3, ["broad_market"]),
    "UPRO": ("ProShares UltraPro S&P 500", "ETF", 3, ["broad_market"]),
    "UDOW": ("ProShares UltraPro Dow30", "ETF", 3, ["broad_market"]),
    "TQQQ": ("ProShares UltraPro QQQ (Nasdaq-100)", "ETF", 3,
             ["broad_market", "megacap_tech", "tech"]),
    "HIBL": ("Direxion Daily S&P 500 High Beta Bull 3X", "ETF", 3,
             ["broad_market", "high_beta"]),
    "TNA": ("Direxion Daily Small Cap Bull 3X (Russell 2000)", "ETF", 3,
            ["smallcap", "high_beta"]),
    "URTY": ("ProShares UltraPro Russell 2000", "ETF", 3, ["smallcap", "high_beta"]),
    "MIDU": ("Direxion Daily Mid Cap Bull 3X", "ETF", 3, ["midcap"]),
    "UMDD": ("ProShares UltraPro MidCap400", "ETF", 3, ["midcap"]),
    "SPYU": ("MAX S&P 500 4X Leveraged ETN", "ETN", 4, ["broad_market", "high_beta"]),

    # ---- technology / AI ----
    "TECL": ("Direxion Daily Technology Bull 3X", "ETF", 3, ["tech", "megacap_tech"]),
    "SOXL": ("Direxion Daily Semiconductor Bull 3X", "ETF", 3, ["semis", "ai", "tech"]),
    "FNGU": ("MicroSectors FANG+ 3X ETN", "ETN", 3, ["megacap_tech", "ai"]),
    "BULZ": ("MicroSectors FANG & Innovation 3X ETN", "ETN", 3,
             ["megacap_tech", "ai", "high_beta"]),
    "WEBL": ("Direxion Daily Dow Jones Internet Bull 3X", "ETF", 3,
             ["software_internet", "tech"]),
    "AIQU": ("MicroSectors Artificial Intelligence 3X ETN", "ETN", 3, ["ai", "tech"]),

    # ---- financials ----
    "FAS": ("Direxion Daily Financial Bull 3X", "ETF", 3, ["financials"]),
    "BNKU": ("MicroSectors U.S. Big Banks 3X ETN", "ETN", 3, ["banks", "financials"]),
    "DPST": ("Direxion Daily Regional Banks Bull 3X", "ETF", 3,
             ["banks_regional", "financials"]),

    # ---- energy ----
    "NRGU": ("MicroSectors U.S. Big Oil 3X ETN", "ETN", 3, ["energy", "oil_gas"]),
    "WTIU": ("MicroSectors Energy 3X ETN", "ETN", 3, ["energy"]),
    "OILU": ("MicroSectors Oil & Gas E&P 3X ETN", "ETN", 3, ["oil_gas", "energy"]),

    # ---- precious metals ----
    "GDXU": ("MicroSectors Gold Miners 3X ETN", "ETN", 3, ["gold", "miners"]),
    "SHNY": ("MicroSectors Gold 3X ETN (bullion via GLD)", "ETN", 3, ["gold"]),

    # ---- healthcare ----
    "CURE": ("Direxion Daily Healthcare Bull 3X", "ETF", 3, ["healthcare"]),
    "LABU": ("Direxion Daily S&P Biotech Bull 3X", "ETF", 3,
             ["biotech", "healthcare", "high_beta"]),
    "PILL": ("Direxion Daily Pharmaceutical & Medical Bull 3X", "ETF", 3,
             ["pharma", "healthcare"]),

    # ---- industrial / transport ----
    "DUSL": ("Direxion Daily Industrials Bull 3X", "ETF", 3, ["industrials"]),
    "DFEN": ("Direxion Daily Aerospace & Defense Bull 3X", "ETF", 3,
             ["defense", "industrials"]),
    "TPOR": ("Direxion Daily Transportation Bull 3X", "ETF", 3,
             ["transport", "industrials"]),
    "JETU": ("MAX Airlines 3X ETN", "ETN", 3, ["airlines", "travel", "transport"]),
    "FLYU": ("MicroSectors Travel 3X ETN", "ETN", 3, ["travel", "consumer"]),
    "CARU": ("MAX Auto Industry 3X ETN", "ETN", 3, ["autos", "consumer"]),

    # ---- consumer / real assets ----
    "WANT": ("Direxion Daily Consumer Discretionary Bull 3X", "ETF", 3, ["consumer"]),
    "RETL": ("Direxion Daily Retail Bull 3X", "ETF", 3, ["retail", "consumer"]),
    "NAIL": ("Direxion Daily Homebuilders & Supplies Bull 3X", "ETF", 3,
             ["housing", "rates_down", "consumer"]),
    "DRN": ("Direxion Daily Real Estate Bull 3X", "ETF", 3, ["real_estate", "rates_down"]),
    "UTSL": ("Direxion Daily Utilities Bull 3X", "ETF", 3, ["utilities"]),

    # ---- rates ----
    "TMF": ("Direxion Daily 20+ Year Treasury Bull 3X", "ETF", 3, ["rates_down"]),
    "TYD": ("Direxion Daily 7-10 Year Treasury Bull 3X", "ETF", 3, ["rates_down"]),

    # ---- international ----
    "YINN": ("Direxion Daily FTSE China Bull 3X", "ETF", 3, ["china", "emerging"]),
    "KORU": ("Direxion Daily South Korea Bull 3X", "ETF", 3, ["korea", "emerging"]),
    "EDC": ("Direxion Daily Emerging Markets Bull 3X", "ETF", 3, ["emerging"]),
    "EURL": ("Direxion Daily FTSE Europe Bull 3X", "ETF", 3, ["europe"]),
    "MEXX": ("Direxion Daily MSCI Mexico Bull 3X", "ETF", 3, ["mexico", "emerging"]),
}

# Per-ticker warnings surfaced with any recommendation.
CAVEATS = {
    "SPYU": "4X, not 3X - the most aggressive product here; decay and gap risk are correspondingly worse.",
    "JETU": "Very small ETN (~$4M AUM); wide spreads and thin liquidity.",
    "CARU": "Small ETN; thin liquidity.",
    "AIQU": "Newer ETN; check liquidity before sizing.",
    "SHNY": "Tracks gold bullion, not miners - typically a risk-OFF asset that fights a bullish equity tape.",
    "GDXU": "Gold miners are a risk-off/inflation hedge; may fight a broad risk-on rally.",
    "TMF": "Bond bull = a bet that yields FALL. A risk-on equity rally usually pushes yields UP, which hurts this.",
    "TYD": "Bond bull = a bet that yields FALL. Same tension with a risk-on tape as TMF.",
    "LABU": "Extremely volatile even by 3X standards.",
    "DPST": "Concentrated in regional banks; single-name credit events hit hard.",
}

# Rejected from the candidate list, with the reason. Surfaced so the exclusion
# is auditable rather than silent.
REJECTED = {
    "OILD": "-3X INVERSE (bearish). The 3X bull counterpart is OILU, which is in the universe.",
    "YSPY": "Not a 3X fund. GraniteShares YieldBOOST SPY - an income ETF that SELLS puts on 3X SPY; caps upside.",
    "SEMY": "Not a 3X fund. GraniteShares YieldBOOST Semiconductor - income via put-selling on 3X semis.",
}


# Presentation only: display grouping and plain-English descriptions. The
# recommendation engine never reads these - it works off `themes` in UNIVERSE.
# Kept here so the reference page can be regenerated from one source of truth.
CATEGORIES = [
    ("Broad US equity", ["SPXL", "UPRO", "UDOW", "TQQQ", "HIBL", "TNA", "URTY",
                         "MIDU", "UMDD", "SPYU"]),
    ("Technology & AI", ["TECL", "SOXL", "FNGU", "BULZ", "WEBL", "AIQU"]),
    ("Financials", ["FAS", "BNKU", "DPST"]),
    ("Energy", ["NRGU", "WTIU", "OILU"]),
    ("Precious metals", ["GDXU", "SHNY"]),
    ("Healthcare", ["CURE", "LABU", "PILL"]),
    ("Industrials & transport", ["DUSL", "DFEN", "TPOR", "JETU", "FLYU", "CARU"]),
    ("Consumer & real assets", ["WANT", "RETL", "NAIL", "DRN", "UTSL"]),
    ("Rates", ["TMF", "TYD"]),
    ("International", ["YINN", "KORU", "EDC", "EURL", "MEXX"]),
]

DESCRIPTIONS = {
    "SPXL": 'The S&P 500 — the default "market is going up" trade',
    "UPRO": "Same exposure as SPXL, different issuer",
    "UDOW": "Dow Jones Industrial Average — 30 large-cap industrial and value names",
    "TQQQ": "Nasdaq-100 — the most heavily traded 3x product; tech-weighted",
    "HIBL": "The most volatile S&P 500 names — a leveraged bet on leverage",
    "TNA": "Russell 2000 small caps — domestic and rate-sensitive",
    "URTY": "Same exposure as TNA, different issuer",
    "MIDU": "S&P MidCap 400",
    "UMDD": "Same exposure as MIDU, different issuer",
    "SPYU": "The S&P 500 at 4x — the most aggressive product in the list",
    "TECL": "Technology Select Sector — broad big tech",
    "SOXL": "Semiconductors — chips, foundries, chip equipment",
    "FNGU": "A concentrated ~10-stock mega-cap tech basket",
    "BULZ": "FANG plus higher-beta innovation names",
    "WEBL": "Internet platforms and e-commerce",
    "AIQU": "Pure AI theme — the newest addition to the universe",
    "FAS": "Financial Select Sector — banks, brokers, insurers",
    "BNKU": "~10 money-center banks, concentrated",
    "DPST": "Regional and community banks",
    "NRGU": "~10 large integrated oil majors",
    "WTIU": "~12 energy equities — not crude futures, despite the ticker",
    "OILU": "25 oil & gas exploration and production companies",
    "GDXU": "Gold mining equities",
    "SHNY": "Gold bullion via GLD — a risk-off asset",
    "CURE": "Health Care Select Sector — payers, providers, devices",
    "LABU": "Biotech",
    "PILL": "Large pharma and medical products",
    "DUSL": "Industrial Select Sector — manufacturing and capex",
    "DFEN": "Defense primes and aerospace",
    "TPOR": "Rail, trucking, freight, logistics",
    "JETU": "Airlines",
    "FLYU": "Travel, hotels, cruise, booking",
    "CARU": "Automakers, EVs, suppliers",
    "WANT": "Consumer discretionary spending",
    "RETL": "Retailers specifically",
    "NAIL": "Homebuilders and building supply — also a rates-down play",
    "DRN": "REITs — commercial and residential property",
    "UTSL": "Utilities, power demand, grid",
    "TMF": "Long-dated Treasuries — needs yields to fall",
    "TYD": "Intermediate Treasuries — same requirement as TMF",
    "YINN": "China and Hong Kong large caps",
    "KORU": "South Korea — heavily semiconductor-weighted",
    "EDC": "Broad emerging markets",
    "EURL": "Developed Europe",
    "MEXX": "Mexico — nearshoring and USMCA sensitive",
}


# Rough real-world liquidity/popularity order, most-traded first. Used ONLY as
# a deterministic tie-break between funds that map to the identical theme set
# (e.g. SPXL vs UPRO vs UDOW), and as a proxy for "what would a retail trader
# actually reach for". It is a static judgment, not a live AUM/volume feed.
POPULARITY = [
    "TQQQ", "SOXL", "SPXL", "UPRO", "TNA", "LABU", "FAS", "TECL", "FNGU",
    "UDOW", "YINN", "DPST", "NAIL", "TMF", "GDXU", "BULZ", "WEBL", "URTY",
    "MIDU", "DRN", "CURE", "DFEN", "RETL", "WANT", "DUSL", "UTSL", "PILL",
    "TPOR", "EDC", "EURL", "KORU", "MEXX", "BNKU", "NRGU", "WTIU", "OILU",
    "SHNY", "HIBL", "UMDD", "TYD", "FLYU", "AIQU", "CARU", "JETU", "SPYU",
]
POPULARITY_RANK = {t: i for i, t in enumerate(POPULARITY)}


def popularity_rank(ticker: str) -> int:
    return POPULARITY_RANK.get(ticker, len(POPULARITY))


def structure_note(ticker: str) -> str:
    entry = UNIVERSE.get(ticker)
    if entry and entry[1] == "ETN":
        return ("ETN: an unsecured note carrying issuer credit risk, not a fund "
                "holding assets.")
    return ""


def validate_themes(tags: list[str]) -> list[str]:
    """Return the tags that are not in the vocabulary."""
    return [t for t in tags if t not in THEMES]
