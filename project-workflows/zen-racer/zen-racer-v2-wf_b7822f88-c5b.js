export const meta = {
  name: 'zen-racer-v2',
  description: 'Build the 3km world: road hierarchy, POIs, lake, weather, feel and collision',
  phases: [
    { title: 'Core', detail: 'road network, terrain+lake, weather, driving feel' },
    { title: 'Populate', detail: 'POI buildings and the delivery loop over the new map' },
  ],
}

const ROOT = 'C:/Users/mark5/Desktop/claudcodechat/zen-racer'

const PRE = `You are building part of "Zen Racer" v2, an isometric package-delivery racing game
(three.js r170 + Rapier 0.14 + Vite). PROJECT ROOT: ${ROOT}

READ FIRST, ALL BINDING:
  ${ROOT}/WORLD_V2.md   <- the v2 spec. This is the job. Read it fully.
  ${ROOT}/CONTRACTS.md  <- module interfaces and conventions
  ${ROOT}/PROGRESS.md   <- decision log and hard-won bug post-mortems
  ${ROOT}/src/core/palette.js <- the ONLY place colours live

The game currently works at 1 km scale: it boots, drives, delivers, and looks good at golden
hour. v2 scales the world to 3 km and gives it structure and purpose. DO NOT rebuild what works.

=== VERIFY, DO NOT GUESS ===
A dev server is ALREADY RUNNING at http://127.0.0.1:5183. Do not start another.

  cd ${ROOT}
  python tools/shot.py --seed pinned-1 -o shots/x.png -w 1280 -H 720 --drive 2 --keys up
  python tools/shot.py --seed pinned-1 --eval "<js>"                    # returns JSON
  python tools/shot.py --seed pinned-1 --pre-eval "<js>" -o shots/x.png # run JS then shoot
  python tools/verify.py --list          # the check suite
  python tools/verify.py --only boot --only physics --only drift
  python tools/gallery.py --set places   # labelled contact sheets

Screenshots land in shots/ and you can Read them back as images. LOOK at them.
window.__zr exposes { engine, vehicle, roadNet, terrain, roads, props, missions, hud, weather,
THREE, RAPIER, physicsWorld }.

CRITICAL: headless software rendering runs the rAF loop at only a few fps, so the car barely
moves during --drive and you CANNOT judge driving by watching. Step physics by hand:
  g.running=false;
  for(let i=0;i<300;i++){ g.vehicle.preStep(1/60,{throttle:1,brake:0,steer:0,handbrake:false},{grip:1});
                          g.physicsWorld.step(); g.vehicle.postStep(1/60); }
Reusable rigs are in ${ROOT}/tools/rigs/ (read its README).
If Playwright runs time out they leave headless_shell processes alive which starve later runs;
kill them between attempts.

=== HARD RULES ===
- No external assets, no CDN, no network at runtime. Everything generated in code.
- Colours from src/core/palette.js. You may ADD keys if you own a file that needs one, but
  never hardcode a colour inline.
- Edit ONLY your assigned files. main.js, index.html, styles.css, tools/ and the docs are the
  integrator's. Another agent owns every other slice.
- Seeded determinism: use the passed rng, never Math.random(), or seeds stop reproducing.
- 60fps on integrated graphics at 1280x720 is a requirement, not an aspiration. At 9x the world
  area, culling and instancing are the whole game.
- Do NOT touch vehicle.js's _placeOnGround/_groundY/RIDE_HEIGHT or the queryPipeline priming
  inside _groundY unless you own vehicle.js -- that fixed a bug where the car hovered forever.
- Keep the graded road shoulder (verge lip <= 0.06 m). A taller lip exceeds the suspension's
  0.10 m droop travel and launches the car off the road. This was the root cause of the
  "drifting is a spin" bug.
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
    api: { type: 'string', description: 'exact exported surface, including anything you added' },
    measurements: { type: 'string', description: 'numbers proving it works' },
    verified: { type: 'boolean' },
    risks: { type: 'string', description: 'what the integrator and other slices must know' },
  },
}

phase('Core')
log('Phase 1: road network, terrain + lake, weather, driving feel')

const core = await parallel([
  () => agent(`${PRE}

YOU OWN: src/world/roadnet.js and src/world/roads.js

