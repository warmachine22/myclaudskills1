export const meta = {
  name: 'conquerrts-m1-sim-core',
  description: 'Build the ConquerRTS deterministic simulation core in parallel, then integrate and adversarially verify determinism',
  phases: [
    { title: 'Primitives', detail: 'RNG, LUT math, SoA pool, spatial grid, content tables — disjoint file ownership' },
    { title: 'World', detail: 'World state, world hash, stepSim, headless runner' },
    { title: 'Integrate', detail: 'Run the full suite and fix what fails' },
    { title: 'Audit', detail: 'Adversarial determinism review' },
  ],
}

const REPO = 'C:/Users/mark5/Desktop/ConquerRTS'

const SHARED = `
PROJECT: ConquerRTS, a browser RTS roguelite at ${REPO}. You are on branch feat/m1-sim-core.

READ FIRST (they are binding, not advisory):
- AGENTS.md sections 4 (performance constraints) and 5
- docs/DATA_AND_BALANCE.md (canonical numbers)
- docs/DECISION_LOG.md entries dated 2026-09-05 (determinism is EXACT, four RNG streams, no transcendentals)
- The already-written contracts you MUST build against, do NOT modify:
  src/sim/core/tick.ts, src/sim/core/handle.ts, src/sim/commands.ts,
  src/sim/events.ts, src/data/defs.ts

ABSOLUTE RULES for anything under src/sim/** or src/data/**:
1. NO imports of 'three', DOM, window, document, localStorage, fetch.
2. NO Math.random, Date.now, new Date, performance.now.
3. NO Math.sin/cos/tan/asin/acos/atan/atan2/exp/log/pow/hypot/cbrt. These are
   implementation-defined in ECMA-262 and are NOT bit-identical between V8 and
   JavaScriptCore (Safari on the target iPad). Use the lookup-table helpers in
   src/sim/core/mathx.ts. Math.sqrt IS allowed (IEEE-754 exactly specifies it).
4. NO console.log/debug/info inside src/sim.
5. NO allocation in per-tick hot paths: no object literals, array literals,
   .push(), .map(), .filter(), closures, or spread inside functions that run
   every tick. Preallocate in constructors; reuse buffers.
   These are enforced by tests/determinism/boundary.spec.ts, which greps the
   source text. Run \`pnpm test\` and it will tell you exactly what you broke.

STYLE (AGENTS.md section 5): "prefer boring, inspectable code over clever
abstractions." Structure-of-arrays is not boring, so compensate with a
documented naming convention and comments that explain WHY, not what. Comment
density should match the existing files — comment the non-obvious decision, not
the obvious line. Never write a comment that narrates a change ("now uses X",
"changed to Y"); write for someone reading the file fresh.

TypeScript is strict. tsconfig has noUncheckedIndexedAccess OFF deliberately.
Use \`import type\` for type-only imports (enforced by lint).

VERIFY YOUR OWN WORK before returning: run
  cd ${REPO} && pnpm typecheck && pnpm lint && pnpm test
Fix everything you broke. Do not return until your own files pass.

FILE OWNERSHIP IS STRICT. Other agents are working in this repo RIGHT NOW on
different files. Create/edit ONLY the files listed in your task. Do not touch
package.json, configs, or any file assigned to someone else. If you need
something from another module that does not exist yet, code against the
interface described in your task and note the assumption in your return value.
`

const REPORT = {
  type: 'object',
  additionalProperties: false,
  required: ['filesWritten', 'summary', 'assumptions', 'checksPassed'],
  properties: {
    filesWritten: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string', description: 'What you built and the key design decisions, 3-8 sentences' },
    assumptions: { type: 'array', items: { type: 'string' }, description: 'Interfaces you assumed from modules not yet written' },
    checksPassed: { type: 'boolean', description: 'true only if typecheck, lint and test all passed when you finished' },
    notes: { type: 'string', description: 'Anything the integrator must know' },
  },
}

