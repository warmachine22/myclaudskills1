export const meta = {
  name: 'conquerrts-m2-vanguard',
  description: 'Make the Vanguard visible and controllable on iPad: instanced rendering, arena, touch controls, movement',
  phases: [
    { title: 'Build', detail: 'Render layer, arena, touch input, movement system — disjoint files' },
    { title: 'Integrate', detail: 'Wire it together, make it green, deploy' },
    { title: 'Look at it', detail: 'Screenshot and judge whether it reads correctly' },
  ],
}

const REPO = 'C:/Users/mark5/Desktop/ConquerRTS'

const SHARED = `
PROJECT: ConquerRTS, browser RTS roguelite at ${REPO}. Branch: feat/m2-vanguard.

THE MILESTONE: the owner opens a URL on his M4 iPad and controls a person
walking through a city. That is all M2 has to deliver — but it has to feel good,
and the architecture has to be the real one, because everything after this
plugs into it.

ALREADY BUILT AND WORKING — read before writing, build against, do NOT rewrite:
  src/sim/core/tick.ts     TICK_HZ=20, TICK_MS, TICK_DT, MAX_UNITS, MAX_SUPPLY
  src/sim/core/mathx.ts    sinT/cosT/atan2T (lookup tables), clamp, lerp,
                           smoothstep, approach, normalizeAngle,
                           shortestAngleDelta, dist/dist2/length/length2
  src/sim/core/rng.ts      sfc32, four named streams, hash32
  src/sim/core/soa.ts      SoaPool, generational handles, swap-remove
  src/sim/core/handle.ts   EntityHandle packing, NULL_HANDLE
  src/sim/spatial/grid.ts  SpatialGrid, allocation-free queryInto
  src/sim/commands.ts      SimCommand + CommandBuffer (moveTo/steer/markTarget…)
  src/sim/events.ts        EventRing (SoA, drop-and-count on overflow)
  src/sim/state/units.ts   UnitSoA — posX/posZ, posPrevX/posPrevZ, heading,
                           headingPrev, velX/velZ, hp, defIndex, faction,
                           per-unit stagger from hash32
  src/sim/state/world.ts   World, createWorld(scenario, seed)
  src/sim/state/hash.ts    hashWorld
  src/sim/step.ts          stepSim — fixed 17-phase system order, most stubs
  src/sim/scenario.ts      ScenarioDef, 'empty' / 'vanguard-only' / 'followers-10'
  src/data/**              16 units, 7 structures, 19 cards, id->index maps
  src/render/Renderer.ts   M0 shell: WebGL2, ground plane, grid, fog, camera
  src/ui/PerfHud.ts        frame-interval percentiles, render CPU, draw calls
  src/app/main.ts          20Hz accumulator loop + interpolation alpha, debug API
  src/app/scenes.ts        showcase scene registry

Current: typecheck, lint and 176 tests pass. Keep it that way.

READ FIRST (binding): AGENTS.md §3 §4 §8; docs/UX_AND_CONTROLS.md;
docs/RENDERING_AND_WORLD_PRESENTATION.md; docs/DECISION_LOG.md 2026-09-05.

HARD RULES inside src/sim/** and src/data/**:
  no 'three', no DOM, no Math.random/Date/performance, no transcendental Math
  (use mathx), no console.log, no per-tick allocation.
  Enforced by tests/determinism/boundary.spec.ts. Fix the source, never the test.

HARD RULES inside src/render/** and src/ui/**:
  READ simulation state, never mutate it. Player input becomes a SimCommand;
  nothing else crosses the boundary. No per-frame allocation in the draw path
  (no new THREE.Vector3 per unit per frame — hoist scratch objects to module or
  instance scope).

RENDERING TARGET (docs/RENDERING_AND_WORLD_PRESENTATION.md): stylized
low-to-medium-detail 3D, strong silhouettes, modular industrial masses, small
material palette, emissive used as information, aggressive LOD, haze for depth.
NOT AAA realism. The camera is high three-quarter / near-isometric, ~42 degrees.
A local facility must read as ONE objective inside a much larger city — never as
"the enemy base".

PERFORMANCE (AGENTS.md §4): 60fps on an M4 iPad. Use InstancedMesh per unit
type. Never one THREE.Object3D per simulated unit. Draw calls under ~100.

STYLE: match the existing files. Comment the non-obvious DECISION and its WHY.
Never write a comment narrating a change ("now uses X", "changed from Y") —
write for someone reading the file fresh who does not know a change happened.

TypeScript strict; noUncheckedIndexedAccess deliberately OFF. \`import type\` for
type-only imports.

BEFORE RETURNING run: cd ${REPO} && pnpm typecheck && pnpm lint && pnpm test
Do not return until it passes.

FILE OWNERSHIP IS STRICT. Other agents edit this repo concurrently. Touch ONLY
your listed files. Never package.json, configs, or another agent's files. If you
need something not yet written, code to the interface described and say so.
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
    key: 'units-render',
    prompt: `TASK: Instanced unit rendering with interpolation. This is the module every