Build the v2 road network from WORLD_V2.md sections 1-3. This is the backbone of the whole
release -- terrain, props and missions all consume it, so the API contract matters as much as
the generation.

KEEP the entire existing exported surface working (nodes, edges, halfWidth, build, query,
distTo, heightAt, path, randomNode, farNode). Everything new is ADDITIVE: edge.kind, edge.width,
node.kind, roadNet.pois. If you rename or remove anything, four other modules break.

The structure to build:
  - A dense central town of 'street' edges (~700-900 m across) -- every pickup happens here.
  - 6-8 'artery' routes leaving town in different compass directions toward the map edge. These
    must CURVE: generate each as a polyline whose heading wanders under a bounded turn rate,
    subdivided into many short edges so it reads as a smooth sweeping road, not a straight line.
  - 'lane' branches off the arteries that wind out to the POIs, tighter and more technical.
  - 8-14 POIs per WORLD_V2.md section 3, spread across compass sectors AND terrain types, each
    at the END of a lane. Generate readable seeded names.
  - BFS-verify full connectivity including every POI. A POI you cannot drive to is a broken game.

roads.js must render the three widths correctly, keep the junction polygon-fan approach (do not
regress to overlapping quads -- that z-fights and puts a lip at every junction), give arteries
lane markings and lanes none, and still produce ONE merged trimesh collider.

Scale check: the spatial hash must stay O(1) at 3 km with far more edges -- terrain calls
query() a few hundred thousand times during worldgen. Measure and report worldgen time.

Report the full added API precisely -- other agents are coding against your description.`,
    { label: 'roadnet', phase: 'Core', schema: SCHEMA }),

  () => agent(`${PRE}

YOU OWN: src/world/terrain.js

Scale terrain to the 3 km world and give it real character. WORLD_V2.md sections 1 and 4.

Three things matter most:

1. PERFORMANCE AT 9x AREA. Keep exactly ONE Rapier heightfield collider for the whole map --
   do not chunk the collider. Chunk the VISUAL mesh into ~250 m tiles so three.js frustum-culls
   them; the ortho camera sees ~40 m at gameplay zoom so nearly every tile must be culled every
   frame. Give distant tiles a reduced-resolution LOD. The heightfield indexing is column-major,
   heights[j*(nrows+1)+i], and the visible mesh MUST be generated from the same loop or the car
   floats. Re-verify that physics ground and visible ground agree after your changes -- raycast
   down at many points and compare against terrain.heightAt.

2. ELEVATION WITH PURPOSE. Town sits low. Hills rise 60-120 m. At least one prominent ridge.
   Climbs should feel like climbs -- this is a core part of "each journey should feel
   challenging". Roads still get flattened toward, and you MUST keep the graded shoulder
   (hidden deep drop under the ribbon, rising to a <=0.06 m verge lip, flat drivable verge,
   then the natural blend). Read the current implementation before changing it: a taller lip
   exceeds the suspension's droop and launches the car, which is exactly the bug that made
   drifting impossible.

3. A LAKE. Carve a basin below a seeded water level, add a cheap animated water surface (no
   assets -- shader ripple/normal scroll is fine), and shoreline material where land meets water.
   Terrain under the water still needs a sane collider. Driving into the lake should be a
   recoverable mistake, not a crash.

Also carry forward the colour work already in the file (macro zones, mid-frequency breakup,
shoulder scuff, slope/height response) and make sure it still reads well at 3 km -- a bigger
map with one flat green fill would be worse than the small map.

The road network is being rewritten in parallel. Code against the API documented in WORLD_V2.md
section 2 (edge.kind, edge.width, roadNet.pois) and guard defensively so a missing new field
degrades instead of throwing.

Report: worldgen time, triangle counts at gameplay/wide zoom, physics-vs-visual agreement error,
and screenshots at several zooms including the lake and a hill.`,
    { label: 'terrain', phase: 'Core', schema: SCHEMA }),

  () => agent(`${PRE}

YOU OWN: src/world/weather.js (NEW FILE) and the weather hooks in src/core/engine.js

Build seeded per-run weather per WORLD_V2.md section 5. Mark asked specifically for snow and
rain. The weather is chosen once from the seed, so a seed always gives the same town AND the
same conditions.

