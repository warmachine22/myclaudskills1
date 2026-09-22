export const meta = {
  name: 'conquerrts-m1-finish',
  description: 'Finish the ConquerRTS simulation core: missing tests and content, World/stepSim/hash, integration, adversarial determinism audit',
  phases: [
    { title: 'Fill gaps', detail: 'mathx tests, cards + data index, data tests' },
    { title: 'World', detail: 'UnitSoA, World, hashWorld, stepSim, scenarios, headless runner' },
    { title: 'Integrate', detail: 'Make the whole repo green and prove determinism end to end' },
    { title: 'Audit', detail: 'Three adversarial lenses, read-only' },
  ],
}

const REPO = 'C:/Users/mark5/Desktop/ConquerRTS'

const SHARED = `
PROJECT: ConquerRTS, a browser RTS roguelite at ${REPO}. Branch: feat/m1-sim-core.

ALREADY BUILT AND COMMITTED — read these before writing anything, build against
them, do NOT rewrite them:
  src/sim/core/tick.ts     fixed 20Hz constants, entity ceilings
  src/sim/core/handle.ts   generational EntityHandle packing
  src/sim/core/rng.ts      sfc32 + four named streams + hash32   (21 tests)
  src/sim/core/soa.ts      SoaPool, swap-remove, dense live prefix (21 tests)
  src/sim/core/mathx.ts    lookup-table trig, Taylor-generated     (NO TESTS YET)
  src/sim/spatial/grid.ts  counting-sort spatial hash             (14 tests)
  src/sim/commands.ts      SimCommand + CommandBuffer pool
  src/sim/events.ts        SoA EventRing
  src/data/defs.ts         content schemas
  src/data/units.ts, weapons.ts, structures.ts                    (NO TESTS YET)

Current state: pnpm typecheck, lint and 65 tests all pass. Keep it that way.

READ FIRST (binding): AGENTS.md sections 4 and 5; docs/DATA_AND_BALANCE.md;
docs/DECISION_LOG.md entries dated 2026-09-05 (determinism is EXACT; four RNG
streams; no transcendentals; pause is a sim-level concept).

ABSOLUTE RULES inside src/sim/** and src/data/**:
1. No 'three', DOM, window, document, fetch.
2. No Math.random, Date.now, new Date, performance.now.
3. No Math.sin/cos/tan/asin/acos/atan/atan2/exp/log/pow/hypot/cbrt — use
   src/sim/core/mathx.ts. Math.sqrt is allowed. Math.PI is allowed (it is a
   spec-exact constant, not an approximated function result).
4. No console.log/debug/info in src/sim.
5. No allocation in per-tick hot paths: no object/array literals, closures,
   .push/.map/.filter/spread inside anything stepSim reaches. Preallocate.
Enforced by tests/determinism/boundary.spec.ts, which greps source text.
Run \`pnpm test\` — it names exactly what you broke. Never weaken that test.

STYLE: match the existing files. Comment the non-obvious DECISION and its WHY,
not the obvious line. Never write a comment narrating a change ("now uses X",
"changed to Y") — write for someone reading the file fresh, who has no idea a
change ever happened. Boring inspectable code beats clever abstraction.

TypeScript strict; noUncheckedIndexedAccess is deliberately OFF. Use
\`import type\` for type-only imports (lint enforces it).

BEFORE RETURNING run: cd ${REPO} && pnpm typecheck && pnpm lint && pnpm test
Fix everything you broke. Do not return until it passes.

FILE OWNERSHIP IS STRICT. Other agents are editing this repo concurrently.
Create/edit ONLY the files your task lists. Never touch package.json, configs,
or another agent's files.
`

const REPORT = {
  type: 'object',
  additionalProperties: false,
  required: ['filesWritten', 'summary', 'checksPassed'],
  properties: {
    filesWritten: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string', description: '3-8 sentences: what you built and the key decisions' },
    assumptions: { type: 'array', items: { type: 'string' } },
    checksPassed: { type: 'boolean', description: 'true ONLY if you saw typecheck, lint and test all pass' },
    notes: { type: 'string' },
  },
}

phase('Fill gaps')