later visual milestone scales through, so build it for 400 units even though M2
draws one.

OWN THESE FILES ONLY:
  src/render/units/InstancedUnitLayer.ts
  src/render/units/silhouettes.ts
  src/render/units/palette.ts
  src/render/interp.ts

silhouettes.ts — build low-poly geometry per unit ROLE, not per unit type:
infantry (upright narrow box + head mass), armour (wide low hull + turret box +
barrel), air (swept wedge), siege (hull + long raised barrel), support (small
box + dish), vanguard (infantry silhouette, larger, with a distinguishing
shoulder/backpack mass). Merge each into ONE BufferGeometry per role via
BufferGeometryUtils.mergeGeometries so a unit is a single instance, not a group.
Keep each under ~120 triangles. AGENTS.md forbids skinned animation in v1 —
these are rigid; life comes from motion and stagger, not deformation.

Silhouette is what carries readability after camera pullback
(RENDERING_AND_WORLD_PRESENTATION.md §9), so exaggerate proportions: make the
tank read as a tank from 60 metres up, not from 5.

palette.ts — player forces saturated and unified; city forces muted industrial
(VISUAL_STYLE.md). Export named colours plus a small emissive set for power and
warning states. Do not scatter hex literals through the render code.

InstancedUnitLayer.ts — one THREE.InstancedMesh per (role, faction) bucket,
allocated once at MAX capacity with count driven down to what is live.
  sync(world, alpha): read UnitSoA, lerp posPrev->pos and shortest-arc
  headingPrev->heading by alpha, compose the matrix, write into the instance
  buffer, set instanceMatrix.needsUpdate, set .count.
Hoist every THREE.Vector3/Quaternion/Matrix4/Euler to instance fields — a
per-unit allocation here is 400 objects per frame at 60fps and is exactly what
AGENTS.md §4 forbids.
Provide dispose(). Provide a way to report instance and triangle counts so the
perf HUD can show real numbers instead of zeros.

interp.ts — the small shared helpers: lerp for position, shortest-arc lerp for
heading (reuse mathx's shortestAngleDelta so render and sim agree on what
"shortest" means).

No tests required for pure rendering, but if you can assert something cheaply
in Node (e.g. geometry triangle counts stay under budget), add
tests/unit/silhouettes.spec.ts and own that file too.`,
  },
  {
    key: 'arena',
    prompt: `TASK: The world the player walks through. This carries the single most
important visual claim in the project: "this fight is a tiny piece of a vast
city."

OWN THESE FILES ONLY:
  src/render/scene/arena.ts
  src/render/scene/skyline.ts
  src/render/scene/lighting.ts
  src/render/scene/cityBlocks.ts

Read docs/RENDERING_AND_WORLD_PRESENTATION.md sections 4, 5, 6, 8 and 13 fully.
Section 13's acceptance test is your specification — an early screenshot must
communicate, with no explanation: I control this small force; I understand the
immediate target; that target is one small piece of the city; the city continues
far beyond my fight; this looks achievable in a browser, not prerendered.

cityBlocks.ts — a modular kit of building masses (base mass + roof profile +
stacks/vents/antenna variants) assembled from boxes, MERGED per city block into
one geometry so a block is 1-2 draw calls rather than 30. Deterministic layout
from a seed passed in (use the sim's Rng if convenient, or a local LCG — this is
render-side so purity does not apply, but a stable layout matters for visual
regression screenshots). Vary height and footprint so the skyline has rhythm.