const PRIMITIVES = [
  {
    key: 'rng',
    prompt: `TASK: Seeded PRNG with named streams.

OWN THESE FILES ONLY:
  src/sim/core/rng.ts
  tests/unit/rng.spec.ts

Implement sfc32 seeded through splitmix32. Chosen over PCG32 (needs 64-bit
multiply, so BigInt or manual limbs in JS — slow and error-prone) and over
Mulberry32 (weaker). sfc32 is pure 32-bit: Math.imul, >>>0, |0, identical on
every JS engine.

class Rng with: seed(s: number): void  (splitmix32 x4 into a..d, then 12 warmup
rounds), nextU32(): number, nextFloat(): number  (nextU32() * 2.3283064365386963e-10,
giving [0,1)), nextRange(lo, hi): number, nextInt(n): number  (unbiased-enough
via the multiply-high trick, NOT modulo), saveTo(out: Uint32Array, offset): void,
loadFrom(src: Uint32Array, offset): void.

Also export a Streams type/class holding FOUR independent Rng instances named
combat, spawn, cards, city. Seed each as splitmix32(masterSeed ^ SALT[i]) with
four distinct compile-time salt constants.

WHY four streams (put this reasoning in a comment): balance suites run across
canonical seeds. With one stream, adding a single accuracy roll to a new weapon
reshuffles every card offer in every seed and invalidates the whole balance
baseline. Separate streams mean combat changes never perturb card sequences.

Also export hash32(x: number): number — a fast integer avalanche hash. Used for
per-unit "personality" (formation stagger) at spawn so those parameters consume
no RNG draws and adding one later shifts no stream.

TESTS (tests/unit/rng.spec.ts):
- Golden vector: assert the first 16 nextU32() values for seed 12345 match a
  committed array. Generate it from your implementation, then hardcode it. This
  catches accidental PRNG edits instantly.
- Same seed twice produces identical sequences.
- Different seeds diverge.
- save/load round-trips exactly mid-sequence.
- nextFloat() stays in [0,1) over 100k draws.
- nextInt(n) covers all buckets and never returns n, over 100k draws.
- The four streams are independent: drawing from combat does not change what
  cards produces next.
- hash32 is deterministic and well-distributed over 10k sequential inputs.`,
  },
  {
    key: 'mathx',
    prompt: `TASK: Deterministic math helpers. This module is what makes cross-engine
determinism possible, so correctness here is load-bearing.

OWN THESE FILES ONLY:
  src/sim/core/mathx.ts
  tests/unit/mathx.spec.ts

Math.sin/cos/atan2 are implementation-defined in ECMA-262 and are NOT
bit-identical between V8 (Node CI, Chromium E2E) and JavaScriptCore (Safari on
the owner's iPad). The deployed build must produce the same world hash as CI,
so the simulation cannot call them. Provide table-based replacements.

Implement:
- sinT(radians), cosT(radians): a shared 4096-entry Float32Array lookup table
  over [0, 2*PI), integer index, LINEAR INTERPOLATION between adjacent entries.
  Must handle negative and large-magnitude inputs by wrapping. Precision is far
  beyond what unit positions need — target max abs error < 5e-4.
- atan2T(z, x): table/octant-based approximation, max abs error < 1e-3, correct
  in all four quadrants, correct at the axes, and atan2T(0,0) === 0.
- IMPORTANT: build the tables ONCE at module load. You may use Math.sin/Math.cos
  in the table CONSTRUCTION only — add an eslint-disable comment plus a clear
  explanation of why that is safe (the table is built identically everywhere
  because it is built from the same constant inputs... actually it is NOT
  guaranteed identical across engines). THEREFORE: do NOT build the table from
  Math.sin. Generate it with a deterministic polynomial/CORDIC approximation
  you implement yourself using only +,-,*,/ and Math.sqrt, so the table bytes
  are identical on every engine. This is the crux of the whole module — get it
  right and explain it in a comment.
- clamp(v, lo, hi), lerp(a, b, t), smoothstep(edge0, edge1, x)
- approach(current, target, maxDelta): move toward target without overshoot
- normalizeAngle(a): wrap to (-PI, PI]
- shortestAngleDelta(from, to): signed smallest rotation
- length2(x, z), dist2(ax, az, bx, bz) (squared, no sqrt — prefer these in hot
  paths), and dist(ax, az, bx, bz)
- PI, TWO_PI, HALF_PI constants

TESTS (tests/unit/mathx.spec.ts):
- sinT/cosT accuracy against Math.sin/Math.cos across 10k samples spanning
  several full turns including negatives. (Using Math.sin in the TEST is fine —
  tests are not in src/sim and are not bound by the purity rule.)
- Identity: sinT(x)^2 + cosT(x)^2 ~= 1.
- atan2T against Math.atan2 across a grid of x,z including axes and origin.
- normalizeAngle and shortestAngleDelta across wrap boundaries, including the
  case where the shortest path crosses PI.
- approach never overshoots, from both directions.
- Determinism: calling sinT(0.7) a thousand times returns the bit-identical
  value every time.`,
  },
  {
    key: 'soa',
    prompt: `TASK: Structure-of-arrays entity pool with generational handles.

OWN THESE FILES ONLY:
  src/sim/core/soa.ts
  tests/unit/soa.spec.ts

AGENTS.md section 4 forbids one JS object per simulated unit. Entity state lives
in parallel typed arrays; this module provides the allocation/removal machinery
they share.

Implement class SoaPool:
- constructor(capacity: number)
- alloc(): EntityHandle  — returns NULL_HANDLE when full (never grows, never throws)
- free(handle: EntityHandle): boolean  — false if the handle is stale
- isAlive(handle: EntityHandle): boolean
- indexOf(handle: EntityHandle): number  — returns -1 if stale
- handleAt(index: number): EntityHandle
- count: number  — live entities, always a DENSE prefix [0, count)
- capacity: number
- clear(): void

REMOVAL IS SWAP-REMOVE so iteration stays cache-friendly over a dense range.
free() must report which index moved into the freed slot so callers can move
their parallel array data: expose \`lastSwapFrom\` / \`lastSwapTo\` fields (or an
onSwap callback set once at construction — NOT per call, that allocates).
Bump the generation on free so stale handles resolve as dead.

Use the helpers in src/sim/core/handle.ts (makeHandle, handleIndex,
handleGeneration, nextGeneration, NULL_HANDLE). Do not reimplement them.

Also export a small helper for the parallel-array pattern the systems will use,
e.g. swapRemoveF32(arr, to, from) / swapRemoveU8 / swapRemoveI32 — trivial but
having one named place prevents each system inventing its own.

TESTS (tests/unit/soa.spec.ts):
- alloc returns distinct handles; count tracks; capacity is respected and
  alloc returns NULL_HANDLE at the ceiling rather than throwing.
- free() bumps the generation: the old handle is no longer alive, and a handle
  allocated into the same slot afterwards is a DIFFERENT handle that IS alive.
  This is the core bug this module exists to prevent — test it hard.
- Swap-remove keeps the live set dense: after freeing from the middle of 100
  entities, indices [0, count) are exactly the surviving handles.
- lastSwapFrom/lastSwapTo correctly identify the moved entity, and are
  meaningful when freeing the LAST element (no swap occurred).
- Generation wraps safely after many alloc/free cycles on one slot (loop 5000
  times) and never produces a false "alive" for a stale handle.
- clear() resets to empty and handles from before clear() are dead.
- Zero allocation: alloc/free in a 100k-iteration loop must not throw and must
  leave count correct.`,
  },
  {
    key: 'grid',
    prompt: `TASK: Uniform spatial hash for local neighbour queries.

OWN THESE FILES ONLY:
  src/sim/spatial/grid.ts
  tests/unit/grid.spec.ts

AGENTS.md section 4: "Use spatial hashing/grid queries for local target
acquisition." At 400 units, an O(N^2) scan is 160k distance checks per tick.
This makes target acquisition and unit separation local.

Implement class SpatialGrid:
- constructor(worldSize: number, cellSize: number) — square world centred on the
  origin, so coordinates span [-worldSize/2, +worldSize/2]
- clear(): void
- insert(handleOrIndex: number, x: number, z: number): void
- rebuild-style usage: cleared and refilled once per tick

Query API, and this is the important part — it MUST NOT allocate:
- queryInto(x, z, radius, out: Int32Array): number — fills \`out\` with candidate
  entity ids, returns how many were written, never exceeds out.length.
  Candidates are cell-level, so callers still do an exact distance check.
- forEachInRadius(x, z, radius, fn) is acceptable as an alternative but the
  Int32Array version must exist because the hot paths need it.

IMPLEMENTATION: use the counting-sort / bucket-offset layout, not arrays of
arrays. Two passes: count per cell, prefix-sum into cellStart, then scatter
entity ids into a flat Int32Array. This preallocates once and produces zero
garbage per rebuild. Out-of-bounds positions must clamp into edge cells rather
than crash or silently drop — a unit walking off the map is a bug, but dropping
it from the grid makes it invisible to combat, which is a worse bug.

Include a cheap way to iterate the grid for debug visualisation (cell counts).

TESTS (tests/unit/grid.spec.ts):
- Inserted points are found by a query covering them; distant points are not.
- A query radius spanning multiple cells returns everything in range (test the
  diagonal case explicitly — a naive 3x3 neighbourhood misses corners when
  radius > cellSize).
- No false negatives: brute-force compare against an O(N^2) scan over 500 random
  points (use a seeded RNG from src/sim/core/rng.ts if it exists, otherwise a
  simple deterministic LCG local to the test) and assert the grid returns a
  SUPERSET of the true in-radius set.
- out-array capacity is respected: a query with more candidates than out.length
  writes exactly out.length and returns that, without overrunning.
- Positions outside the world clamp rather than throw.
- clear() empties it.
- Rebuilding 1000 times does not grow any internal array (assert lengths stable).`,
  },
  {
    key: 'content',
    prompt: `TASK: Content tables — the canonical game data.

OWN THESE FILES ONLY:
  src/data/units.ts
  src/data/weapons.ts
  src/data/structures.ts
  src/data/cards.ts
  src/data/index.ts
  tests/unit/data.spec.ts

Transcribe docs/DATA_AND_BALANCE.md into typed tables using the schemas already
defined in src/data/defs.ts (UnitDef, WeaponDef, StructureDef, CardDef,
CardEffect). DO NOT modify defs.ts. DO NOT invent numbers that the doc supplies.
Where the doc is silent on a field the schema requires (turnRate, radius,
accuracy, targetClass, produceEverySeconds, rebuild timings), choose a sensible
value, and mark it in a comment as initial tuning per AGENTS.md section 10.

FROM THE DOC — transcribe faithfully:
- Player roster: Vanguard, Rifleman, Rocket Trooper, Battle Tank, Gunship,
  Artillery, Repair Drone (HP / speed / supply / range / identity all given).
- Weapons: Vanguard rifle, infantry rifle, rocket launcher, tank cannon,
  gunship attack, artillery shell, repair beam — damage, rate, multipliers.
  Note artillery has a MINIMUM range (the doc says so; pick a value and mark it
  initial tuning).
- City units: Security Trooper, Rocket Infantry, Heavy Gunner, Hunter Drone,
  Strike Drone, IFV, Heavy Tank, Counter-Battery Walker, Repair Crawler.
  The doc gives HP and role; derive the rest consistently with the player
  roster's scale and mark as initial tuning.
- Structures: Scrap Depot, Generator, Factory, Turret, Command Spire, Shield
  Emitter, HQ — HP, scrap, integrity weight, rebuildable flag.
- Cards: the initial More list, Better list, and New list from the doc.

FORMATION BANDS matter — set formationBand correctly per docs/ARMY_AND_UNITS.md:
armour->front, infantry->flank, support->center, siege->rear, air->air.
The Vanguard is not in a band (he is the anchor); give him 'front' and tag him.

Gate A only uses Rifleman, Rocket Trooper and Security Trooper, but define the
whole roster now — it is pure data, it costs nothing, and it lets the formation
layout code be exercised across all five bands immediately.

src/data/index.ts should re-export the tables plus prebuilt id->index maps using
indexById from defs.ts.

TESTS (tests/unit/data.spec.ts):
- Every unit's weaponIds resolve to a real weapon.
- Every structure's weaponId / producesUnitId resolve.
- Every card's effects reference real unit and weapon ids.
- No duplicate ids within any table.
- Every unit has a valid formationBand and targetClass.
- Numbers are sane: positive HP, positive range, accuracy in (0,1], supply >= 0.
- Spot-check a handful of values directly against docs/DATA_AND_BALANCE.md
  (e.g. Battle Tank 280 HP, Artillery range 36, Generator 650 HP / 32 scrap) so
  a future careless edit to the tables fails loudly.`,
  },
]

