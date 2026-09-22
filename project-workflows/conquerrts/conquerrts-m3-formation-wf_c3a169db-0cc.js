export const meta = {
  name: 'conquerrts-m3-formation',
  description: 'Followers marching in role-based formation with column-to-line deployment, plus a visual pass on palette and sightlines',
  phases: [
    { title: 'Build', detail: 'Formation system, followers, debug gizmos, visual polish' },
    { title: 'Integrate', detail: 'Wire up, make green, capture screenshots' },
    { title: 'Judge', detail: 'Does it read as an army or a blob?' },
  ],
}

const REPO = 'C:/Users/mark5/Desktop/ConquerRTS'

const SHARED = `
PROJECT: ConquerRTS at ${REPO}. Branch: feat/m2-vanguard.

WHAT EXISTS AND WORKS (257 tests green — read before writing, do not rewrite):
  src/sim/core/       tick (TICK_HZ 20, TICK_DT), mathx (sinT/cosT/atan2T,
                      clamp, lerp, smoothstep, approach, normalizeAngle,
                      shortestAngleDelta, dist/dist2/length/length2), rng
                      (four streams + hash32), soa (SoaPool, generational
                      handles, swap-remove), handle
  src/sim/spatial/grid.ts   SpatialGrid, allocation-free queryInto
  src/sim/state/      units.ts (UnitSoA: posX/posZ, posPrevX/posPrevZ, heading,
                      headingPrev, velX/velZ, hp, defIndex, faction, slot,
                      per-unit stagger from hash32), world.ts, hash.ts
  src/sim/systems/    commands.ts, movement.ts  (Vanguard steering works)
  src/sim/step.ts     fixed 17-phase order; formation/slotAssign/separation are stubs
  src/sim/scenario.ts 'empty' / 'vanguard-only' / 'followers-10'
  src/data/           16 units, 7 structures, 19 cards, formationBand on every unit
  src/render/         Renderer, CameraRig (42deg pitch, 55 FOV, follow+zoom),
                      units/InstancedUnitLayer + silhouettes + palette,
                      scene/arena + cityBlocks + skyline + lighting, interp
  src/input/          PointerRouter, TouchSteer, TapTarget, CameraGesture
  src/ui/             PerfHud (with .stats()), TouchHud
  tools/              shot.mjs (screenshots), perfprobe.mjs (real-GPU perf)

MEASURED BASELINE on a real GPU: 60fps locked, render cpu 1.4ms, sim 0.2ms,
~30 draw calls, ~16k triangles, 1 unit. There is a lot of headroom.

READ FIRST (binding): AGENTS.md sections 3, 4, 8; docs/ARMY_AND_UNITS.md in
full; docs/VISUAL_STYLE.md; docs/RENDERING_AND_WORLD_PRESENTATION.md;
docs/DECISION_LOG.md 2026-09-05.

HARD RULES in src/sim/** and src/data/**: no 'three', no DOM, no
Math.random/Date/performance, no transcendental Math (use mathx), no
console.log, NO PER-TICK ALLOCATION. Enforced by
tests/determinism/boundary.spec.ts — fix the source, never the test.

HARD RULES in src/render/** and src/ui/**: read simulation state, never mutate
it. No per-frame allocation in the draw path — hoist scratch Vector3/Matrix4 to
instance scope.

STYLE: match the existing files. Comment the non-obvious DECISION and its WHY.
Never write a comment narrating a change ("now uses X", "changed from Y") —
write for a reader who does not know a change happened.

TypeScript strict; noUncheckedIndexedAccess deliberately OFF; \`import type\`.

BEFORE RETURNING, run each gate SEPARATELY (piping into tail masks exit codes):
  cd ${REPO} && pnpm typecheck && pnpm lint && pnpm test
Do not return until all three pass.

FILE OWNERSHIP IS STRICT. Other agents edit this repo concurrently. Touch ONLY
your listed files.
`

const REPORT = {
  type: 'object',
  additionalProperties: false,
  required: ['filesWritten', 'summary', 'checksPassed'],
  properties: {
    filesWritten: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
    assumptions: { type: 'array', items: { type: 'string' } },
    checksPassed: { type: 'boolean' },
    notes: { type: 'string' },
  },
}