const GAPS = [
  {
    key: 'mathx-tests',
    prompt: `TASK: Test the deterministic math module. It shipped without tests and it is
the single most load-bearing module for cross-engine determinism.

OWN THIS FILE ONLY: tests/unit/mathx.spec.ts

Read src/sim/core/mathx.ts first and test what it actually exports.

Tests are NOT bound by the purity rule — you may freely use Math.sin/cos/atan2
in the test as the reference oracle. That is the whole point: prove the
table-based versions agree with the real ones to within tolerance.

COVER:
- sinT/cosT vs Math.sin/Math.cos across >= 10000 samples spanning several full
  turns INCLUDING large negatives and large positives. Assert max absolute
  error under 5e-4. Report the actual observed max error in the assertion
  message so a future regression is legible.
- Pythagorean identity sinT(x)^2 + cosT(x)^2 ~= 1 across the same range.
- Exact known values: sinT(0) === 0, cosT(0) === 1, and the quarter-turn values
  to tolerance.
- atan2T vs Math.atan2 over a grid of x,z spanning all four quadrants, plus
  both axes, plus the origin. Note: the module documents a DELIBERATE deviation
  at negative zero (atan2T(-0,-1) is +PI where Math.atan2 gives -PI) — assert
  the documented behaviour, do not treat it as a bug.
- normalizeAngle across wrap boundaries, and shortestAngleDelta where the
  shortest path crosses PI in both directions.
- approach() never overshoots, approached from above and below, and reaches the
  target exactly.
- clamp, lerp, smoothstep at and beyond their edges.
- dist2/length2/dist agree with each other.
- DETERMINISM: calling sinT(0.7) 1000 times returns the bit-identical value
  (use Object.is to catch a -0/+0 or NaN discrepancy).
- TABLE PURITY: read the mathx.ts source text in the test and assert it
  contains no Math.sin/Math.cos/Math.atan call. This is the regression guard
  that stops someone "simplifying" the table construction later and silently
  breaking Safari-vs-CI determinism.`,
  },
  {
    key: 'cards-and-data',
    prompt: `TASK: Finish the content layer — the card pool and the data index — then test
all of it.

OWN THESE FILES ONLY:
  src/data/cards.ts
  src/data/index.ts
  tests/unit/data.spec.ts

Read src/data/defs.ts (CardDef, CardEffect), and the already-written
src/data/units.ts, weapons.ts, structures.ts, so ids match exactly.

src/data/cards.ts — transcribe the card lists from docs/DATA_AND_BALANCE.md:
  More:   +6 Riflemen, +2 Rocket Troopers, +1 Battle Tank, +1 Gunship,
          +1 Artillery, +2 Repair Drones, Reinforcement Wave (+4 Riflemen +1 Tank)
  Better: infantry damage +18%, infantry HP +20%, tracked armour HP +22%,
          air attack speed +18%, siege reload -15%, support repair rate +25%,
          Vanguard mark duration +30%
  New:    unlock Rocket Trooper / Battle Tank / Gunship / Artillery / Repair Drone
Use the CardEffect variants already defined in defs.ts. Set requiresUnit on
"More" cards for units that must be unlocked first — offering "+1 Gunship" to a
player who has never unlocked gunships is exactly the dead card that
docs/ENGAGEMENT_AND_RETENTION.md says to protect players from.
Give each card a short qualitative \`signal\` string per
docs/UPGRADES_AND_BUILDCRAFT.md (e.g. "Raises armour concentration"). Never a
recommendation — the player reads the board.
Weights are initial tuning; say so in a comment.

src/data/index.ts — re-export every table plus prebuilt id->index Maps using
indexById() from defs.ts, so runtime lookups are O(1) into typed arrays.

tests/unit/data.spec.ts — cover ALL the content tables (units, weapons,
structures, cards):
- Referential integrity: every unit's weaponIds resolve; every structure's
  weaponId and producesUnitId resolve; every card effect's unitId/weaponId/role
  resolves. A typo here is a runtime crash at the worst possible moment.
- No duplicate ids in any table.
- Every unit has a valid formationBand and targetClass; bands cover all five
  values across the roster (front/flank/center/rear/air) so formation layout
  code can be exercised.
- Sanity: positive HP, positive range, accuracy in (0,1], supply >= 0,
  artillery minRange < range.
- Every "More" card that grants a non-starter unit declares requiresUnit.
- Spot-check hardcoded values straight from docs/DATA_AND_BALANCE.md so a
  careless future edit fails loudly: Battle Tank 280 HP, Artillery range 36,
  Generator 650 HP and 32 scrap, HQ 2600 HP, Rifleman 42 HP.
- Card kinds: at least one each of more/better/new exists.`,
  },
]