phase('Primitives')
log('Building 5 independent primitive modules with disjoint file ownership')

// Barrier is correct here: the World module in the next phase imports ALL of
// these, so it cannot start until every one exists.
const built = await parallel(
  PRIMITIVES.map((p) => () =>
    agent(`${SHARED}\n\n${p.prompt}`, {
      label: `build:${p.key}`,
      phase: 'Primitives',
      schema: REPORT,
    }),
  ),
)

const ok = built.filter(Boolean)
const failedKeys = PRIMITIVES.filter((p, i) => !built[i]).map((p) => p.key)
if (failedKeys.length) log(`WARNING: primitives that returned nothing: ${failedKeys.join(', ')}`)
log(`${ok.length}/${PRIMITIVES.length} primitives built`)

const context = ok
  .map((r, i) => `--- ${PRIMITIVES[i]?.key ?? 'module'} ---\n${r.summary}\nfiles: ${(r.filesWritten || []).join(', ')}\nassumptions: ${(r.assumptions || []).join('; ') || 'none'}`)
  .join('\n\n')

phase('World')

const world = await agent(
  `${SHARED}

TASK: World state, world hash, and stepSim. You are integrating the primitives
five other agents just built. Their reports:

${context}

READ their actual source before using them — the reports may be imprecise.

OWN THESE FILES ONLY:
  src/sim/state/units.ts
  src/sim/state/world.ts
  src/sim/state/hash.ts
  src/sim/step.ts
  src/sim/scenario.ts
  src/headless/run.ts
  tests/determinism/world.spec.ts

BUILD:

1) src/sim/state/units.ts — UnitSoA: parallel typed arrays sized MAX_UNITS.
   At minimum: posX, posZ, posPrevX, posPrevZ (Float32Array), heading,
   headingPrev, velX, velZ, hp, cooldown (Float32Array), defIndex, faction,
   state, formationBand (Uint8Array), slot, targetHandle (Int32Array),
   and the per-unit stagger fields derived from hash32 at spawn
   (accelMul, turnRateMul, settleEpsilon, fireOffsetTicks).
   Wrap an SoaPool. Provide spawn(defIndex, x, z, faction) and kill(handle),
   and make kill() correctly swap-remove EVERY parallel array in lockstep with
   the pool's swap. Getting that wrong is the single most likely source of
   bizarre bugs later, so write it carefully and test it.

2) src/sim/state/world.ts — World: owns the unit SoA, the four RNG streams, the
   event ring, the spatial grid, tick counter, run clock, scrap total, Drop
   Meter progress, and a paused flag. createWorld(scenario, seed) builds it.
   Preallocate everything; no growth after construction.

3) src/sim/state/hash.ts — hashWorld(w): number. FNV-1a over the LIVE prefix of
   every simulation-significant array (positions, headings, hp, targets, slots,
   RNG stream states, tick, scrap). Must NOT include render-only or debug state.
   Float32 values must be hashed via their exact bit pattern — use a shared
   Float32Array/Uint32Array view, not string conversion. This function is the
   spine of every determinism test, so it must be total and stable.

4) src/sim/step.ts — stepSim(world, commands: CommandBuffer, tick: number).
   Establish the FIXED SYSTEM ORDER as named no-op-or-minimal functions with
   the ordering documented in a comment, so later milestones fill them in
   without renegotiating the order:
     0 prevCopy (posPrev.set(pos) etc — do implement this, it is what the
       renderer interpolates against)
     1 commands  2 clock  3 formation  4 slotAssign  5 flowfield  6 movement
     7 separation  8 gridRebuild  9 acquisition  10 combat  11 damage
     12 deaths  13 structures  14 spawning  15 pickups  16 dropMeter
   For M1, implement genuinely: prevCopy, commands (MOVE_TO/STEER update a
   vanguard intent), clock (advance tick and run timer), movement (integrate
   velocity toward the move target using mathx only), gridRebuild, and
   deaths (drain a pending-kill list). The rest are documented stubs.
   MUST NOT allocate per tick.

5) src/sim/scenario.ts — ScenarioDef plus a couple of tiny scenarios
   ('empty', 'vanguard-only', 'followers-10') that createWorld can build. Keep
   it data-shaped; map content comes later.

6) src/headless/run.ts — a plain Node ESM entry (run via tsx) that builds a
   world from a scenario+seed, steps N ticks with an empty or scripted command
   buffer, and prints the final hash plus simple metrics as JSON. It may import
   ONLY src/sim, src/data. Console output IS allowed here (it is not src/sim).
   CLI: --scene=<id> --seed=<n> --ticks=<n>. Keep the arg parsing dumb.

7) tests/determinism/world.spec.ts:
   - sameSeedTwice: two worlds from seed 7, 3000 ticks each with an identical
     scripted command sequence, assert hashWorld(a) === hashWorld(b) EXACTLY.
   - differentSeedsDiverge.
   - A committed golden hash for ('vanguard-only', seed 7, 1000 ticks):
     generate it, then hardcode it, with a comment saying to regenerate
     deliberately and note it in the PR when simulation behaviour changes.
   - Spawn/kill integrity: spawn 200 units, kill 60 scattered ones, assert the
     live prefix is dense, every surviving handle still resolves to the SAME
     unit data it had before (this is the swap-remove test that matters), and
     stale handles are dead.
   - noAllocationDrift: run 1200 ticks; assert no internal array length changed.

Report precisely what you implemented versus stubbed.`,
  { label: 'world+step+hash', phase: 'World', schema: REPORT },
)