arena.ts — a ~400x400m playable area with urban verticality per §8: raised
roadway, a canal or rail trench with bridges, retaining walls, ramps. NOT natural
canyons. Leave the centre open enough to move and fight in. Ground material
should read as industrial surface, not grass.

skyline.ts — the distant city. Very low-detail merged/instanced silhouettes
ringing the arena, emissive window strips, a few smoke plumes, one or two
landmark shapes tall enough to read as "the HQ is over there". This must be
CHEAP — a handful of draw calls total. Sell extent with silhouette and haze, not
geometry (§5).

lighting.ts — one dominant directional key plus hemisphere fill, and fog tuned
so the arena is clear and the skyline recedes into haze.
CRITICAL AND ALREADY LEARNED THE HARD WAY: Three's Lambert/Standard diffuse
divides by PI, so intensities that look right in older examples land about 3x
too dark. Existing Renderer.ts uses hemisphere 2.4 / directional 3.2 against a
0x28313c ground and reads correctly — start from those values. Also, fog near
plane must sit well beyond the camera-to-target distance (~93m at the current
rig) or it fogs the ground the player is looking at. It did, at 90.

Export a single buildArena(scene, seed) that assembles everything, and report
the resulting draw-call and triangle count in your summary.`,
  },
  {
    key: 'input',
    prompt: `TASK: Touch-first controls. docs/UX_AND_CONTROLS.md is binding — iPad landscape
is the primary target and desktop inherits, not the reverse.

OWN THESE FILES ONLY:
  src/input/PointerRouter.ts
  src/input/TouchSteer.ts
  src/input/TapTarget.ts
  src/input/CameraGesture.ts

Both control modes must exist; the doc is explicit that they serve different
emotional states — deliberate strategy versus panicked dodging:
  - HOLD AND DRAG anywhere on the field: a virtual thumbstick appears where the
    finger lands and steers the Vanguard by direction. Emit CMD.STEER with a
    NORMALIZED direction. Show the stick base and knob (the render/UI side may
    not exist yet — expose the stick state as plain data and let the integrator
    draw it).
  - TAP a point: emit CMD.MOVE_TO with world coordinates. You will need to
    unproject the screen point onto the ground plane (y=0) — implement that
    here, taking the camera as a parameter so this file stays free of scene
    knowledge.
  - TAP an enemy: emit CMD.MARK_TARGET. There are no enemies in M2; implement
    the hit-test hook and leave the target resolution to a callback the
    integrator wires up later.
  - TWO-FINGER DRAG: camera pan. PINCH: camera zoom. Both go through
    CameraGesture.ts and must NOT emit SimCommands — camera is a view concern,
    never simulation state.

PointerRouter.ts owns pointer event handling and decides which gesture a touch
belongs to. Use Pointer Events, not TouchEvent. Handle pointercancel (iPad
gestures steal pointers constantly and a dropped cancel leaves the player
walking forever). Set touch-action none is already done in CSS; do not fight it.

Requirements from the doc: minimum 44pt interactive targets; no reliance on
hover; nothing critical placed in accidental thumb-rest zones.
Latency matters more than smoothing here — do not add input lag for elegance.

Everything you emit must go through the existing CommandBuffer from
src/sim/commands.ts. Never mutate world state directly.

Add tests/unit/input.spec.ts (own it) covering the pure logic you can test
without a DOM: screen-to-ground unprojection given a known camera matrix,
steering vector normalization including the zero-length case, the dead zone,
and gesture classification (one pointer vs two).`,
  },
  {
    key: 'movement',
    prompt: `TASK: Make the Vanguard actually move, in the simulation. This is sim-side and
bound by the purity rules.

OWN THESE FILES ONLY:
  src/sim/systems/commands.ts
  src/sim/systems/movement.ts
  tests/scenario/movement.spec.ts

src/sim/step.ts already defines the 17-phase order and calls named functions;
read it and slot into the existing 'commands' and 'movement' phases. If those
are currently inline stubs in step.ts, extract them into your files and leave
step.ts importing them — coordinate by keeping step.ts's call sites identical.
(If editing step.ts is unavoidable, keep the diff to the import and call lines
only; the integrator will reconcile.)

