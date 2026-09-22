# -*- coding: utf-8 -*-
"""Brute-force ATS board-token discovery.

Tries a large list of plausible company slugs against the Greenhouse / Lever / Ashby
public board APIs. A wrong slug just 404s, so this is cheap. Records which tokens
resolve so future runs only query known-good boards.
"""
import requests, json, re, warnings, sys, io, concurrent.futures as cf
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"})
T = 15

NAMES = """
ramp brex mercury deel rippling gusto justworks namely trinet zenefits
plaid stripe block square affirm marqeta lithic unit column increase moderntreasury
robinhood webull public stash acorns betterment wealthfront titan altruist
chime varo dave current onedebit sofi upstart avant lendingclub prosper
coinbase gemini paxos anchorage bitgo fireblocks chainalysis circle kraken
datadog mongodb elastic confluent redis neo4j couchbase clickhouse timescale
cockroachlabs planetscale neon supabase render railway fly vercel netlify
sourcegraph gitlab github circleci harness launchdarkly split optimizely
sentry honeycomb chronosphere grafana newrelic cribl panther expel huntress
snyk wiz semgrep chainguard tailscale okta auth0 duo cyberark sailpoint
twilio sendgrid bandwidth vonage courier knock resend loops customerio
braze iterable klaviyo attentive segment amplitude mixpanel heap posthog
notion linear asana monday clickup airtable coda slite miro mural figma
canva loom calendly zoom dropbox box slack discord reddit pinterest quora
etsy squarespace wix webflow shopify bigcommerce faire stitchfix renttherunway
warbyparker glossier allbirds everlane bombas casper purple away
doordash instacart gopuff getir uber lyft via bird lime
peloton whoop oura levels function hims ro curology capsule
oscarhealth clover devoted alignment cedar zocdoc flatiron tempus komodohealth
springhealth headway alma talkspace maven kindbody progyny carrot
duolingo coursera udemy chegg outschool newsela amplify codecademy skillshare
compass zillow opendoor flip latch smartrent procore autodesk
flexport samsara motive project44 stord shipbob
dataminr yext olo yotpo unqork alloy middesk truework persona
lemonade policygenius hippo kin root branch nerdwallet creditkarma
seatgeek stubhub vividseats gametime dice bandsintown kickstarter patreon
substack beehiiv ghost cameo whop vimeo mux cloudinary wistia brightcove
nytimes axios businessinsider vox buzzfeed conde theathletic
criteo taboola outbrain liveintent movableink mparticle sprinklr
verkada rhombus anduril applieddintuition appliedintuition nuro zoox waymo cruise kodiak einride
scale openai anthropic cohere perplexity huggingface runwayml elevenlabs suno
cognition anysphere codeium magic poolside augment tabnine sweep
harvey decagon abridge openevidence hebbia glean writer typeface adept
modal baseten together replicate fal groq cerebras lambdalabs crusoe
warp arc raycast superhuman shortwave hey missive
carta angellist wellfound pave lattice culture-amp 15five workramp guild
betterup handshake ripplematch symplicity
epicgames riotgames unity roblox scopely zynga playco voodoo miniclip
bungie behaviour naughtydog insomniac avalanche skydance
nintendo playstation xbox netflix spotify soundcloud bandcamp
""".split()

EXTRA_ASHBY = """Valon Sierra Cape openai anthropic notion linear vercel scale
perplexity elevenlabs clipboard zapier quora whatnot uniswap maximor pariveda
n1 ellipsislabs runsybil-jobs bridger suno ramp mercury deel replit sourcegraph
modal baseten together harvey decagon abridge openevidence hebbia writer glean
column unit increase moderntreasury lithic alloy middesk truework
runway captions descript luma pika found attentive antimetal resend knock
courier loops supabase neon railway render planetscale clickhouse cognition""".split()

def try_gh(tok):
    try:
        r = S.get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs", timeout=T)
        if r.status_code == 200:
            n = len(r.json().get("jobs", []))
            if n: return ("greenhouse", tok, n)
    except Exception: pass

def try_lv(org):
    try:
        r = S.get(f"https://api.lever.co/v0/postings/{org}?mode=json", timeout=T)
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, list) and d: return ("lever", org, len(d))
    except Exception: pass

def try_ab(org):
    try:
        r = S.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}", timeout=T)
        if r.status_code == 200:
            n = len(r.json().get("jobs", []))
            if n: return ("ashby", org, n)
    except Exception: pass

names = sorted(set(NAMES))
ashby_names = sorted(set(NAMES) | set(EXTRA_ASHBY))
found = []
with cf.ThreadPoolExecutor(40) as ex:
    for fn, lst in ((try_gh, names), (try_lv, names), (try_ab, ashby_names)):
        for r in ex.map(fn, lst):
            if r: found.append(r)

by = {"greenhouse": [], "lever": [], "ashby": []}
for src, tok, n in found:
    by[src].append((tok, n))
json.dump(by, open("boards.json", "w", encoding="utf-8"), indent=1)
for k, v in by.items():
    v.sort()
    print("\n%s (%d boards, %d postings):" % (k.upper(), len(v), sum(n for _, n in v)))
    print("  " + ", ".join("%s(%d)" % (t, n) for t, n in v))