Export exactly:
  export class Weather {
    constructor({ rng, scene, engine, palette })
    kind        // 'clear' | 'overcast' | 'rain' | 'snow' | 'fog'
    gripScale   // clear 1.0, rain ~0.75, snow ~0.55  (main.js multiplies ctx.grip by this)
    update(dt, carPos)
    dispose()
  }

Each condition must change the LOOK convincingly, not just add particles:
  - rain: falling particles, darker and shinier road, tyre spray, cooler lower-contrast light,
    shorter fog distance, duller sun
  - snow: slow drifting flakes, accumulation tint on upward-facing surfaces, bright flat light
  - fog: heavy aerial perspective, weakened sun disc
  - overcast / clear: the baseline golden hour already in engine.js

CRITICAL PERFORMANCE RULE: particles live in a bounded volume that follows the car and recycle
from a fixed pool. Never simulate weather across 3 km, never allocate per frame. One
InstancedMesh or Points object per effect.

You may edit engine.js ONLY for the hooks weather needs (sun/fog/exposure/ambient modulation and
whatever accessor you need). Do not restyle the lighting -- the golden-hour grade is signed off
and another agent's work depends on it. Keep every change additive and guarded so 'clear' is
byte-for-byte the current look.

Take screenshots of every condition at gameplay zoom and wide, and report the fps/triangle cost
of each versus clear.`,
    { label: 'weather', phase: 'Core', schema: SCHEMA }),

  () => agent(`${PRE}

YOU OWN: src/vehicle/vehicle.js

THE DRIVING IS WHAT MARK CARES ABOUT MOST. His words: "The driving must feel extremely
satisfying. You should not understeer or oversteer. The handbrake must give a good feeling.
It's OK to balance between arcade versus full physics." Read WORLD_V2.md section 6 -- it carries
research findings you must honour.

CURRENT MEASURED STATE (tools/verify.py --only drift, on the longest straight road):
  thr 0.6  cs -0.25: held 0.37s peak 35.4deg exit 61.0 km/h (0.69 retained, 1.02s AIRBORNE)
  thr 0.85 cs -0.45: held 0.42s peak 35.4deg exit 53.9 km/h (0.61 retained, 1.03s AIRBORNE)
  thr 1.0  cs -0.70: held 1.42s peak 36.1deg exit  9.1 km/h (0.10 retained, 1.03s AIRBORNE)
Every one of nine combinations spends ~1 second airborne. A separate finding: at 88 km/h a 35
degree drift moves the car sideways at ~14 m/s, which crosses the whole 10 m carriageway in
0.36 s -- so part of this is that the car runs out of road, and the map is being widened in
parallel. But the airborne time on a FLAT road is yours to eliminate.

TARGETS, enforced by tools/verify.py --only drift:
  - >=3 of 9 throttle x countersteer combinations sustain 20-50 deg slip for >=2 s
  - peak slip angle under ~70 deg (past 80 is a spin)
  - best drift retains >=45% of entry speed
  - ZERO airborne time during a normal handbrake turn on flat road
  - more countersteer must measurably REDUCE yaw rate

Research findings to apply:
  - HANDBRAKE LATENCY IS THE GENRE'S BIGGEST COMPLAINT. The rears must break traction on the
    SAME FRAME the button goes down. Check for any smoothing/ramp on the handbrake path and
    remove it.
  - COUNTER-STEER ASSIST IS CONTENTIOUS: it makes pad/keyboard drifting achievable, but players
    say too much "destroys the feeling". Implement it subtle and proportional to how far past
    the target slip angle the car is, and expose a toggle (default on) as this.assistEnabled.
  - Reference feel is art of rally / Absolute Drift: real inertia and mass, forgiving braking,
    arcade-accessible with genuine depth.

Neither understeer nor oversteer may dominate. Turn-in immediate but not twitchy; the car
rotates when asked but never snaps away without warning; a slide must always feel like the
player's.

ALSO YOURS: COLLISION RESPONSE (WORLD_V2.md section 7). Mark flagged collision as needing work.
Hitting a building must scrub speed and jolt, never wedge the car or fling it across the map.
Build a rig that drives into a building at speed and asserts the car ends outside the geometry,
with reduced speed and finite position, and never relies on the stuck-respawn safety net.