const gaps = await parallel(
  GAPS.map((g) => () =>
    agent(`${SHARED}\n\n${g.prompt}`, { label: `fill:${g.key}`, phase: 'Fill gaps', schema: REPORT }),
  ),
)
const gapsOk = gaps.filter(Boolean)
log(`${gapsOk.length}/${GAPS.length} gap tasks complete`)

const gapContext = gaps
  .map((r, i) => `--- ${GAPS[i].key} ---\n${r ? r.summary : 'FAILED — returned nothing'}`)
  .join('\n\n')

phase('World')

const world = await agent(
  `${SHARED}

TASK: World state, world hash, stepSim, scenarios, and the headless runner.
This is the layer everything from M2 onward plugs into, so the interfaces
matter more than the behaviour.

Context from the content agents that just ran:
${gapContext}

OWN THESE FILES ONLY:
  src/sim/state/units.ts
  src/sim/state/world.ts
  src/sim/state/hash.ts
  src/sim/step.ts
  src/sim/scenario.ts
  src/headless/run.ts
  tests/determinism/world.spec.ts

1) src/sim/state/units.ts — UnitSoA, parallel typed arrays sized MAX_UNITS,
   wrapping an SoaPool. At minimum: posX/posZ, posPrevX/posPrevZ, heading,
   headingPrev, velX/velZ, hp, cooldown (Float32Array); defIndex, faction,
   state, formationBand (Uint8Array); slot, targetHandle (Int32Array); plus
   per-unit stagger derived from hash32(entityId) at spawn (accelMul,
   turnRateMul, settleEpsilon, fireOffsetTicks).

   WHY stagger comes from a hash and not the RNG: docs/ARMY_AND_UNITS.md wants
   bounded per-unit variation so the army reads as disciplined rather than
   robotic. Deriving it from the entity id means adding a stagger parameter
   later consumes no RNG draws and therefore shifts no stream — the balance
   baseline survives.

   spawn(defIndex, x, z, faction) -> EntityHandle, and kill(handle).
   kill() MUST swap-remove EVERY parallel array in lockstep with the pool's
   swap. A single array left unswapped silently corrupts a unit's state and
   produces bugs that are near-impossible to trace. Use the pool's
   lastSwapFrom/lastSwapTo (or its onSwap hook) — read soa.ts to see which it
   exposes. Test this hard.

2) src/sim/state/world.ts — World owns: the UnitSoA, the four RNG streams, the
   EventRing, the SpatialGrid, tick, run clock, scrap total, Drop Meter
   progress, vanguard handle, a paused flag, and the vanguard's current move
   intent. createWorld(scenario, seed). Preallocate everything; nothing grows
   after construction.

3) src/sim/state/hash.ts — hashWorld(w): number, FNV-1a over the LIVE prefix of
   every simulation-significant array plus RNG stream states, tick, and scrap.
   Hash Float32 values by their exact BIT PATTERN via a shared
   Float32Array/Uint32Array view — never via string conversion.
   CRITICAL: exclude render-only and debug state, but do NOT exclude anything
   the next tick reads. A field that affects future ticks but is missing from
   the hash makes desync invisible, which is worse than no hash at all. State
   in a comment what you included and why.

4) src/sim/step.ts — stepSim(world, commands: CommandBuffer, tick: number).
   Establish the FIXED SYSTEM ORDER as named functions, with the order and its
   rationale documented in a comment so later milestones fill them in without
   renegotiating it:
     0 prevCopy  1 commands  2 clock  3 formation  4 slotAssign  5 flowfield
     6 movement  7 separation  8 gridRebuild  9 acquisition  10 combat
     11 damage  12 deaths  13 structures  14 spawning  15 pickups  16 dropMeter
   Genuinely implement now: prevCopy (posPrev.set(pos) etc — this is what the
   renderer interpolates against), commands (MOVE_TO / STEER set vanguard
   intent; CHOOSE_CARD and MARK_TARGET may be stubs), clock, movement
   (integrate toward intent using mathx only, respecting moveSpeed and
   turnRate), gridRebuild, and deaths (drain a preallocated pending-kill list).
   Everything else is an explicitly documented stub.
   Deaths are DEFERRED — damage accumulates, and removals all happen at step 12.
   Iterating an array while compacting it is a whole class of bug avoided by
   construction, and it makes death ordering deterministic.
   MUST NOT allocate per tick.

5) src/sim/scenario.ts — ScenarioDef plus 'empty', 'vanguard-only',
   'followers-10'. Data-shaped; real maps come later.

6) src/headless/run.ts — Node ESM entry (run via tsx). Builds a world from
   scenario+seed, steps N ticks, prints final hash and simple metrics as JSON.
   Imports ONLY src/sim and src/data. console output IS allowed here.
   CLI: --scene=<id> --seed=<n> --ticks=<n>. Keep arg parsing dumb.

7) tests/determinism/world.spec.ts:
   - sameSeedTwice: two worlds, seed 7, 3000 ticks, identical scripted commands,
     assert hashWorld(a) === hashWorld(b) EXACTLY (toBe, not toBeCloseTo).
   - differentSeedsDiverge.
   - Golden hash for ('vanguard-only', seed 7, 1000 ticks): generate it, then
     hardcode it, with a comment saying to regenerate deliberately and note it
     in the PR when simulation behaviour intentionally changes.
   - Swap-remove integrity: spawn 200 units, kill 60 scattered ones, assert the
     live prefix is dense, EVERY surviving handle still resolves to the same
     unit data it had before, and stale handles report dead. This is the test
     that matters most in this file.
   - No allocation drift: 1200 ticks, assert no internal array length changed.`,
  { label: 'world+step+hash', phase: 'World', schema: REPORT, effort: 'high' },
)

