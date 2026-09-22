export const meta = {
  name: 'zen-racer-polish',
  description: 'Make Zen Racer look amazing and feel fun, with visual verification per slice',
  phases: [{ title: 'Polish', detail: 'five owners iterate against real screenshots' }],
}

const ROOT = 'C:/Users/mark5/Desktop/claudcodechat/zen-racer'

const PREAMBLE = `You are polishing "Zen Racer", an isometric package-delivery racing game
(three.js r170 + Rapier 0.14 + Vite). PROJECT ROOT: ${ROOT}

THE GAME ALREADY WORKS. It boots, generates a seeded town, and the car drives properly
(0-95 km/h in 5s, four wheels planted, gears shifting). Your job is NOT to rebuild it.
Your job is to make it look amazing and feel fun. Do not regress working behaviour.

READ FIRST (binding): ${ROOT}/CONTRACTS.md and ${ROOT}/src/core/palette.js and ${ROOT}/PROGRESS.md

=== HOW TO VERIFY (you MUST actually look at your work) ===
A dev server is ALREADY RUNNING at http://127.0.0.1:5183 -- do NOT start another one, the port
is taken. Use the Playwright harness (the Claude browser pane's screenshots are unreliable on
this machine, so always use this):

  cd ${ROOT}
  python tools/shot.py --seed pinned-1 -o shots/mine.png -w 1280 -H 720 --drive 2 --keys up
  python tools/shot.py --seed pinned-1 --probe                  # telemetry JSON
  python tools/shot.py --seed pinned-1 --console                # console + page errors
  python tools/shot.py --eval "<js>"                            # returns JSON from the page
  python tools/shot.py --pre-eval "<js>"  -o shots/x.png        # run JS, THEN screenshot

Screenshots land in shots/ and you can Read them back as images. LOOK AT THEM. Iterate.
Boot takes ~4s; keep --drive small (1-2) so iteration stays fast.
window.__zr exposes { engine, vehicle, roadNet, terrain, roads, props, missions, hud, THREE,
RAPIER, physicsWorld }. --pre-eval is how you move the camera somewhere interesting:

  --pre-eval "const g=window.__zr,e=g.engine; e.viewSize=90; g.hud.setVisible(false); e.render(0.016);"

NOTE: headless software rendering makes the requestAnimationFrame loop run at only a few fps,
so the car barely moves during --drive. That is a HARNESS artifact, not a bug. To exercise
physics deterministically, step it yourself in --eval:
  g.running=false;
  for(let i=0;i<300;i++){ g.vehicle.preStep(1/60,{throttle:1,brake:0,steer:0,handbrake:false},{grip:1});
                          g.physicsWorld.step(); g.vehicle.postStep(1/60); }

=== HARD RULES ===
- No external assets, no CDN, no network. Everything generated in code.
- Colours come from src/core/palette.js. Only the LOOK owner may edit that file; everyone else
  reads it and uses existing keys.
- Do NOT edit main.js, index.html, CONTRACTS.md, PROGRESS.md, tools/, or files owned by another
  slice. Stay strictly inside the files you are given.
- Keep 60fps on integrated graphics. Instance repeated geometry, never allocate per frame.
- Verify with esbuild before finishing:
  node_modules/.bin/esbuild <files> --bundle --format=esm --outfile=NUL --external:three --external:three/* --external:@dimforge/*
- Do not git commit; the integrator handles that.`

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['files', 'summary', 'verified', 'risks'],
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string', description: 'what you changed and why, 4-10 sentences' },
    verified: { type: 'boolean', description: 'esbuild clean AND you looked at screenshots' },
    screenshots: { type: 'string', description: 'paths of shots you captured and what each shows' },
    risks: { type: 'string', description: 'what the integrator must know: regressions, assumptions, anything you could not verify' },
  },
}

