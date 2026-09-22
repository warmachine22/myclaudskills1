export const meta = {
  name: 'zen-racer-feel-graphics',
  description: 'Finish the drift tuning and polish the graphics on the 3km world',
  phases: [{ title: 'Refine', detail: 'drift speed retention, and a graphics polish pass' }],
}

const ROOT = 'C:/Users/mark5/Desktop/claudcodechat/zen-racer'

const PRE = `You are refining "Zen Racer" v2, an isometric package-delivery racing game
(three.js r170 + Rapier 0.14 + Vite). PROJECT ROOT: ${ROOT}

READ FIRST: ${ROOT}/WORLD_V2.md, ${ROOT}/PROGRESS.md, ${ROOT}/src/core/palette.js

STATE: the 3 km world is BUILT AND VERIFIED. 744 road nodes / 778 edges, a road hierarchy
(artery 7.0 m / street 5.0 / lane 3.2 half-widths via edge.width, edge.kind), 12 named POIs with
bespoke landmark buildings, 186 m of elevation, a lake, seeded weather (window.__zr.weather with
.kind and .gripScale), streamed instanced props. Verified passing: boot (4 seeds, zero console
errors), perf (101 draw calls / 77k tris at gameplay zoom), mission (full pickup->delivery pays
out), determinism, stability, audio, controls, physics (0-100 in 5.55 s, braking 90.7->3.7 km/h
in 2 s, steering correct).

=== VERIFY, DO NOT GUESS ===
A dev server is ALREADY RUNNING at http://127.0.0.1:5183. Do not start another.
  cd ${ROOT}
  python tools/verify.py --list ; python tools/verify.py --only <check>
  python tools/shot.py --seed pinned-1 -o shots/x.png -w 1280 -H 720 --drive 2 --keys up
  python tools/shot.py --seed pinned-1 --eval "<js>" / --pre-eval "<js>" -o shots/x.png
  python tools/gallery.py --set places
Screenshots land in shots/ and you can Read them back as images. LOOK at them.

CRITICAL: headless software rendering runs the rAF loop at a few fps, so you CANNOT judge motion
by watching. Step physics by hand (set g.running=false first, which also stops the camera being
snatched back):
  g.running=false;
  for(let i=0;i<300;i++){ g.vehicle.preStep(1/60,{throttle:1,brake:0,steer:0,handbrake:false},{grip:1});
                          g.physicsWorld.step(); g.vehicle.postStep(1/60); }
Kill stray headless_shell processes between timed-out Playwright runs.

HEADING CONVENTION (this cost a lot of time, do not reintroduce it): the car's forward is -Z and
placement applies a pure Y rotation, so a body rotated by h points along (-sin h, -cos h).
Facing world direction (dx,dz) therefore requires atan2(-dx,-dz), NOT atan2(dx,-dz).

=== HARD RULES ===
- No external assets, no CDN, no network. Everything generated in code.
- Colours from src/core/palette.js.
- Edit ONLY your assigned files. main.js, index.html, styles.css, tools/ and docs are the
  integrator's; every other src file belongs to another slice.
- Seeded determinism: use the passed rng, never Math.random().
- 60 fps on integrated graphics at 1280x720. Do not regress the perf check.
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
    measurements: { type: 'string', description: 'before/after numbers proving the change' },
    verified: { type: 'boolean' },
    risks: { type: 'string' },
  },
}

phase('Refine')

const out = await parallel([
  () => agent(`${PRE}

YOU OWN: src/vehicle/vehicle.js