phase('Integrate')

const integ = await agent(
  `${SHARED}

TASK: Integration. Several agents just built in parallel. You are now the ONLY
agent running and may edit ANY file.

${gapContext}

--- world/step/hash ---
${world ? world.summary + (world.notes ? '\nnotes: ' + world.notes : '') : 'FAILED — the World agent returned nothing. Build src/sim/state/*, src/sim/step.ts, src/sim/scenario.ts, src/headless/run.ts and tests/determinism/world.spec.ts yourself to the spec in the workflow.'}

DO, in order:
1. cd ${REPO} && pnpm typecheck && pnpm lint && pnpm test — fix every failure.
   The boundary test is authoritative: fix the SOURCE, never the test.
2. Reconcile duplication and interface drift between modules built in parallel
   (two distance helpers, mismatched insert/query signatures, etc). Keep ONE —
   prefer the allocation-free version.
3. Make \`pnpm sim:run --scene=vanguard-only --seed=7 --ticks=600\` work. Fix the
   package.json script if wrong (you MAY edit package.json). RUN IT.
4. Run it TWICE and confirm the hash is byte-identical. Then run it with
   --seed=8 and confirm the hash DIFFERS. Report the three actual hash values
   you observed — this is the end-to-end determinism proof and I want the real
   numbers, not a claim.
5. Confirm \`pnpm build\` still succeeds and the browser entry still boots
   (nothing in src/app should have broken).
6. Remove dead scaffolding or stray files created outside assignments.

Report the exact commands and their REAL output for step 4. Do not set
checksPassed true unless you personally saw typecheck, lint, test and build all
succeed.`,
  { label: 'integrate', phase: 'Integrate', schema: REPORT, effort: 'high' },
)

phase('Audit')

const AUDIT = {
  type: 'object',
  additionalProperties: false,
  required: ['verdict', 'findings'],
  properties: {
    verdict: { enum: ['sound', 'flawed'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['severity', 'file', 'claim', 'why'],
        properties: {
          severity: { enum: ['critical', 'major', 'minor'] },
          file: { type: 'string' },
          claim: { type: 'string' },
          why: { type: 'string', description: 'The concrete call sequence or input that produces the wrong result' },
        },
      },
    },
    summary: { type: 'string' },
  },
}