commands.ts — drain the CommandBuffer into world intent:
  CMD.MOVE_TO   -> set moveTargetX/Z, clear steer intent
  CMD.STEER     -> set steerX/Z (already normalized), clear move target
  CMD.MARK_TARGET / CLEAR_MARK -> set/clear world.markedTarget with a decay
                   timer (the bias itself lands in a later milestone)
  CMD.CHOOSE_CARD / MARCH_TO -> documented stubs
Steering and a move target are mutually exclusive: a drag must immediately
override a tap destination, or the player fights their own previous input.

movement.ts — integrate the Vanguard using TICK_DT and mathx only:
  - accelerate toward desired direction, capped at the def's moveSpeed
  - turn toward travel direction at the def's turnRate using shortestAngleDelta
    and approach — the body should face where it is going, with a real turn, not
    an instant snap
  - arrive cleanly at a MOVE_TO destination: decelerate into it and STOP inside
    a small radius rather than orbiting or jittering. Jitter at the destination
    is the single most obvious "this feels cheap" tell.
  - write velX/velZ so the renderer and later systems can read motion
  - no allocation

Design intent, per AGENTS.md §8: the Vanguard is the steering wheel of the whole
army later. Movement must feel responsive NOW, because every formation behaviour
downstream inherits its feel.

tests/scenario/movement.spec.ts — deterministic, no rendering:
  - MOVE_TO drives the unit to the target and it comes to rest (velocity ~0,
    position within tolerance) and STAYS at rest for 100 further ticks.
  - STEER moves in the commanded direction at moveSpeed once up to speed.
  - A STEER command mid-MOVE_TO overrides it immediately.
  - Turn rate is respected: commanding a 180-degree reversal takes at least the
    number of ticks turnRate implies, and heading stays continuous (no snap).
  - Determinism: same seed and same scripted command sequence gives an identical
    world hash over 600 ticks.
  - No allocation drift over 1200 ticks.`,
  },
]

phase('Build')
log('Four independent tracks: unit rendering, the arena, touch input, movement')

const built = await parallel(
  TASKS.map((t) => () =>
    agent(`${SHARED}\n\n${t.prompt}`, { label: `build:${t.key}`, phase: 'Build', schema: REPORT }),
  ),
)

const ctx = built
  .map((r, i) => `--- ${TASKS[i].key} ---\n${r ? r.summary : 'FAILED — returned nothing; build it yourself to the spec.'}${r && r.notes ? '\nnotes: ' + r.notes : ''}${r && r.assumptions && r.assumptions.length ? '\nassumed: ' + r.assumptions.join('; ') : ''}`)
  .join('\n\n')

log(`${built.filter(Boolean).length}/${TASKS.length} tracks complete`)

phase('Integrate')

const integ = await agent(
  `${SHARED}

TASK: Wire M2 together into something the owner can open on his iPad and play
with. You are the only agent running and may edit ANY file.

What the four tracks built:
${ctx}

DO:
1. Read the four tracks' actual source. Reconcile interface drift between them.

2. Rewire src/render/Renderer.ts and src/app/main.ts into the real shape:
   - Renderer builds the arena (buildArena) and owns an InstancedUnitLayer.
   - Each frame: renderer.sync(world, alpha) then render. The alpha is already
     computed in main.ts's accumulator loop — use it, so motion is smooth at
     60fps despite a 20Hz simulation. Verify this visually: at 20Hz without
     interpolation, movement visibly stutters.
   - Camera FOLLOWS the Vanguard: smoothed, slightly leading his travel
     direction, holding the ~42 degree near-isometric pitch. Do not snap.
     Height should already scale with force footprint (one unit now, hundreds
     later) — put that hook in even if it barely moves yet.
   - PointerRouter is installed and emits into the CommandBuffer that stepSim
     drains. Draw the virtual thumbstick when a steer gesture is active.
   - The world boots the 'vanguard-only' scenario and the player controls him.

3. Perf HUD must show REAL numbers now: instances, triangles, draw calls, and
   the live unit count — not the zeros M0 hardcoded.

4. Register a 'vanguard-arena' scene in src/app/scenes.ts and mark it ready:true
   so it appears as a live tile on /dev. Mark 'march-25' etc still not ready.