phase('Integrate')

const integ = await agent(
  `${SHARED}

TASK: Integration pass. Six agents just built the simulation core in parallel.
Your job is to make the whole repo green and coherent — you are the only agent
running now, so you may edit ANY file.

Reports from the builders:
${context}

--- world/step/hash ---
${world ? world.summary : 'FAILED — the World agent returned nothing. Build or repair src/sim/state/*, src/sim/step.ts, src/headless/run.ts yourself.'}
${world && world.notes ? 'notes: ' + world.notes : ''}

DO:
1. cd ${REPO} && pnpm typecheck && pnpm lint && pnpm test
   Fix every failure. The determinism boundary test (tests/determinism/
   boundary.spec.ts) is authoritative — if it flags something in src/sim, fix
   the source, do NOT weaken the test.
2. Reconcile duplication and mismatched interfaces between the parallel modules
   (e.g. two agents both writing a distance helper, or grid expecting a
   different insert signature than world calls). Prefer the version that is
   allocation-free and keep ONE.
3. Wire a real smoke path: \`pnpm sim:run --scene=vanguard-only --seed=7 --ticks=600\`
   must run and print a hash. Run it. If package.json's sim:run script is wrong,
   fix it (you may edit package.json).
4. Run it TWICE and confirm the printed hash is identical. Then confirm a
   different seed gives a different hash. This is the end-to-end determinism
   proof — report the actual hashes you observed.
5. Make sure \`pnpm build\` still succeeds and the app still boots (the browser
   entry must not import anything that broke).
6. Delete any dead scaffolding, TODO stubs that are actually unreachable, or
   files an agent created outside its assignment.

Return the exact commands you ran and their real output for the determinism
check. Do NOT claim checksPassed unless you personally saw all four of
typecheck, lint, test, and build succeed.`,
  { label: 'integrate+green', phase: 'Integrate', schema: REPORT, effort: 'high' },
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
          why: { type: 'string', description: 'Concrete scenario where this breaks' },
        },
      },
    },
    summary: { type: 'string' },
  },
}