const TASKS = [
  {
    key: 'formation-layout',
    prompt: `TASK: Formation slot geometry and assignment. This is the highest-risk system
in the entire project. AGENTS.md: "the army must form and deploy like an army,
not boids following a cursor." If this reads as a blob, nothing else matters.

OWN THESE FILES ONLY:
  src/sim/formation/layout.ts
  src/sim/formation/fillOrder.ts
  src/sim/formation/assign.ts
  src/sim/formation/state.ts
  src/data/formation.ts
  tests/unit/formation.spec.ts

THE CORE THESIS, and the reason this design is shaped the way it is: the
army-vs-boids difference is NOT the steering algorithm. It is (a) stable slot
identity across transitions, (b) POSITIONAL rather than steering-based
separation, and (c) units facing a common direction when settled. Build for
those three properties.

--- ANCHOR FRAME (state.ts) ---
Formation geometry is authored in a local 2D frame and transformed to world.
  origin  = Vanguard position pushed BACKWARD along forward by ANCHOR_LEAD
            (initial tuning 5m), so the Vanguard sits at the HEAD of the
            formation, not its centre. He leads; that is the fantasy.
  forward = SMOOTHED Vanguard heading, exponential smoothing ~0.75s time
            constant, with a velocity deadzone so a stationary Vanguard keeps
            his last heading.
NEVER use instantaneous velocity for forward. That makes the entire army
pinwheel on every touch correction and is the single fastest way to produce the
swarm look.
In DEPLOYING/LINE, forward retargets toward the contact centroid rather than
travel heading — that is what makes the line face the ENEMY instead of facing
the direction of march.

FormationState holds: mode (COLUMN | DEPLOYING | LINE | UNDEPLOYING | HOLD |
RETREAT), deployT (0..1), originX/originZ, fwdX/fwdZ, fwdTargetX/fwdTargetZ,
contactTicks, noContactTicks, layoutDirty, lastCountByBand (Uint8Array len 5),
slotCount.

--- THREE PARALLEL LAYOUTS, ONE SLOT INDEX (layout.ts) ---
Preallocate to MAX_SUPPLY:
  columnLocalX/Z, lineLocalX/Z, retreatLocalX/Z : Float32Array
  slotBand: Uint8Array, slotFillOrder: Int32Array, slotOccupant: Int32Array
  bandSlotStart/bandSlotCount: Int32Array(5), bandFillOrder: Int32Array
Live slot position = lerp(columnLocal, lineLocal, ease(deployT)).

THE CRITICAL TRICK: slot IDENTITY is constant through the transition. A unit in
front slot #7 stays in front slot #7 and simply WALKS from its column position
to its line position. Nobody re-sorts mid-deploy. That is what produces a drill
manoeuvre instead of a scramble, and it is why the two layouts must be
generated as parallel arrays rather than as two independent formations.

COLUMN form (forward = +Z), from docs/ARMY_AND_UNITS.md's march spec:
  air    orbit, +14 ahead                    scouts ahead/above
  front  3 files at x = -3, 0, +3, z +6      armour at the head
  flank  1 file per side at x = +/-9, z +4 -> -12   infantry screening the length
  center 3 files x = -2, 0, +2, z -2 -> -8   support protected inside
  rear   2 files x = +/-3, z -12             artillery at the tail
Silhouette: long and thin, armour leading beside the Vanguard, infantry as two
running files on the flanks, soft units interior.

LINE form:
  front  one rank, spacingX 2.6, z +4, bowed FORWARD by lineArc ~1.5m at centre
  flank  becomes the WINGS: files continue outward past the front rank's ends,
         two ranks at z +2 and z 0 (this is the staggered "Firing Line" from
         DATA_AND_BALANCE.md)
  center 2 ranks at z -6
  rear   2 ranks at z -14, wide spread (artillery needs line of sight and has a
         minimum range)

FRONTAGE GOVERNOR: maxFrontage = clamp(8 + 0.9*sqrt(count)*avgRadius*K, 20, 90).
When the line would exceed it, ADD RANKS, NOT FILES. Without this, 200 units
become a 200m wall the camera cannot frame and whose flanks never reach the
fight. Initial tuning.

RETREAT form (the doc is explicit: "do not simply reverse the march column"):
forward keeps pointing at the threat so units keep facing and firing; the anchor
ORIGIN translates backward with the Vanguard; front band's offset reduces so
armour falls back into the body; flank widens rearward to screen. Implement as
the third lerp target — it reuses the whole machinery.

Put the tunable numbers in src/data/formation.ts as a BandLayout table so they
can be tuned without touching logic. Mark them initial tuning.

--- FILL ORDER (fillOrder.ts) — why the army looks disciplined ---
bandFillOrder encodes DESIRABILITY, precomputed on layout rebuild. For front:
rank 0 first, and within a rank, centre file outward alternating (0, +1, -1,
+2, -2, ...).
Three consequences, all free:
  1. The line fills FROM THE MIDDLE OUTWARD — the single cheapest visual cue
     that reads as "military".
  2. Reinforcements from card call-downs slot into the INTERIOR, which matches
     the design intent that recovery feels powerful rather than like stragglers
     appearing at the edge.
  3. Slot identity is (band, fillOrderPosition), NOT geometry — so when the army
     grows, layout rebuild appends slots at the OUTSIDE of each band and every
     existing unit keeps its slot and does not move. Growth is append-only.
     This is why the army does not reshuffle every time a card grants +6
     riflemen.

--- ASSIGNMENT (assign.ts): banded, budgeted, greedy, hysteretic ---
Naive global assignment is what makes formations look wrong — Hungarian is
O(N^3), and nearest-slot-per-tick makes units swap slots every tick and visibly
vibrate. Instead:
 1. PARTITION BY BAND. A unit is only ever eligible for slots matching its
    UnitDef.formationBand. Five small independent problems, O(N) total.
 2. ON JOIN (spawn / call-down): take the first free slot in bandFillOrder.
 3. ON CASUALTY the slot frees. DO NOT immediately drag a distant unit into it.
    Each tick process at most SLOT_COMPACT_BUDGET = 8 free slots. For a free
    slot at fill-order position p, find the occupied slot with the LARGEST
    fill-order position in that band (the outermost/rearmost occupant) and move
    that unit in — ONLY IF its world distance to the target slot is under
    MAX_RESLOT_DIST (12m). Otherwise leave it free and retry next tick.
    The emergent behaviour is exactly the drill you want: THE LINE CLOSES
    INWARD FROM ITS ENDS, one or two men at a time. No teleports, no cross-field
    sprints, no holes that persist forever. This is ~25 lines and the
    highest-leverage code in the project.
 4. HYSTERESIS: a unit may not change slot more than once per RESLOT_COOLDOWN =
    20 ticks (1s). Kills all remaining oscillation.
 5. Layout rebuild triggers (NOT every tick): any band's count changed by >= 3
    since last rebuild, OR mode change, OR 40 ticks elapsed. Rebuild preserves
    occupancy BY FILL-ORDER POSITION.
Zero allocation throughout.

--- TESTS (tests/unit/formation.spec.ts) ---
  - Column layout matches a committed golden array for 20 units so an
    accidental layout regression fails loudly.
  - Line fills centre-outward: with 7 front units, assert occupied x positions
    are symmetric about centre and contiguous.
  - GROWTH IS APPEND-ONLY: with 20 units assigned, add 6 more; assert NOT ONE
    of the original 20 changed slot index. This is the property that stops the
    army reshuffling on every card.
  - ASSIGNMENT STABILITY: kill a unit 40m from another; assert the distant unit
    does NOT change slot (MAX_RESLOT_DIST respected).
  - CASUALTY COMPACTION: kill 5 units from the middle of a 30-unit line; step
    enough ticks; assert holes are filled from the OUTSIDE in, and that no unit
    moved more than MAX_RESLOT_DIST in one reassignment.
  - Hysteresis: a unit cannot change slot twice within 20 ticks.
  - Frontage governor: at 200 units the line adds ranks and total width stays
    under the cap.
  - deployT lerp: at deployT 0 slots equal column positions, at 1 equal line
    positions, and slot INDEX is unchanged throughout.
  - No allocation drift over 1200 ticks.`,
  },
  {
    key: 'formation-motion',
    prompt: `TASK: How units actually move to their slots, and the mode state machine. This
is the other half of "army, not boids".

OWN THESE FILES ONLY:
  src/sim/systems/formation.ts
  src/sim/systems/separation.ts
  src/sim/formation/transitions.ts
  tests/scenario/formation-motion.spec.ts

Coordinate with the layout agent: it owns src/sim/formation/{layout,fillOrder,
assign,state}.ts and src/data/formation.ts. Import from those; do not edit them.
If an interface you need is missing, code to what this brief describes and note
the assumption.

src/sim/step.ts already calls named functions for the 'formation', 'slotAssign'
and 'separation' phases. Slot into those call sites; keep step.ts edits to
import and call lines only.

--- MOVEMENT BLEND (in systems/formation.ts) ---
Per unit per tick:
  worldSlot = origin + rotate(slotLocal[slot], fwd)
  toSlot = worldSlot - pos;  d = |toSlot|
  if d > slotBreakDist(band):        // out of formation, catching up
      desired  = 0.85*norm(toSlot) + 0.15*flowField(pos)   // flow field is a
                                                            // stub for now:
                                                            // use march heading
      speedMul = min(1.25, 1 + (d - slotBreakDist)*0.05)
  else:
      w = smoothstep(settleEpsilon, slotBreakDist, d)
      desired  = w*norm(toSlot) + (1-w)*flowField(pos)
      speedMul = 1

THREE THINGS DO THE HEAVY LIFTING — get these right above all else:

1. THE SETTLE DEADZONE. Below settleEpsilon the slot force is EXACTLY ZERO, so
   units genuinely STOP. Without a deadzone every unit micro-jitters around its
   slot forever and the whole army shimmers — the most obvious "this feels
   cheap" tell there is. Per-unit settleEpsilon varies in [0.25, 0.6]m from the
   existing hash32 stagger so they do not all freeze on the same frame.

2. SEPARATION IS POSITIONAL, NOT STEERING (separation.ts). After integration,
   run 2 iterations over spatial-grid neighbours: for each overlapping pair push
   both apart by half the penetration, weighted by radius, CAPPED at
   0.35*radius per tick. Steering-based separation is the boids approach and
   produces oscillation and orbiting — fish behaviour. Position-based resolution
   produces units that firmly refuse to overlap and otherwise hold station.
   This single choice is most of the visual difference. Use the existing
   SpatialGrid.queryInto with a preallocated Int32Array.

3. COMMON FACING WHEN SETTLED. Heading turns toward the combat target if
   engaged, else toward formation.fwd. When in-slot and idle, EVERY unit faces
   formation-forward, so the line visibly DRESSES. One line of code, enormous
   payoff.

Stagger comes from the existing per-unit hash32 fields (accelMul, turnRateMul,
settleEpsilon, fireOffsetTicks) — near-synchrony that still reads as
disciplined, per docs/ARMY_AND_UNITS.md. Do not consume RNG for it.

AIR BAND EXCEPTION: same system, different constants. slotBreakDist 14m, a slow
orbital drift added to the slot local position, no participation in separation,
altitude applied in RENDER only. Do NOT build a second system for air.

--- MODE FSM (transitions.ts) ---
  COLUMN      --contact held 0.35s-->            DEPLOYING
  DEPLOYING   --deployT >= 1-->                  LINE
  LINE        --no contact 3.0s AND vanguard moving--> UNDEPLOYING --> COLUMN
  COLUMN/LINE --vanguard stationary 1.5s, no contact--> HOLD (spacing x0.85,
                                                       face fwd)
  LINE        --vanguard velocity . fwd < -0.5 for 0.6s--> RETREAT
contact = a hostile unit or armed structure within (maxWeaponRange + 8) of the
anchor origin, OR the Vanguard holds a marked target within 1.4x his range.
There are no enemies yet — implement the predicate against whatever hostile
query exists, and make it testable by injecting a contact position.

THE DEBOUNCE IS NOT OPTIONAL: 0.35s to enter, 3.0s to leave. Without asymmetric
debounce the army STROBES between column and line at the edge of contact range,
which looks worse than never deploying at all. This is the #1 failure mode of
the whole system — if the deploy ever reads badly, check this first.

deploySeconds = 1.6, eased with smoothstep on deployT. AUTONOMOUS_BUILD.md calls
the column-to-line transition "a marketing shot", so expose the easing curve and
duration as tunables in src/data/formation.ts, not as constants buried in code.

--- TESTS (tests/scenario/formation-motion.spec.ts) ---
  - 20 followers spawned scattered converge into column within N ticks and then
    HOLD STILL: assert total unit movement over the following 100 ticks is
    below a small epsilon. This is the anti-shimmer test and it matters most.
  - No overlaps: after settling, assert no two units are closer than the sum of
    their radii (minus a small tolerance).
  - Facing: when settled and idle, assert heading variance across the army is
    tiny — they dress the line.
  - Debounce: oscillate a contact in and out at 4Hz; assert mode does NOT
    change more than once, proving the asymmetric debounce holds.
  - Deploy: inject contact, assert mode goes COLUMN -> DEPLOYING -> LINE, that
    deployT rises monotonically, and that it takes ~1.6s not one tick.
  - Retreat: assert units keep facing the threat while the anchor moves back.
  - Determinism: identical world hash over 600 ticks for the same seed and
    scripted contact.
  - No allocation drift over 1200 ticks with 50 units.`,
  },
  {
    key: 'followers-and-gizmos',
    prompt: `TASK: Put followers in the world, and make the formation VISIBLE to a developer.
Without gizmos, neither a human nor an agent can tell from a screenshot whether
slot assignment is working, and the whole self-review loop is blind.

OWN THESE FILES ONLY:
  src/render/debug/SlotGizmo.ts
  src/render/debug/index.ts
  src/sim/scenario.ts        (extend only — keep existing scenarios working)
  src/app/scenes.ts          (register scenes only)
  tests/e2e/formation.spec.ts

SCENARIOS — extend src/sim/scenario.ts with:
  'followers-10'   (already exists — make sure it spawns 10 riflemen near the
                    Vanguard)
  'march-25'       25 mixed units spanning MULTIPLE bands: riflemen (flank),
                   rocket troopers (flank), battle tanks (front), artillery
                   (rear), repair drones (center). Even though combat does not
                   exist, exercising all five bands NOW is what proves the
                   layout code works across the whole roster.
  'column-to-line' same roster, plus a scripted contact source so the
                   deployment transition can be triggered deterministically for
                   screenshots and visual regression.
  'bench-100'      100 units, mixed bands, for perf measurement.
  'bench-200'      200 units.
Keep them data-shaped and deterministic from the seed.

Register these in src/app/scenes.ts with ready:true so they appear as live tiles
on /dev. Leave scenes whose milestone has not landed as ready:false.

SLOT GIZMO (src/render/debug/SlotGizmo.ts), shown only when ?debug=1:
  - every slot drawn as a ring, COLOURED BY BAND (front/flank/center/rear/air)
  - occupied slots filled, unoccupied slots hollow — so holes in the line are
    instantly visible
  - a line from each unit to its assigned slot
  - the anchor frame axes (origin, forward)
  - the contact radius as a circle
  - mode and deployT as readable text
Draw all rings with ONE InstancedMesh and all lines with ONE LineSegments
geometry whose position buffer you rewrite each frame — not one object per slot,
which at 200 units would cost more than the game.
Expose a toggle through the existing debug API pattern.

E2E (tests/e2e/formation.spec.ts): boot ?scene=march-25&debug=1, assert zero
console errors, assert unit count reaches 25, assert every unit gets a slot
(no unit has slot -1 after settling), and assert via window.__CQ that the
formation mode is COLUMN while marching.`,
  },
  {
    key: 'visual-pass',
    prompt: `TASK: Fix two concrete visual problems found by screenshotting the current
build, then verify by screenshotting again yourself.

OWN THESE FILES ONLY:
  src/render/scene/cityBlocks.ts
  src/render/scene/arena.ts
  src/render/scene/skyline.ts
  src/render/units/palette.ts
  src/render/CameraRig.ts

PROBLEM 1 — THE CITY LOOKS LIKE COLOURED SLABS, NOT A CITY.
Screenshots show buildings in saturated brown, olive green and mid blue lying
in flat arrangements. docs/VISUAL_STYLE.md is explicit: "player force uses a
unified saturated identity colour; CITY USES MORE MUTED INDUSTRIAL VALUES." The
saturated browns and greens fight the player's blue for attention and read as
random boxes rather than an industrial megacity.
Fix: pull the city palette toward desaturated concrete/steel/rust — narrow
value range, low saturation, with EMISSIVE used as the information channel
(window strips, warning lights, power conduits) since that is what the doc says
carries meaning. Keep the player blue as the only strongly saturated thing on
screen. Buildings should read through SILHOUETTE and MASS, not hue.

PROBLEM 2 — YOU CANNOT SEE THAT THE CITY CONTINUES.
docs/RENDERING_AND_WORLD_PRESENTATION.md section 13 is the project's own
acceptance test and the current build fails three of its points: "that target is
only one small piece of the city", "the city continues far beyond my current
fight", and understanding the immediate objective. Everything visible is ground
within about 150m; no skyline, no landmark, no horizon.

Diagnose before changing anything. The camera is pitch 42 degrees with a 55
degree vertical FOV, so the TOP of the frustum points (42 - 27.5) = 14.5 degrees
BELOW horizontal. Nothing above roughly the camera's own height is ever in
frame, at any distance — which is why the skyline you built is invisible. That
is geometry, not a bug in the skyline.
The doc permits "roughly the 35-50 degree family, not a locked requirement".
Consider: a modest pitch reduction, a taller near-district in the 120-250m band
whose upper masses fall inside the frustum, long avenue sightlines that let the
eye run out to distance, and haze layering to separate depth. Do NOT abandon
the near-isometric read, and do NOT simply zoom out — the doc also says early
game should "feel intimate enough that the Vanguard matters physically", and he
is currently ONE unit.
Whatever you change, the acceptance test is what a SCREENSHOT communicates.

METHOD — this is not optional:
  1. cd ${REPO} && pnpm build && pnpm preview   (background it)
  2. node tools/shot.mjs artifacts/shots
  3. READ the PNGs with the Read tool and LOOK at them.
  4. Change something. Rebuild. Screenshot. Read again. Compare.
  Iterate until section 13 is genuinely satisfied. Do not report success on a
  change you did not visually verify.
  5. Check cost did not regress: node tools/perfprobe.mjs. Baseline is 60fps,
     1.4ms render cpu, ~30 draw calls. Staying near that matters — the skyline
     must be sold with silhouette and haze, not geometry.

Report the before/after draw-call and triangle counts, and describe honestly
what the final screenshot does and does not communicate.`,
  },
]

