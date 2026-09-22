export const meta = {
  name: 'zen-racer-fix',
  description: 'Fix the uncontrollable drift, flat terrain, oversized route arrows and car rear quarter',
  phases: [{ title: 'Fix', detail: 'four targeted fixes against measured evidence' }],
}

const ROOT = 'C:/Users/mark5/Desktop/claudcodechat/zen-racer'

const PREAMBLE = `You are fixing one specific problem in "Zen Racer", a working isometric
package-delivery racing game (three.js r170 + Rapier 0.14 + Vite). PROJECT ROOT: ${ROOT}

The game boots, generates a seeded town, drives, and now looks good at golden hour. Read
${ROOT}/PROGRESS.md and ${ROOT}/CONTRACTS.md first. Colours live in src/core/palette.js.

=== VERIFY YOUR WORK, DO NOT GUESS ===
A dev server is ALREADY RUNNING at http://127.0.0.1:5183. Do not start another.

  cd ${ROOT}
  python tools/shot.py --seed pinned-1 -o shots/x.png -w 1280 -H 720 --drive 2 --keys up
  python tools/shot.py --seed pinned-1 --eval "<js>"                  # returns JSON
  python tools/shot.py --seed pinned-1 --pre-eval "<js>" -o shots/x.png  # run JS then shoot
  python tools/shot.py --seed pinned-1 --probe                        # telemetry
  python tools/shot.py --seed pinned-1 --console                      # console + page errors

Screenshots go to shots/ and you can Read them back as images. LOOK at them.
window.__zr exposes { engine, vehicle, roadNet, terrain, roads, props, missions, hud, THREE,
RAPIER, physicsWorld }.

CRITICAL HARNESS FACT: headless software rendering runs the requestAnimationFrame loop at only a
few fps, so the car barely moves during --drive and you CANNOT judge driving by watching. Step
physics by hand instead:
  g.running=false;
  for(let i=0;i<300;i++){ g.vehicle.preStep(1/60,{throttle:1,brake:0,steer:0,handbrake:false},{grip:1});
                          g.physicsWorld.step(); g.vehicle.postStep(1/60); }
Ready-made rigs live in ${ROOT}/tools/rigs/ (read its README). Run one with:
  python tools/shot.py --seed pinned-1 --eval "$(cat tools/rigs/drift-sweep.js)" --drive 1
If Playwright runs time out they leave headless_shell processes alive which starve later runs;
kill them between attempts.

=== HARD RULES ===
- No external assets, no CDN, no network. Everything generated in code.
- Edit ONLY the files you are given. Another agent owns the rest, and main.js, index.html,
  styles.css, tools/ and the docs are off limits.
- Keep seeded determinism (use the passed rng, never Math.random) and 60fps budget.
- Do not regress what works. In vehicle.js in particular, do NOT touch _placeOnGround/_groundY/
  RIDE_HEIGHT or the queryPipeline priming inside _groundY -- that fixed a bug where the car
  hovered out of suspension reach forever and is load-bearing.
- Verify with esbuild before finishing:
  node_modules/.bin/esbuild <files> --bundle --format=esm --outfile=NUL --external:three --external:three/* --external:@dimforge/*
- Do not git commit.`

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['files', 'summary', 'verified', 'risks'],
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
    measurements: { type: 'string', description: 'before/after numbers proving the fix' },
    verified: { type: 'boolean' },
    risks: { type: 'string' },
  },
}