// Three adversarial lenses, run concurrently. All READ-ONLY: they must not edit,
// so they cannot conflict with each other.
const LENSES = [
  {
    key: 'determinism',
    ask: `Try to BREAK the claim that this simulation is bit-deterministic across
JS engines. Hunt specifically for: any transcendental Math call reaching the sim
(including indirectly, or in table construction); iteration over a Map/Set/object
whose order could differ; reliance on Array.sort stability or on sort comparator
ties; NaN or -0 leaking into the hash; the world hash omitting state that
actually affects future ticks (that is the subtle one — a field not hashed but
read next tick makes desync invisible); float accumulation whose ORDER depends on
entity index after a swap-remove; and RNG stream cross-contamination.`,
  },
  {
    key: 'allocation',
    ask: `Try to BREAK the claim that the per-tick path is allocation-free.
Hunt for: object/array literals, closures, .map/.filter/.push/spread, string
concatenation, boxing, or iterator protocol use (for..of over a non-array) in
anything reachable from stepSim. Also check that arrays genuinely never grow and
that the event ring and command buffer drop rather than reallocate on overflow.`,
  },
  {
    key: 'correctness',
    ask: `Try to BREAK the swap-remove and handle machinery, and the spatial grid.
Hunt for: parallel arrays that are not all swapped in lockstep on kill (a single
missed array silently corrupts a unit); stale handles that resolve alive after
generation wrap; the grid missing neighbours on the diagonal when radius exceeds
cell size; off-by-one in the dense live prefix; and the case of freeing the last
element. For each, describe the concrete sequence of calls that produces the bug.`,
  },
]