The drift finally WORKS and you are finishing it. Measured now by
\`python tools/verify.py --only drift\` (seed pinned-1, on a 1020 m straight run):

  thr 0.6  cs -0.25: held 1.67s peak 137.8deg exit  0.4 km/h (0.01 retained, 0.00s airborne)
  thr 0.6  cs -0.45: held 2.37s peak  67.4deg exit 25.7 km/h (0.31 retained, 0.05s airborne)
  thr 0.6  cs -0.70: held 2.13s peak 114.1deg exit  0.5 km/h (0.01 retained, 0.00s airborne)
  thr 0.85 cs -0.25: held 2.62s peak  66.0deg exit 27.5 km/h (0.34 retained, 0.03s airborne)
  thr 0.85 cs -0.45: held 2.80s peak  67.7deg exit 13.6 km/h (0.17 retained, 0.00s airborne)
  thr 0.85 cs -0.70: held 3.00s peak  68.8deg exit 18.3 km/h (0.22 retained, 0.00s airborne)
  thr 1.0  cs -0.25: held 2.97s peak  66.0deg exit 16.9 km/h (0.21 retained, 0.05s airborne)
  thr 1.0  cs -0.45: held 2.93s peak  67.7deg exit 12.5 km/h (0.15 retained, 0.00s airborne)
  thr 1.0  cs -0.70: held 2.77s peak  68.9deg exit 20.5 km/h (0.25 retained, 0.00s airborne)

That is 7/9 sustaining a 2s+ slide with airborne time essentially eliminated -- a huge
improvement on 0/9. TWO PROBLEMS REMAIN, and the check still fails on both:

1. SPEED RETENTION IS TOO LOW: best is 0.34, the target is >=0.45. Look at the peak slip
   column -- almost everything pegs at 66-69 deg. Something is holding the car at ~67 deg, and a
   67 deg attitude is enormous: the car is nearly sideways, so it is acting as an airbrake and
   scrubbing all its speed. A real, satisfying drift sits around 30-45 deg. Find whatever is
   targeting/clamping near 67 (there is an HB_YAW_TARGET-style governor in the file) and bring
   the sustained attitude down into the 30-45 band. Holding a TIGHTER angle should both feel
   better and retain far more speed. Do not achieve this by killing the slide -- 'held' must stay
   >=2s for most inputs.

2. TWO LOW-THROTTLE INPUTS STILL SPIN: thr0.6/cs-0.25 hits 137.8 deg and thr0.6/cs-0.70 hits
   114.1 deg, both ending at ~0.5 km/h. Past 80 deg the car is spinning, not drifting. Note the
   pattern: it is the LOW throttle cases that spin, and the mid countersteer (-0.45) survives.
   That suggests throttle is currently doing the stabilising and countersteer authority is too
   weak at high slip. More countersteer must measurably REDUCE yaw rate at every throttle level.

TARGETS (the check enforces all of these):
  - >=3 of 9 inputs sustain 20-50 deg slip for >=2 s  (you are already at 7/9 for 20-75)
  - peak slip under ~70 deg on every input, none past 80
  - best drift retains >=45% of entry speed
  - zero airborne time on flat road (already achieved -- do not regress it)

Research constraints from WORLD_V2.md section 6, which Mark asked for specifically:
  - the handbrake must break the rears on the SAME FRAME -- latency is the genre's biggest
    complaint. Verify there is no ramp on the handbrake path.
  - counter-steer assist must stay SUBTLE and toggleable; too much "destroys the feeling".
  - reference feel: art of rally / Absolute Drift -- real inertia and mass, forgiving braking.
  - Mark: "should not understeer or oversteer", "handbrake must give a good feeling",
    arcade/sim blend is explicitly fine.

DO NOT touch _placeOnGround / _groundY / RIDE_HEIGHT or the queryPipeline priming in _groundY.

Report the full before/after sweep table from tools/verify.py --only drift. Also confirm
tools/verify.py --only physics still passes (0-100 around 5.5 s, braking, steering sign).`,
    { label: 'drift-tune', phase: 'Refine', schema: SCHEMA }),

  () => agent(`${PRE}

YOU OWN: src/core/engine.js and src/core/palette.js

Mark's words: "Graphics needs improvement" and "The art style you're using is good, I just want
you to polish it up and clean it wherever you can." So: do NOT restyle. The golden-hour direction
is signed off and he likes it. Sharpen and clean what is there, and make it hold up on a world
that is now 9x larger with 186 m of elevation, a lake, and weather.

The lighting model was rebuilt in an earlier round and is sound -- three r155+ is physically lit,
so the sun is 8.6 against ~0.75 of total fill, exposure 0.90, cool blue fill against a warm key,
ACES, bloom threshold 1.25 against raw linear radiance on a HalfFloat target. Read the file and
understand that before changing any of it.

What to work on, in rough priority order:

1. LOOK AT IT FIRST, WIDELY. Run \`python tools/gallery.py\` and Read every contact sheet it
   produces (shots/gallery/_sheet_*.png). Also shoot the lake, a hilltop POI, a rural lane, and
   the town core. Write down what actually looks weak before you touch anything. The world
   changed underneath this lighting: it was tuned on a flat 1 km map and now has big elevation,
   water, and long sightlines.

2. AERIAL PERSPECTIVE AT 3 km. With 186 m of relief and long views, distance haze is what makes
   scale read. Check the fog band is doing useful work at wide zoom without fogging the car at
   gameplay zoom (remember the ortho camera sits a fixed distance back, so fog near/far are
   offset by CAM_DIST -- that offset already exists, do not break it).

3. SHADOWS. The shadow ortho is fitted per frame to the visible ground. On big slopes and at the
   lake shore, check for acne, peter-panning, and shadows popping as the fit changes. Long
   golden-hour shadows are the signature of this look -- they must be clean.

4. WATER. There is a lake now (scene object 'lake'). Make sure it reads as water from the
   isometric camera: a believable sky reflection, some specular sparkle, a soft shoreline rather
   than a hard geometric edge. Keep it cheap.

5. GENERAL CLEANLINESS: banding in the sky gradient, aliasing on road edges and building
   silhouettes, bloom fringing on lit windows, anything that reads as CG artefact rather than
   art direction. Confirm it still looks right in rain, snow and fog (set
   window.__zr.weather.kind is not enough -- reseed with different seeds until you get each
   condition, or read weather.js to find how it picks).

You may add PALETTE keys. Do not regress the perf check
(\`python tools/verify.py --only perf\`, currently 101 draw calls / 77k tris at gameplay zoom)
and do not break the occluder fade that props relies on (engine.applyOcclusionFade).

Deliver before/after screenshots for every change you make, and say plainly what you improved
and what you deliberately left alone.`,
    { label: 'graphics', phase: 'Refine', schema: SCHEMA }),
])

return out
