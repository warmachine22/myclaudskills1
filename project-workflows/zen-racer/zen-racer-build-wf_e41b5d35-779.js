export const meta = {
  name: 'zen-racer-build',
  description: 'Build the Zen Racer game modules in parallel against a fixed contract',
  phases: [{ title: 'Build', detail: 'seven module owners build against CONTRACTS.md' }],
}

const ROOT = 'C:/Users/mark5/Desktop/claudcodechat/zen-racer'

const PREAMBLE = `You are building one slice of "Zen Racer", an isometric package-delivery racing game
running in the browser: three.js r170 + Rapier 0.14 physics + Vite 6.

PROJECT ROOT: ${ROOT}

BEFORE WRITING ANY CODE you MUST read these two files, they are binding:
  - ${ROOT}/CONTRACTS.md      (module interfaces, conventions, physics constants, gotchas)
  - ${ROOT}/src/core/palette.js  (the ONLY source of colours and world constants)

Also skim ${ROOT}/index.html so you know the DOM element ids that already exist.

ART DIRECTION (all visual work must serve this):
  "Golden hour in a Pacific-Northwest rally town." A low warm sun, long cool-blue shadows,
  warm haze on the horizon. The world is warm and slightly desaturated so the WR-Blue hero car
  reads as the most saturated thing on screen. Think Art of Rally / absolute drift crossed with
  Monument Valley's clarity: clean readable silhouettes, strong shadow shapes, no visual noise.
  Nothing muddy, nothing flat-shaded-grey, nothing default-three.js-looking.

HARD RULES:
  - No external assets. No CDN, no fetch, no image/model/audio files. Everything generated in code.
  - Never hardcode a colour. Import from src/core/palette.js.
  - ESM only. 'import * as THREE from "three"'. Addons from 'three/examples/jsm/...' NOT 'three/addons/...'.
  - Do NOT import Rapier. main.js imports it and passes RAPIER in.
  - Do NOT create or edit main.js, index.html, styles.css, palette.js, CONTRACTS.md, rng.js, noise.js,
    input.js, or any file outside the ones you are told to own. Another agent owns those.
  - Seeded determinism: world generation uses the passed-in rng, never Math.random().
  - Must hold 60fps on integrated graphics. Instance repeated geometry. Never allocate in a hot loop.
  - Write real, complete, working code. No TODOs, no placeholder stubs, no "left as an exercise".

WHEN DONE, verify your files parse and their imports resolve:
  cd ${ROOT} && node_modules/.bin/esbuild <each file you wrote> --bundle --format=esm --outfile=NUL --external:three --external:three/* --external:@dimforge/*
It must exit 0. Fix anything it reports. Then report back.`

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['files', 'summary', 'verified', 'risks'],
  properties: {
    files: { type: 'array', items: { type: 'string' }, description: 'files written' },
    summary: { type: 'string', description: 'what you built, 4-8 sentences' },
    verified: { type: 'boolean', description: 'did the esbuild check exit 0' },
    exports: { type: 'string', description: 'exact exported API you implemented' },
    risks: { type: 'string', description: 'anything the integrator must know: assumptions, things you could not test, deviations from CONTRACTS.md and why' },
  },
}