phase('Build')
log('Formation is the make-or-break system; two agents on it, plus followers/gizmos and a visual pass')

const built = await parallel(
  TASKS.map((t) => () =>
    agent(`${SHARED}\n\n${t.prompt}`, { label: `build:${t.key}`, phase: 'Build', schema: REPORT, effort: 'high' }),
  ),
)

const ctx = built
  .map((r, i) => `--- ${TASKS[i].key} ---\n${r ? r.summary : 'FAILED — returned nothing.'}${r && r.notes ? '\nnotes: ' + r.notes : ''}${r && r.assumptions && r.assumptions.length ? '\nassumed: ' + r.assumptions.join('; ') : ''}`)
  .join('\n\n')
log(`${built.filter(Boolean).length}/${TASKS.length} tracks complete`)

phase('Integrate')

const integ = await agent(
  `${SHARED}

TASK: Wire the formation system together so an army actually marches, and make
the whole repo green. You are the only agent running and may edit ANY file.

What the four tracks built:
${ctx}

DO:
1. Read the tracks' real source and reconcile interface drift between the two
   formation agents especially — they split layout from motion and will have
   made assumptions about each other.
2. Ensure src/sim/step.ts calls formation, slotAssign and separation in the
   documented phase order, and that the Vanguard still steers correctly (his
   movement must not regress — that is the feel everything inherits).
3. Make the InstancedUnitLayer render followers, not just the Vanguard: multiple
   role buckets, correct per-role silhouettes and palette.
4. Boot 'march-25' as a live scene and confirm 25 units actually form a column
   behind the Vanguard and follow him when he moves.
5. Wire the SlotGizmo behind ?debug=1.
6. Update public/dev/status.json for a NON-TECHNICAL owner. He is the visionary,
   not a developer. "Do the units look like a squad following you, or a crowd?"
   — not "verify slot assignment hysteresis".
7. Run each gate separately: pnpm typecheck; pnpm lint; pnpm test; pnpm build;
   pnpm test:e2e. Piping into tail masks exit codes — do not do that.
8. Measure: node tools/perfprobe.mjs "http://localhost:4173/?scene=bench-200&debug=1" 8
   Report real numbers at 200 units. Baseline at 1 unit was 60fps / 1.4ms.

Report honestly. Do not claim checksPassed unless you saw every gate pass.`,
  { label: 'integrate', phase: 'Integrate', schema: REPORT, effort: 'high' },
)