DO NOT touch _placeOnGround/_groundY/RIDE_HEIGHT or the queryPipeline priming -- load-bearing.

Report the full before/after drift sweep table plus your collision measurements. The numbers
are the deliverable.`,
    { label: 'feel', phase: 'Core', schema: SCHEMA }),
])

log('Phase 1 complete; populating the new map')
phase('Populate')

const populate = await parallel([
  () => agent(`${PRE}

YOU OWN: src/world/props.js

The road network now has a hierarchy (town streets, curving arteries, winding rural lanes) and
8-14 named POIs, and the world is 3 km across with hills and a lake. Populate it so it feels
like a place, and so 9x the area does not mean 9x the emptiness OR 9x the cost.

1. THE POIs ARE THE POINT. Each POI in roadNet.pois (kind: cottage, lakehouse, farm, quarry,
   lookout, chapel, depot) needs its own distinctive, recognisable building or small cluster --
   you should know where you are the moment you arrive. A hill cottage, a boathouse at the
   water's edge, a barn and silo, and so on. These are hand-felt landmarks, not another
   instanced box. They may be their own meshes rather than instances since there are few.

2. DENSITY GRADIENT ACROSS 3 km. Dense, taller, tight frontage in the town core; thinning along
   the arteries; sparse rural buildings, barns, fences and hedgerows along the lanes; wilderness
   between. Derive it from the road graph and edge.kind, not hardcoded positions.

3. PERFORMANCE IS THE HARD PART AT THIS SCALE. Instance everything repeated. Cull by distance
   or per-region so the whole 3 km of props is not submitted every frame -- the ortho camera
   sees ~40 m. Report draw calls and triangles at gameplay zoom; the budget is ~120 draw calls.

Keep: engine.applyOcclusionFade on building and tree materials (without it the car vanishes
behind geometry in isometric view), buildings collidable with colliders that MATCH what is
drawn, roadside furniture non-collidable so it cannot trap the car, seeded determinism, and the
existing shader window work. Handle sloped lots with a plinth/foundation rather than burying the
building (a previous version sank buildings up to 2.6 m into hillsides).

Screenshot every POI type and the density gradient, and report counts and costs.`,
    { label: 'props', phase: 'Populate', schema: SCHEMA }),

  () => agent(`${PRE}

YOU OWN: src/game/missions.js and src/game/minimap.js

Rebuild the delivery loop around the new map. Mark's ultimate goal, verbatim: "picking something
up in the city and then driving it off to a specific area within a time amount that's reasonable
to complete but challenging."

MISSIONS:
  - PICKUPS happen in the CENTRAL TOWN (nodes with kind 'town'). DROP-OFFS are the named POIs in
    roadNet.pois. That asymmetry is the whole game: leave the city, drive out to a real place.
  - Name the job after the POI and say something about it -- "Larch Cottage, up on the ridge".
    The player should form a mental map of the region over a session.
  - TIME BUDGETS from the A* path length, but now weighted by difficulty: lanes are slower than
    arteries, and climbing costs time. Use edge.kind, edge.width and POI elevation/difficulty.
    It must be "reasonable to complete but challenging" -- tight enough to be exciting,
    achievable enough not to feel unfair. Derive the pace from REAL MEASUREMENTS of how fast the
    car actually covers each road tier, not a guess: drive the rig and measure.
  - Payout scales with distance, difficulty and time remaining; streak multiplier for
    consecutive on-time runs.
  - Weather affects grip (window.__zr.weather.gripScale). If conditions are bad the budget must
    account for it, or every rainy run is an unfair loss.

MINIMAP at 3 km: it can no longer show the whole world usefully. Use a zoomed view around the
car that pans, with the objective clamped to the edge with a distance readout, plus the A* route
drawn. Distinguish the road tiers visually. Keep it cheap: pre-render static geometry once to an
offscreen canvas and blit, do not redraw 3 km of roads every frame. It must stay legible at
220 px and rotate correctly with the camera yaw.

Do not invent new DOM: index.html and styles.css are fixed. Use the existing element ids.

Verify a full pickup-to-delivery cycle end to end (python tools/verify.py --only mission) and
report real numbers: typical journey distance, time budget, and how much margin a good drive
leaves.`,
    { label: 'missions', phase: 'Populate', schema: SCHEMA }),
])

return { core, populate }