const TASKS = [
  {
    label: 'engine',
    prompt: `${PREAMBLE}

YOU OWN: src/core/engine.js  (the Engine class)

This module decides whether the game looks amazing or looks like a default three.js scene. Take it seriously.

Implement exactly the Engine class described in CONTRACTS.md. Key work:
  1. WebGLRenderer: antialias, ACESFilmicToneMapping, exposure ~1.05, SRGBColorSpace output,
     shadowMap PCFSoft, devicePixelRatio capped at 1.5. Detect WebGL2; degrade gracefully.
  2. Procedural sky: build a vertical gradient on a 2D canvas (zenith -> mid -> warm horizon ->
     ground bounce) with a soft sun disc glow bloomed into it at the sun azimuth. Use it as an
     equirect texture -> PMREMGenerator -> scene.environment AND scene.background. This env map is
     what makes the car paint look like paint, so get the gradient genuinely pretty.
  3. Lighting: warm low directional sun (long shadows), hemisphere fill, small ambient. Shadow
     camera is a tight ortho box recentred on the car each frame so 2048 texels stay dense.
     Tune bias/normalBias so there is no shadow acne and no peter-panning.
  4. Isometric OrthographicCamera. Elevation ~38-40deg. rotateView(dir) animates a 45deg yaw snap
     (ease it, do not jump). follow() smooth-damps to the car plus a velocity lookahead, and lerps
     the ortho view size from ~30 at rest to ~52 at speed.
  5. applyOcclusionFade(material): patch onBeforeCompile so fragments that lie between the camera
     and the car dither-discard. Maths: v = worldPos - uCarPos; t = dot(v, uCamFwd);
     if t < 0 (fragment nearer the camera than the car) and length(v - uCamFwd*t) < uFadeRadius,
     discard with a hashed/bayer dither ramp so it reads as a soft fade, not a hard hole.
     Share ONE set of uniforms (this.fadeUniforms) across every patched material and update them
     in follow(). This must work on InstancedMesh materials too.
  6. Bloom: EffectComposer + RenderPass + UnrealBloomPass + OutputPass on quality 'high'.
     Keep the threshold high (~0.85) so only lights/emissives bloom - do NOT wash the whole frame.
     Auto-downgrade quality if measured fps stays under ~45, and fall back to plain
     renderer.render() if the composer fails to construct for any reason. Never throw.
  7. resize() handling ortho frustum + composer + dpr correctly.

Expose this.quality and a small this.stats { fps } so main.js can show it.`,
  },
  {
    label: 'worldgen',
    prompt: `${PREAMBLE}

YOU OWN: src/world/roadnet.js and src/world/terrain.js and src/world/roads.js

This is the procedural world. It must be solid: the car drives on it, so geometry errors here
become gameplay bugs. Read the CONTRACTS.md sections for all three files very carefully,
especially the Rapier heightfield column-major layout note and the junction-fan note. Those two
are the classic ways this goes wrong.

roadnet.js: pure data + queries, no three.js. Jittered grid of nodes, pruned edges that keep the
graph connected (BFS-verify, re-add if it splits), node heights sampled from the terrain base
noise then relaxed so no edge exceeds WORLD.maxGrade. Uniform-grid spatial hash so query(x,z) is
O(1)-ish - it gets called ~200k times during worldgen. A* for path().

terrain.js: fbm hills ~18m amplitude. Flatten toward roads exactly as specified (snap to
roadHeight - 0.30 inside the carriageway, smoothstep back to natural over ~14m) so terrain can
never poke through the road ribbon. Vertex colours blended by height AND slope. The three.js mesh
vertex layout MUST match the Rapier heightfield indexing exactly - generate both from one loop so
they cannot disagree. Add a subtle tiling procedural detail texture so the ground is not flat
colour at close range.

roads.js: quad ribbons per edge, shortened at both ends, junctions filled with a proper polygon
fan sorted by angle so there is no step and no z-fighting. Lane markings (dashed centre, solid
edges) as separate raised geometry with polygonOffset. Shoulders/kerbs. One merged trimesh
collider for the whole network, friction 1.35.

Sanity-check your own work before finishing: write a tiny throwaway node script that builds a
RoadNet with a fake baseHeightFn, asserts the graph is connected, asserts every edge gradient is
under maxGrade, and asserts query() returns the same answer as a brute-force nearest-segment scan
for ~500 random points. Delete the throwaway script when it passes. Report the results.`,
  },
  {
    label: 'props',
    prompt: `${PREAMBLE}

YOU OWN: src/world/props.js

Set dressing. This is a large fraction of "does the world look amazing". A grid of grey boxes
would fail; make it feel like a real small town at golden hour.

Per CONTRACTS.md: buildings lining the streets from ONE InstancedMesh with per-instance colour,
trees from ONE InstancedMesh of a merged trunk+foliage geometry, lamp posts along the roads.
Buildings get cuboid fixed-body colliders; trees do not.

Push hard on these details, they are what sells it:
  - Buildings must vary believably: footprint, height, roof treatment. Give them a slightly
    inset roof slab in PALETTE.roofDark so they are not bare extrusions.
  - Procedural windows in the shader via onBeforeCompile. Derive each instance's world size from
    the instanceMatrix basis vector lengths (length(instanceMatrix[0].xyz) etc) so window tiling
    stays square no matter how the box is scaled. Vary lit vs dark windows with a stable hash of
    the instance id + window cell so it does not shimmer frame to frame. Lit windows use
    PALETTE.windowLit and should bloom.
  - Buildings sit ON the terrain: sample terrain height at the footprint and sink the base slightly
    so no building floats or hovers on a slope.
  - Trees: vary scale, rotation and foliage tint per instance from the seeded rng.
  - You MUST call engine.applyOcclusionFade(material) on the building AND tree materials, or the
    car will be invisible behind buildings in isometric view.

Return an update(dt, carPos) even if it only animates lamp glow, so main.js can call it safely.`,
  },
  {
    label: 'car-model',
    prompt: `${PREAMBLE}

YOU OWN: src/vehicle/stiModel.js

This is the hero asset. It is on screen 100% of the time and it is the single thing the player
looks at most. It has to look genuinely good, not like a programmer-art box car.

The brief: INSPIRED BY a 1998 Subaru Impreza WRX STi (GC8) - a recognisable homage, explicitly
NOT a replica and not badged. Capture the silhouette and the signature cues and it will read
instantly: boxy compact sedan, big rectangular bonnet scoop, tall pedestal rear wing, gold
multi-spoke wheels, WR-Blue paint, deep front bumper with round fog lights, side skirts, mud flaps.

THE CRITICAL TECHNIQUE (read the CONTRACTS.md section, then do this properly):
Do NOT stack boxes. Build the body by LOFTING cross-section rings along Z. Define ~24 stations
from the nose (z = -2.17) to the tail (z = +2.17). Each station is a closed outline in the XY
plane with: a floor, a lower body side, a hard BELTLINE CREASE, a tumblehome curve leaning into
the greenhouse, and a roof crown. Vary halfWidth / beltline height / roof height / top width per
station to sculpt bonnet -> raked windscreen -> roof -> fast rear glass -> boot. At the two axle
stations, inset the LOWER body inward below the arch line to carve wheel arches. Stitch the rings
into quads, cap nose and tail so it is watertight, and duplicate ring points at the beltline so
computeVertexNormals gives you a crisp crease there instead of a soft blob.

Then the glass: sub-select the SAME lofted surface by ring-index band and Z range, push it out
~4mm along the normal, and give it the dark glass material. That guarantees the windscreen, rear
screen and side glass fit the body exactly, and leaves the A/B/C pillars painted.

Then the details, each as its own mesh: bonnet scoop (with a dark recessed opening), pedestal rear
wing (uprights + blade + endplates), door mirrors on stalks, headlights and taillights with
emissive materials, grille, front lip, side skirts, mud flaps, exhaust tip, door shut lines,
door handles.

Wheels: return four Object3Ds in order FL, FR, RL, RR. Each = tyre (with a visible sidewall and
some tread suggestion) + gold multi-spoke rim (~16 spokes) + brake disc + red caliper. The vehicle
module positions and spins them, so build each wheel centred at its own origin with the axle
along X.

Materials: MeshPhysicalMaterial with clearcoat 1 for the paint so the PMREM env reads on the
panels as highlights running down the flanks. Get metalness/roughness right - this is what makes
it look like a car and not like plastic.

Budget ~2-4k triangles for the body. Do not go under; smooth shading needs the resolution.

VERIFY YOUR SILHOUETTE. Write a throwaway node script that imports your module with a three.js
stub if needed, or simpler: after building, compute and print the geometry bounding box and assert
it is close to 1.69 wide x 1.40 tall x 4.34 long, and assert the triangle count is in range.
Delete the throwaway when it passes. Report the numbers you measured.`,
  },
  {
    label: 'vehicle-physics',
    prompt: `${PREAMBLE}

YOU OWN: src/vehicle/vehicle.js

This module IS the game feel. If the driving is not fun, nothing else matters. Read the
CONTRACTS.md vehicle section - every constant in it is a considered starting point, use them.

Rapier's DynamicRayCastVehicleController is a port of Bullet's btRaycastVehicle. Two API facts
you must get right or nothing will work:
  - the forward-axis SETTER is named 'setIndexForwardAxis' (property assignment), while the
    GETTER is 'indexForwardAxis'. Set setIndexForwardAxis = 2 and indexUpAxis = 1.
  - car forward is -Z, so engine force must be NEGATED to drive forwards.
Useful readbacks that already exist: wheelHardPoint(i), wheelSuspensionLength(i), wheelRotation(i),
wheelSteering(i), wheelIsInContact(i), wheelForwardImpulse(i), wheelSideImpulse(i),
wheelContactPoint(i), currentVehicleSpeed(). Use wheelHardPoint + wheelSuspensionLength to place
the wheel meshes rather than recomputing the transform yourself.

Import buildSTI from './stiModel.js', add the group to the scene, and drive its wheels array.
Another agent is writing stiModel.js right now, so code against the documented interface:
  buildSTI({color}) -> { group, wheels:[FL,FR,RL,RR], setBrake(on), setReverse(on), setSteer(rad), MODEL_Y_OFFSET }
Guard defensively (optional chaining) so a missing helper cannot crash the frame loop.

Implement preStep/postStep exactly as the step order in CONTRACTS.md specifies - main.js owns
physicsWorld.step() between them.

Make it FUN, not merely correct:
  - AWD 40/60 split, torque curve that tapers to zero near 62 m/s.
  - Simulated 5-speed for rpm/gear (HUD + audio only, never gate physics on it). Make the shifts
    feel good: brief torque cut on upshift.
  - Handbrake must produce a controllable, catchable slide - heavy rear brake plus rear
    sideFrictionStiffness down to ~0.35. Weight transfer should make lift-off rotation work.
    Tune until you can hold a long drift with countersteer and throttle. This is the core verb.
  - Speed-sensitive steering with rate limiting so it is not twitchy at speed.
  - Mild per-axle anti-roll bar from the left/right suspension length delta, applied with
    applyImpulseAtPoint, so the car leans but does not tip.
  - Aero drag + downforce as impulses.
  - Auto-right after being upside down 2.5s; reset() snaps to the nearest road.

FX (pooled, zero per-frame allocation):
  - Skid marks: ribbon geometry laid down when a wheel exceeds a slip threshold, capped and
    recycled in a ring buffer. They should darken the road where you drift and fade out over time.
  - Tyre smoke on slip, dust puffs off-road, using instanced or pooled sprites.
  - Populate this.wheelSlip[4] each frame - audio and FX read it.

Expose speed, rpm, gear, position, quaternion, velocity, wheelSlip, airborne, body, controller.`,
  },
  {
    label: 'game-layer',
    prompt: `${PREAMBLE}

YOU OWN: src/game/missions.js, src/game/minimap.js, src/game/hud.js

The gameplay loop and everything the player reads. index.html already contains the DOM (read it) -
use the existing element ids, do not invent new markup or restyle anything.

missions.js - the delivery loop. Pickup node -> drop-off node, at least ~250m apart on the graph.
Time budget from the A* path length over a target average speed (~16 m/s) plus a buffer that
tightens as the streak grows. Payout scales with distance and time remaining, multiplied by streak.
Fire onPickup / onDeliver / onFail so main.js can toast and play a sound.
The beacon markers matter a lot: a vertical light column plus a rotating ring, animated, drawn so
they stay visible through fog and over geometry (depthTest off / high renderOrder) - in an
isometric view the player must never lose the objective. Pickup uses PALETTE.pickup, drop-off
PALETTE.dropoff. Add a floating arrow above the car that points at the current objective.

minimap.js - 2D canvas, 220x220. Draw the road network (roadNet.edges), the car as a triangle,
the objective as a pulsing dot, and a clamped edge arrow when the objective is off the minimap.
Rotate the whole map by the camera yaw so "up" always means "away from the camera". Draw the
route polyline from the A* path if missions exposes it. Keep it cheap: pre-render the static road
network once to an offscreen canvas and just blit + rotate it each frame.

hud.js - drive the existing DOM ids, and draw the circular rev counter into #dial with 2D canvas:
sweeping rpm arc, redline zone, gear letter, big digital speed. It should feel crisp and modern,
matching the CSS already in styles.css (read it for the palette and type). Include toast() with
the good/bad/info kinds the CSS already supports, and setVisible() for the H key.
Redraw the dial only when values actually change enough to matter - do not burn frame time.`,
  },
  {
    label: 'audio',
    prompt: `${PREAMBLE}

YOU OWN: src/audio/engineAudio.js

Pure WebAudio synthesis, no samples, no files. A flat-four boxer rumble that responds to rpm and
throttle and makes the car feel alive.

  - Oscillator stack: a few detuned saw/square partials at the firing frequency and its harmonics.
    A boxer's character comes from an uneven-sounding low-order beat - get some of that flavour
    with slight detune and a sub partial.
  - Lowpass filter whose cutoff and resonance track rpm and throttle (closed throttle = darker and
    quieter, on-throttle = brighter and louder). A WaveShaper for gentle saturation when loaded.
  - Filtered noise bed for induction/wind that scales with speed.
  - Tyre squeal: bandpass-filtered noise driven by the max of wheelSlip, with the band centre
    moving with slip so it is not a static beep.
  - Small turbo whoosh / blow-off flavour on throttle lift at high rpm is very welcome on this car.
  - A short landing thump when airborne goes false.

Requirements: start() must be called from a user gesture and must resume() the context. No clicks
or zipper noise - ramp every parameter with setTargetAtTime / linearRampToValueAtTime, never
assign .value directly during playback. Must be cheap (this runs alongside a 60fps renderer).
setMuted() and dispose() must be clean. If AudioContext is unavailable, degrade to a no-op that
never throws - the game must still run.

Also export a tiny sound-effect helper on the class for the game layer to call:
  ping(kind) where kind is 'pickup' | 'deliver' | 'fail' - short synthesised UI stingers,
  pleasant and non-annoying, matching the calm "zen" tone of the title.`,
  },
]

phase('Build')
log(`Building ${TASKS.length} module slices against CONTRACTS.md`)

const results = await parallel(
  TASKS.map((t) => () => agent(t.prompt, { label: t.label, phase: 'Build', schema: SCHEMA }))
)

const ok = results.filter(Boolean)
log(`${ok.length}/${TASKS.length} slices returned`)

return TASKS.map((t, i) => ({ slice: t.label, result: results[i] }))