const TASKS = [
  {
    label: 'drift',
    prompt: `${PREAMBLE}

YOU OWN: src/vehicle/vehicle.js

THIS IS THE MOST IMPORTANT FIX IN THE GAME. The handbrake does not produce a drift, it produces
a SPIN. Drifting is the core verb; right now it is a coin flip that always loses.

MEASURED EVIDENCE (from tools/rigs/drift-sweep.js, seed pinned-1). Standard entry: full throttle
to ~83 km/h, then steer=1 with handbrake for ~0.9 s, then hold with throttle and countersteer.
Sweeping throttle {0.6, 0.85, 1.0} x countersteer {-0.25, -0.45, -0.7}, EVERY combination ends
with the car stopped:

  throttle 0.85 / counter -0.25 -> peak slip angle 114.9 deg, ends 4.0 km/h
  throttle 0.85 / counter -0.45 -> peak 92.5 deg,  ends 0.2 km/h
  throttle 1.0  / counter -0.25 -> peak 109.2 deg, ends 0.5 km/h
  throttle 1.0  / counter -0.70 -> peak 89.6 deg,  ends 23.0 km/h
  (slip angle held above 20 deg for only ~0.8 s in every case, because the car blows straight
   past a drift into a spin and then scrubs to a standstill)

A single trace shows the entry is actually GOOD: rear wheel slip pegs at 1.0, skid marks lay
down, 83 -> 57 km/h, slip angle reaches -47 deg, yaw rate peaks at -2.51 rad/s. The initiation
is right. What is broken is everything after it: the rotation never stops building, the car
passes 90 deg (pointing backwards), and a sideways car is an airbrake so it bleeds to zero.

Note there is already an HB_YAW_TARGET governor (1.05 rad/s) in the file. Measured yaw hit
2.51 rad/s, so whatever it is doing, it is not holding. Work out why before changing it.

WHAT GOOD LOOKS LIKE, and you must hit these numbers with the sweep rig:
  - At least one throttle/countersteer combination sustains slip angle in the 20-50 deg band for
    2+ continuous seconds. Ideally most of the mid-range combinations do -- the player should be
    able to find it, not hunt for one magic input.
  - Peak slip angle during a normal handbrake turn stays under ~70 deg. Past ~80 deg is a spin.
  - Exit speed after a sustained drift should be a decent fraction of entry speed (say 45%+),
    not 0-4 km/h.
  - Countersteer must actually CATCH the slide -- more countersteer should reduce yaw rate.
    Verify that relationship holds; if more countersteer does nothing, the front tyres have no
    authority during the slide and that is your bug.
  - Do not fix it by making the car understeer or by removing the handbrake's bite. The entry
    must stay as satisfying as it is now.

Legitimate tools: cap or bleed yaw rate as a function of slip angle; restore rear grip promptly
when the handbrake releases; give the front tyres more lateral authority at high slip angle so
countersteer works; reduce the yaw moment at very high slip angle; add a modest self-aligning
torque that pulls the car back toward its velocity vector. Arcade racers all do some of this.
It must remain a physical-feeling car, not an on-rails cheat.

Also confirm skid marks/smoke still trigger (they did: marks went 0011 then 1111 during the
handbrake) and that a drift leaves visible marks -- screenshot one.

Report the full before/after sweep table. The numbers are the deliverable.`,
  },
  {
    label: 'terrain',
    prompt: `${PREAMBLE}

YOU OWN: src/world/terrain.js

The ground reads as a flat, muddy, untextured fill at gameplay zoom. Look at
shots/v2_zoom20.png -- large areas of uniform yellow-olive with nothing to read against. The
lighting slice already did what it could from colour and light and explicitly handed this back:
the fix belongs in the terrain mesh.

What to add:
  1. LOW-FREQUENCY MACRO VARIATION in the vertex colours at roughly 150-300 m scale, so different
     parts of the map read as different ground rather than one flat wash. Use the seeded noise
     that is already passed in.
  2. MID-FREQUENCY BREAKUP at ~15-40 m so there is something to read at gameplay zoom -- patchy
     grass, drier and greener areas, subtle mottling.
  3. GROUND CONTACT NEAR ROADS: dirt and gravel scuffing along the shoulders where the flatten
     band meets natural terrain, so roads look worn into the landscape instead of pasted on.
  4. SLOPE AND HEIGHT RESPONSE: rock on steep faces, drier grass on high exposed ground, richer
     green in valleys and hollows. Some of this exists; make it read clearly.
  5. If a tiling detail texture would help at close range, generate one procedurally (canvas,
     no files) and keep it subtle -- it must not tile visibly or turn into noise.

CONSTRAINTS: the car must remain the most saturated thing on screen -- keep the ground muted and
let it support the scene, do not make it a patchwork quilt. Take colours from PALETTE (you may
read it, you may NOT edit it -- use existing keys and blend between them). Keep the mesh vertex
layout EXACTLY matched to the Rapier heightfield indexing (column-major,
heights[j*(nrows+1)+i]) -- if you touch the height generation at all, re-verify that the physics
ground and visible ground still agree, or the car will float or sink. Safest is to change only
colours and material, not heights.

Verify with screenshots at gameplay zoom (viewSize 20), mid (50) and wide (130), in a green area
AND on a hillside. Show me it reads as ground.`,
  },
  {
    label: 'markers',
    prompt: `${PREAMBLE}

YOU OWN: src/game/missions.js

Two problems, one certain and one to check.

1. CERTAIN -- THE ROUTE CHEVRONS ARE ENORMOUS AT GAMEPLAY ZOOM. Look at shots/v2_game.png: at
   the normal resting framing (ortho viewSize 20) the blue route arrows are bigger than the car,
   several are on screen at once, and they clip the frame edges. They dominate the picture and
   look broken. In shots/look_after_town.png, taken zoomed out at viewSize 58, the same arrows
   read fine as a breadcrumb trail. So they are sized for a zoomed-out view and nobody checked
   them at the framing the game actually plays at.
   Fix so they read well at BOTH: gameplay framing (viewSize 20, the default at rest) and the
   flat-out framing (viewSize 40). Consider scaling with the camera's view size, thinning them
   out near the car, fading the nearest ones, or drawing fewer of them. The on-car objective
   arrow should stay clear and unambiguous. Do not remove route guidance -- it is genuinely
   useful, it is just far too big.

2. TO CHECK -- BEACON VISIBILITY AFTER THE LIGHTING REBUILD. The lighting slice changed the light
   scale substantially (sun intensity 3.1 -> 8.6, exposure 1.05 -> 0.90) and raised the bloom
   threshold 0.88 -> 1.25, and it flagged that it never got a mission beacon in frame to check.
   Bloom now compares against RAW LINEAR RADIANCE on a HalfFloat target, not a 0..1 value, so an
   emissive that used to glow may not any more. Verify the pickup and drop-off beacons still read
   strongly from a distance and up close, in sunlight and in shadow, and fix them if not.

Verify by screenshotting at viewSize 20, 40 and 58, with a beacon in frame. You can drive mission
state directly through window.__zr.missions in --pre-eval, and move the car with
window.__zr.vehicle.reset({x,y,z}, heading). Report the shot paths.`,
  },
  {
    label: 'carfix',
    prompt: `${PREAMBLE}

YOU OWN: src/vehicle/stiModel.js

The car was reauthored in the last round and is much better -- at gameplay distance it reads
clearly as a boxy late-90s rally sedan with the right cues. Up close it still has problems. Look
at shots/final_front34.png (and the other final_*.png shots) before you change anything.

What I can see at a front three-quarter view:
  1. THE REAR QUARTER IS PUFFY AND TOO TALL. Behind the C-pillar the body swells and the boot
     deck sits high and flat, so the back half reads more like a small pickup or a crossover than
     a compact saloon. The greenhouse looks small against it. This is the biggest silhouette
     problem -- fix the proportion of cabin to rear deck.
  2. THE WHEELS SIT BADLY IN THE ARCHES. The tyres look narrow and inset, with an odd gap between
     tyre and arch lip, and the front wheel in particular looks like it is floating rather than
     filling its arch. Check track width, tyre width, arch radius and ride height together
     (the chassis body rests 0.553 m above ground; wheel radius 0.315).
  3. THE PAINT READS FLAT. There is a clearcoat highlight on the roof but the flanks are a single
     even blue with no light running along them. A car body's appeal is almost entirely in how
     highlights travel down the shoulder line. Check the beltline crease is actually catching
     light, and tune metalness/roughness/clearcoat against the PMREM environment.
  4. No door shut lines are visible from this angle; panel separation would help it read as a
     built object.

Shoot it yourself from front three-quarter, side, rear three-quarter and rear, big in frame:
  python tools/shot.py --seed pinned-1 -o shots/cf_a.png -w 1280 -H 720 --drive 1 \\
    --pre-eval "const g=window.__zr,e=g.engine; e.viewSize=7; g.hud.setVisible(false); e.render(0.016);"
Change the angle between shots via e.yaw (then several e.render(0.016) calls).

Keep it an HOMAGE with no badging. Keep the body in the 2-4k triangle range. DO NOT change the
exported interface -- buildSTI({color}) -> { group, wheels:[FL,FR,RL,RR], setBrake, setReverse,
setSteer, MODEL_Y_OFFSET } -- vehicle.js depends on it exactly, and note vehicle.js already
composes steering into the wheel objects, so the model must NOT also apply steer to them
(applySteerToWheels stays false; that double-steer bug was fixed last round, do not reintroduce it).

Report measured bounding box, triangle count, and your shot paths.`,
  },
]

phase('Fix')
log('Four targeted fixes against measured evidence')

const results = await parallel(
  TASKS.map((t) => () => agent(t.prompt, { label: t.label, phase: 'Fix', schema: SCHEMA }))
)

return TASKS.map((t, i) => ({ slice: t.label, result: results[i] }))