phase('Judge')

const CRIT = {
  type: 'object',
  additionalProperties: false,
  required: ['verdict', 'issues'],
  properties: {
    verdict: { enum: ['reads-as-army', 'reads-as-blob'] },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['severity', 'what', 'why'],
        properties: {
          severity: { enum: ['blocking', 'notable', 'minor'] },
          what: { type: 'string' },
          why: { type: 'string' },
        },
      },
    },
    summary: { type: 'string' },
  },
}

const critique = await agent(
  `PROJECT: ConquerRTS at ${REPO}, branch feat/m2-vanguard.

You are judging the single question this milestone exists to answer:
DOES THE FORCE READ AS A DISCIPLINED ARMY, OR AS A SWARM FOLLOWING A CURSOR?

AGENTS.md section 3: "The army must form and deploy like an army, not boids
following a cursor." AUTONOMOUS_BUILD.md Gate A passes only if "screenshots or
video read as intentional formation rather than a flock".

METHOD:
1. cd ${REPO} && pnpm build && pnpm preview   (background it)
2. Capture the marching column, with and without gizmos:
     node tools/shot.mjs artifacts/judge "/?scene=march-25&debug=1"
     node tools/shot.mjs artifacts/judge "/?scene=march-25"
   and the deployment transition:
     node tools/shot.mjs artifacts/judge "/?scene=column-to-line&debug=1"
3. Also capture a SEQUENCE during deployment so you can see the transition, not
   just its endpoints — write a short Playwright script INSIDE the repo (so
   module resolution works), take frames ~250ms apart across the deploy, and
   DELETE the script when done. Do not leave scratch files in the repo.
4. READ every PNG with the Read tool and actually look at them.

JUDGE:
  - Marching: is it a COLUMN — long, thin, ordered — or a clump? Are armour,
    infantry, support and artillery in sensibly different places, or mixed?
  - Are units evenly spaced, or overlapping/clipping?
  - When settled, do they face a COMMON DIRECTION, or point randomly?
  - Deployment: does the column visibly WIDEN into a line? Does it read as a
    manoeuvre a commander ordered, or as a crowd spreading out?
  - Does the line fill from the middle outward?
  - Any shimmer, jitter, orbiting, or vibration around slots?
  - With gizmos on: is every unit actually near its assigned slot, or are there
    long lines from units to distant slots (which means assignment is thrashing)?

Be harsh and specific. "It renders" is not the bar. The bar is that a stranger
looking at the screenshot says "that's an army". If something is wrong, name the
likely cause. If it genuinely reads as an army, say so plainly — do not invent
problems.`,
  { label: 'army critique', phase: 'Judge', schema: CRIT, effort: 'high' },
)