const LENSES = [
  {
    key: 'determinism',
    ask: `BREAK the claim that this simulation is bit-deterministic across JS engines.
Hunt for: any transcendental Math call reaching src/sim, including indirectly or
in table construction; iteration over a Map/Set/plain object whose order could
differ; reliance on Array.sort stability or comparator ties; NaN or -0 leaking
into the world hash; and THE SUBTLE ONE — state that affects a future tick but
is NOT included in hashWorld, which makes desync invisible. Also: float
accumulation whose ORDER depends on entity index after a swap-remove, and RNG
stream cross-contamination.`,
  },
  {
    key: 'allocation',
    ask: `BREAK the claim that the per-tick path is allocation-free. Trace everything
reachable from stepSim and hunt for object/array literals, closures, .map,
.filter, .push, spread, string concatenation, boxing, or for..of over a
non-array. Verify arrays genuinely never grow, and that the EventRing and
CommandBuffer drop-and-count on overflow rather than reallocating.`,
  },
  {
    key: 'correctness',
    ask: `BREAK the entity lifecycle and the spatial grid. Hunt for: parallel arrays not
all swapped in lockstep on kill (one missed array silently corrupts a unit);
stale handles resolving alive after generation wrap; the grid missing
neighbours on the DIAGONAL when query radius exceeds cell size; off-by-one in
the dense live prefix; freeing the last element; and deferred-death ordering
producing a different result than immediate removal would. For each, give the
exact call sequence that triggers it.`,
  },
]

const audits = await parallel(
  LENSES.map((l) => () =>
    agent(
      `PROJECT: ConquerRTS at ${REPO}, branch feat/m1-sim-core.

You are an adversarial reviewer. READ ONLY — do not edit any file.

Read src/sim/**, src/data/**, tests/unit/**, tests/determinism/**, and
docs/DECISION_LOG.md entries dated 2026-09-05 for the determinism contract.

${l.ask}

Report a finding ONLY if you can name a CONCRETE sequence of calls or inputs
that produces a wrong result. "This could be fragile" is noise — omit it.
Finding nothing real is a perfectly good outcome: return verdict "sound" with an
empty findings array rather than inventing something to justify your existence.`,
      { label: `audit:${l.key}`, phase: 'Audit', schema: AUDIT, effort: 'high' },
    ),
  ),
)

const real = audits.filter(Boolean)
const allFindings = real.flatMap((a) => a.findings || [])
const blocking = allFindings.filter((f) => f.severity === 'critical' || f.severity === 'major')
log(`Audit: ${allFindings.length} findings, ${blocking.length} blocking`)

let repair = null
if (blocking.length) {
  phase('Integrate')
  repair = await agent(
    `${SHARED}

TASK: Resolve blocking findings from an adversarial audit. You may edit any
file; you are the only agent running.

FINDINGS:
${blocking.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}\n   CLAIM: ${f.claim}\n   WHY: ${f.why}`).join('\n\n')}

For each, FIRST decide whether it is real by reading the code. Auditors report
plausible-but-wrong issues; if a finding is wrong, say so and explain why rather
than "fixing" working code — an unnecessary change to determinism-critical code
is itself a risk.

For real ones: fix the source AND add a regression test that fails before the
fix and passes after. A determinism or swap-remove bug without a test comes back.

Then run: pnpm typecheck && pnpm lint && pnpm test && pnpm build
Report which findings you fixed, which you rejected and why, and the final state
of all four checks.`,
    { label: 'repair', phase: 'Integrate', schema: REPORT, effort: 'high' },
  )
}

return {
  gaps: gaps.map((r, i) => ({ key: GAPS[i].key, ok: !!r, files: r ? r.filesWritten : [] })),
  world: world ? { files: world.filesWritten, passed: world.checksPassed, notes: world.notes } : null,
  integration: integ ? { summary: integ.summary, passed: integ.checksPassed, notes: integ.notes } : null,
  audits: real.map((a, i) => ({ lens: LENSES[i].key, verdict: a.verdict, findings: (a.findings || []).length })),
  blockingFindings: blocking,
  repair: repair ? { summary: repair.summary, passed: repair.checksPassed } : null,
}