const audits = await parallel(
  LENSES.map((l) => () =>
    agent(
      `PROJECT: ConquerRTS at ${REPO}, branch feat/m1-sim-core.

You are an adversarial reviewer. READ ONLY — do not edit any file.

Read the simulation core: src/sim/**, src/data/**, tests/unit/**,
tests/determinism/**. Also read docs/DECISION_LOG.md entries dated 2026-09-05
for the determinism contract.

${l.ask}

Default to reporting a finding only if you can name a CONCRETE sequence of
calls or inputs that produces the wrong result. Speculative "this could be
fragile" observations are noise — omit them. If you find nothing real, return
verdict "sound" with an empty findings array; that is a perfectly good answer
and is much better than inventing something.`,
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

TASK: Fix the blocking findings from an adversarial audit of the simulation core.
You may edit any file. You are the only agent running.

FINDINGS:
${blocking.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}\n   CLAIM: ${f.claim}\n   WHY: ${f.why}`).join('\n\n')}

For each: first decide whether it is REAL by reading the code. Auditors
sometimes report plausible-but-wrong issues — if a finding is wrong, say so and
explain why rather than "fixing" working code.

For the real ones: fix the source, and ADD A REGRESSION TEST that fails before
your fix and passes after. A determinism or swap-remove bug without a test will
come back.

Then run: pnpm typecheck && pnpm lint && pnpm test && pnpm build
Report which findings you fixed, which you rejected and why, and the final
state of all four checks.`,
    { label: 'repair', phase: 'Integrate', schema: REPORT, effort: 'high' },
  )
}

return {
  primitives: ok.map((r, i) => ({ key: PRIMITIVES[i]?.key, files: r.filesWritten, passed: r.checksPassed })),
  primitivesFailed: failedKeys,
  world: world ? { files: world.filesWritten, passed: world.checksPassed, notes: world.notes } : null,
  integration: integ ? { summary: integ.summary, passed: integ.checksPassed, notes: integ.notes } : null,
  auditVerdicts: real.map((a, i) => ({ lens: LENSES[i]?.key, verdict: a.verdict, count: (a.findings || []).length })),
  blockingFindings: blocking,
  repair: repair ? { summary: repair.summary, passed: repair.checksPassed } : null,
}