const blocking = ((critique && critique.issues) || []).filter((i) => i.severity === 'blocking')
log(`Critique: ${critique ? critique.verdict : 'none'}, ${blocking.length} blocking`)

let fix = null
if (blocking.length) {
  phase('Integrate')
  fix = await agent(
    `${SHARED}

TASK: Fix blocking problems found by looking at actual screenshots of the army.
You may edit any file; you are the only agent running.

VERDICT: ${critique.verdict}
SUMMARY: ${critique.summary}

BLOCKING:
${blocking.map((b, i) => `${i + 1}. ${b.what}\n   WHY IT MATTERS: ${b.why}`).join('\n\n')}

Likely causes, in the order they are usually responsible:
  - Strobing between column and line -> the asymmetric contact debounce
    (0.35s in, 3.0s out) is not holding.
  - Shimmer or vibration at rest -> the settle deadzone is missing or too small,
    or separation is steering-based rather than positional.
  - Units clumping or overlapping -> positional separation not running, or its
    per-tick correction cap is too low to resolve penetration.
  - Army reshuffling on growth -> slot identity is geometric rather than
    (band, fillOrderPosition).
  - Pinwheeling on turns -> forward is instantaneous velocity rather than
    smoothed heading.

Fix the cause. Re-capture screenshots, READ them yourself, and confirm the
problem is actually gone — never report a visual fix you did not visually
verify. Then run every gate separately and report the real state.`,
    { label: 'army repair', phase: 'Integrate', schema: REPORT, effort: 'high' },
  )
}

return {
  tracks: built.map((r, i) => ({ key: TASKS[i].key, ok: !!r, files: r ? r.filesWritten : [] })),
  integration: integ ? { summary: integ.summary, passed: integ.checksPassed, notes: integ.notes } : null,
  critique: critique ? { verdict: critique.verdict, summary: critique.summary, issues: critique.issues } : null,
  repair: fix ? { summary: fix.summary, passed: fix.checksPassed } : null,
}