const TASKS = [
  {
    label: 'look',
    prompt: `${PREAMBLE}

YOU OWN: src/core/engine.js and src/core/palette.js

You are the art director. This is the highest-impact slice. I have looked at real screenshots
and here is exactly what is wrong right now:

1. THE SCENE READS AS OVERCAST DUSK, NOT GOLDEN HOUR. It is flat, greenish and murky. There is
   no warm directional light on surfaces, almost no contrast between lit and shadowed faces, and
   no colour separation between sunlight and skylight. This is the single biggest problem.
2. The sky, where visible past the terrain edge, is a flat pale grey wash. It should be a
   genuinely pretty golden-hour gradient - warm near the horizon, deeper blue at zenith - and
   it doubles as the PMREM environment, so making it beautiful also makes the car paint good.
3. Lit building windows blow out into white blobs. Bloom threshold and/or emissive strength is
   too hot for a daylit scene.
4. Terrain is a flat untextured mid-green over huge areas. It needs subtle variation so it does
   not read as a solid fill at distance. (You own the lighting and palette; the terrain MESH is
   owned by another slice, so achieve this through palette colour choices and lighting, and if
   you need a colour key that does not exist yet, ADD it to palette.js.)
5. When zoomed out, large hard-edged dark rectangles appear on the ground. Investigate: I believe
   this is the directional light's shadow camera being only ~46 m half-extent, so everything
   outside the shadow frustum edge-clamps and reads as shadowed. Fix it properly (size//fade the
   shadow frustum, or fade shadow influence to zero at its edge). It is visible in normal play too.

Deliver a scene that looks like a still from a good stylised driving game at golden hour:
warm key light, cool sky fill in the shadows, real contrast, saturated but not garish, clean
readable silhouettes. Tune exposure, sun vs fill ratio, sun colour and elevation, fog, bloom
threshold/strength, and the sky gradient together - they only work as a set.

Also confirm the ortho framing reads well (currently 21 m at rest, 38 m flat out) and adjust if
the car does not sit right in frame.

VERIFY BY LOOKING. Take before/after screenshots at several framings (close on the car, mid, and
a wide shot over a built-up area) and iterate until it genuinely looks good. Report the shot paths.`,
  },
  {
    label: 'car',
    prompt: `${PREAMBLE}

YOU OWN: src/vehicle/stiModel.js

The car is the hero asset and is on screen 100% of the time. At gameplay zoom it currently reads
as a plausible blue sedan with a wing and gold wheels - which is a good start - but nobody has
ever looked at it up close. Your job is to make it genuinely good from the isometric gameplay
distance AND hold up when the camera is closer.

First, LOOK AT IT. Frame it big and shoot from several angles:
  python tools/shot.py --seed pinned-1 -o shots/car_a.png -w 1280 -H 720 --drive 1 --keys up \\
    --pre-eval "const g=window.__zr,e=g.engine; e.viewSize=7; g.hud.setVisible(false); e.render(0.016);"
Rotate the view between shots with e.rotateView(1) plus several e.render() calls, or by setting
e.yaw directly, so you see the front three-quarter, the side, and the rear three-quarter.

Then fix what you find. Things to scrutinise specifically:
  - Silhouette: does it read as a late-90s boxy rally sedan, or has the loft gone lumpy? Check
    the beltline crease is crisp and the greenhouse tumblehome is right.
  - Do the wheel arches actually look like arches, and do the wheels sit in them correctly with
    no gap or intersection? Check ride height looks right (the chassis rests 0.553 m up).
  - Glass: does it fit the body, and do the A/B/C pillars read as body-coloured?
  - The signature cues must be unmistakable: bonnet scoop, tall pedestal wing, gold multi-spoke
    wheels, deep front bumper with fog lights, side skirts, mud flaps.
  - Materials: the paint should show a clearcoat highlight running down the flank from the PMREM
    environment. If it looks like flat plastic, fix metalness/roughness/clearcoat.
  - Lights: headlights and taillights should read as lit elements without blowing out.

It is an HOMAGE, not a replica, and carries no badging. Keep the body around 2-4k triangles;
add detail where it reads at gameplay distance, not where it does not.

Do not change the exported interface: buildSTI({color}) -> { group, wheels:[FL,FR,RL,RR],
setBrake, setReverse, setSteer, MODEL_Y_OFFSET }. vehicle.js depends on it exactly.
Report the measured bounding box and triangle count, and the shot paths.`,
  },
  {
    label: 'feel',
    prompt: `${PREAMBLE}

YOU OWN: src/vehicle/vehicle.js

The driving works and the numbers are already believable: 0-95.6 km/h in 5 s, four wheels in
contact, gears shifting 1-2-3, braking effective. Your job is to make it FUN, which is a
different thing from correct. This is the core verb of the game - everything else is scenery.

Do NOT regress what works. In particular do not touch the spawn/reset ground-snap logic
(_placeOnGround / _groundY / RIDE_HEIGHT) - that was a hard-won fix for a bug where the car
hovered out of suspension reach forever, and the query-pipeline priming inside _groundY is
load-bearing (Rapier only refreshes the query pipeline inside world.step()).

Tune by DETERMINISTIC SIMULATION, not by watching (headless rAF is too slow). Step the physics
yourself in --eval and measure. Build yourself a little test rig that reports, for a given
control input over N steps: speed curve, yaw rate, slip angle, lateral g, and whether the car
spun out. Then tune against it.

What "fun" means here, in priority order:
  1. A handbrake slide you can initiate, HOLD with countersteer and throttle, and cleanly exit.
     Right now this is unproven - my one test applied the handbrake from a standstill and it just
     stopped. Make a proper test: get to ~70 km/h, turn in, handbrake, then hold opposite lock and
     partial throttle, and measure whether the slide sustains or snaps. Tune rear
     sideFrictionStiffness, the handbrake brake force, weight transfer and steering rate until a
     drift is catchable rather than a coin flip.
  2. Turn-in should feel immediate but not twitchy. Check the speed-sensitive steering curve.
  3. Weight transfer you can feel: the car should squat under power, dive under braking, and roll
     in corners - without ever tipping over. Verify the anti-roll bar is doing something.
  4. Off-road (grip ~0.3) should feel loose and gravelly but recoverable, not instant death.
  5. Landings from jumps should settle, not pogo.

Also verify the FX actually work and look right: skid marks should appear where you drift and
recycle without leaking, tyre smoke on slip, dust off-road. Screenshot a drift to prove it.

Report the measured numbers from your test rig - before and after - so the tuning is legible.`,
  },
  {
    label: 'world',
    prompt: `${PREAMBLE}

YOU OWN: src/world/props.js and src/world/terrain.js

The world is currently too EMPTY and too UNIFORM. Real evidence from screenshots:
  - Long stretches of road have nothing beside them at all. You can drive for hundreds of metres
    past nothing but cone trees and the occasional lamp post.
  - There are only ~180 buildings across a 1 km town and they are spread evenly, so there is no
    sense of a town centre, no outskirts, no landmarks - everywhere looks the same.
  - Terrain is a flat mid-green over huge areas with no visible detail at gameplay distance.
  - Buildings on slopes sink up to 2.6 m into the ground (the base is set below the LOWEST
    footprint corner). On steep lots that swallows most of a low building. Handle slopes better -
    consider a foundation/plinth in PALETTE.concrete that fills the gap instead of burying the
    building, so it reads as built into the hillside rather than sunk in it.

Make the world worth driving through:
  1. DENSITY GRADIENT. Give the map a centre: dense, taller, tightly-packed frontage near the
     middle of the road network, thinning to sparse rural lots at the edges. Derive it from the
     road graph (node degree / distance to the network centroid), not from a hardcoded position.
  2. VARIETY. More building archetypes than "box with a roof": vary footprint aspect, height,
     roof style, colour grouping so neighbouring buildings feel related. A handful of larger
     landmark structures that are visible from a distance and help the player navigate.
  3. FILL THE GAPS. Fences or hedgerows along rural road edges, parked/static vehicles or crates
     in yards, hay bales, power poles - whatever suits the setting. Cheap, instanced, and it must
     never block the carriageway or trap the car.
  4. TERRAIN READABILITY. Vertex-colour and detail variation so ground reads as ground at
     gameplay distance: patchier grass, dirt/gravel scuffs near road shoulders, rock on steep
     slopes. Keep it subtle - the car must stay the most saturated thing on screen.

Keep the seeded determinism (only the passed rng), keep the occluder fade applied to building
and tree materials, keep buildings collidable and thin roadside props non-collidable, and keep
draw calls low - instance everything. Report before/after counts, draw calls and triangles from
--probe, and shot paths.`,
  },
  {
    label: 'game',
    prompt: `${PREAMBLE}

YOU OWN: src/game/missions.js, src/game/hud.js, src/game/minimap.js

The delivery loop runs: it picks a pickup and a drop-off, names them, counts down, and the HUD,
minimap and objective arrow all work. Now make the loop something a player actually wants to
repeat. Right now it is mechanically complete but emotionally flat.

Work on, in priority order:
  1. MOMENT-TO-MOMENT CLARITY. In an isometric view with a rotating camera the player must never
     wonder where to go. Check the beacon reads from far away and up close, the on-car arrow is
     unambiguous, and the minimap route is legible at 220px. Verify at several camera yaws -
     rotate the view with e.rotateView(1) and confirm the minimap and arrow stay correct.
  2. PACING. A flat "deliver, next job" treadmill is boring. Give the run an arc: escalating time
     pressure, a visible streak that means something, occasional higher-value rush jobs, and
     legible risk/reward. Time budgets come from the A* path length - make sure they are tight
     enough to be exciting but achievable, and verify with real numbers from the road graph rather
     than guessing.
  3. JUICE. The delivery moment should feel great: a satisfying beacon burst, a clear payout
     callout, a streak escalation. The near-miss of a timer running out should be tense - the HUD
     already has warn/crit states in the CSS, use them.
  4. FEEDBACK THE PLAYER CAN ACT ON. Show speed, gear and rpm clearly, and make the timer bar and
     distance readable at a glance while driving.

Do not invent new DOM: index.html and styles.css are fixed and owned by the integrator. Use the
existing element ids and CSS classes (read both files). You may draw freely inside the #dial and
#minimap canvases.

Verify by screenshotting the HUD at several states (fresh job, timer nearly out, delivery moment)
- you can drive the state directly through window.__zr.missions in --pre-eval. Report shot paths.`,
  },
]

phase('Polish')
log(`Polishing ${TASKS.length} slices with visual verification`)

const results = await parallel(
  TASKS.map((t) => () => agent(t.prompt, { label: t.label, phase: 'Polish', schema: SCHEMA }))
)

return TASKS.map((t, i) => ({ slice: t.label, result: results[i] }))