5. Update public/dev/status.json for this milestone: what changed, known
   limitations, and 3-5 things worth judging as a human — phrased for a
   NON-TECHNICAL owner. He is the visionary, not a developer. Say things like
   "does walking feel responsive when you drag?" not "verify pointer event
   latency".

6. Run: pnpm typecheck && pnpm lint && pnpm test && pnpm build && pnpm test:e2e
   Fix everything. Then extend tests/e2e/ with a boot test for the new scene
   asserting zero console errors and that the Vanguard actually moves in
   response to a synthesized MOVE_TO command (assert via window.__CQ).

7. Capture screenshots with the existing tool so the next agent can see the
   result:  pnpm preview  (background), then
   node tools/shot.mjs artifacts/shots
   Report the draw-call and triangle counts you actually observed.

Report honestly what works and what does not. Do not claim checksPassed unless
you saw all five commands succeed.`,
  { label: 'integrate', phase: 'Integrate', schema: REPORT, effort: 'high' },
)

phase('Look at it')

const CRIT = {
  type: 'object',
  additionalProperties: false,
  required: ['verdict', 'issues'],
  properties: {
    verdict: { enum: ['ships', 'needs-work'] },
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

You are judging whether this milestone LOOKS right. You have vision — use it.

1. Start the app:  cd ${REPO} && pnpm build && pnpm preview   (background it)
2. Capture screenshots at iPad-landscape resolution:
     node tools/shot.mjs artifacts/shots
   and also capture the new scene directly, e.g.
     SHOT_BASE=http://localhost:4173 node tools/shot.mjs artifacts/shots "/?scene=vanguard-arena&debug=1"
3. READ the resulting PNG files with the Read tool and actually look at them.
   If a screenshot is black, near-black, or empty, that is a BLOCKING issue —
   investigate why (lighting intensity, fog near plane, camera aim, a silent
   WebGL error) and report the cause, not just the symptom.
4. Also check the browser console for errors via the E2E harness or
   pnpm exec playwright, and check the perf HUD numbers in the screenshot.

JUDGE AGAINST docs/RENDERING_AND_WORLD_PRESENTATION.md §13, which is the
project's own acceptance test:
  - Does the player read as a small figure in a large world?
  - Does the city continue visibly beyond the immediate area?
  - Is the camera a plausible near-isometric GAMEPLAY camera, not a cinematic
    or a top-down board?
  - Do silhouettes read at gameplay distance?
  - Does it look intentionally stylized rather than cheap or broken?
  - Draw calls under ~100? Frame time sane?

Be a harsh critic. "It renders" is not the bar; the bar is that a stranger
seeing this screenshot understands what the game is. Report concrete, specific
issues with their likely cause. If it genuinely looks right, say so — do not
invent problems.`,
  { label: 'visual critique', phase: 'Look at it', schema: CRIT, effort: 'high' },
)

const blocking = ((critique && critique.issues) || []).filter((i) => i.severity === 'blocking')
log(`Visual critique: ${critique ? critique.verdict : 'no result'}, ${blocking.length} blocking`)

let fix = null
if (blocking.length) {
  phase('Integrate')
  fix = await agent(
    `${SHARED}

TASK: Fix blocking visual problems found by looking at actual screenshots. You
may edit any file; you are the only agent running.

CRITIQUE SUMMARY: ${critique.summary}

BLOCKING:
${blocking.map((b, i) => `${i + 1}. ${b.what}\n   WHY IT MATTERS: ${b.why}`).join('\n\n')}

Fix the cause, not the symptom. Then re-capture screenshots, READ them yourself
with the Read tool, and confirm the problem is actually gone — do not assume a
code change fixed a visual bug you never re-verified.

Then run: pnpm typecheck && pnpm lint && pnpm test && pnpm build
Report what you changed and what the screenshots look like now.`,
    { label: 'visual repair', phase: 'Integrate', schema: REPORT, effort: 'high' },
  )
}

return {
  tracks: built.map((r, i) => ({ key: TASKS[i].key, ok: !!r, files: r ? r.filesWritten : [] })),
  integration: integ ? { summary: integ.summary, passed: integ.checksPassed, notes: integ.notes } : null,
  critique: critique ? { verdict: critique.verdict, summary: critique.summary, issues: critique.issues } : null,
  visualRepair: fix ? { summary: fix.summary, passed: fix.checksPassed } : null,
}
