export const meta = {
  name: 'zen-racer-v2-phase2',
  description: 'Populate the 3km world: POI landmarks, density gradient, city-to-POI delivery loop',
  phases: [{ title: 'Populate', detail: 'props and the delivery loop over the new map' }],
}

const ROOT = 'C:/Users/mark5/Desktop/claudcodechat/zen-racer'

const PRE = `You are building part of "Zen Racer" v2, an isometric package-delivery racing game
(three.js r170 + Rapier 0.14 + Vite). PROJECT ROOT: ${ROOT}

READ FIRST, ALL BINDING:
  ${ROOT}/WORLD_V2.md   <- the v2 spec. This is the job.
  ${ROOT}/CONTRACTS.md  <- module interfaces and conventions
  ${ROOT}/PROGRESS.md   <- decision log and hard-won bug post-mortems
  ${ROOT}/src/core/palette.js <- the ONLY place colours live

=== THE v2 WORLD IS ALREADY BUILT AND VERIFIED BOOTING ===
Phase 1 landed. Measured, on seed pinned-1:
  - 3 km world. 744 road nodes, 778 edges (v1 had 64/79).
  - Road hierarchy is LIVE: 332 'artery' edges, 312 'lane', 134 'street'.
    edge.kind is one of 'artery'|'street'|'lane'; edge.width is the per-edge HALF width
    and ranges 3.2 (lane) .. 7.0 (artery). roadNet.halfWidth is only the default.
  - node.kind is 'town' (100) | 'junction' (632) | 'poi' (12).
  - roadNet.pois has 12 entries: { i, name, kind, x, y, z, elevation, difficulty }.
    kind is one of cottage | lakehouse | farm | quarry | lookout | chapel | depot.
    Real examples: "Larch Lakehouse" (lakehouse, elev -32.7, difficulty 0.55),
    "Thistle Priory" (chapel), "Peregrine Cut" (quarry, elev +55.6, difficulty 0.65),
    "Stonecrop Lookout" (lookout, elev +55, difficulty 0.72), "Pike Cabin" (cottage).
  - Terrain relief is 186 m (-68.3 to +118.4). There is a lake (scene object named 'lake').
  - Terrain visual mesh is chunked into 144 tiles for frustum culling; ONE Rapier heightfield.
  - Weather exists and IS wired into main.js: window.__zr.weather with .kind
    ('clear'|'overcast'|'rain'|'snow'|'fog') and .gripScale (clear 1.0, rain ~0.75, snow ~0.55).
    main.js already multiplies ctx.grip by it.

Your slice is what is still v1 and does not yet understand any of the above.

=== VERIFY, DO NOT GUESS ===
A dev server is ALREADY RUNNING at http://127.0.0.1:5183. Do not start another.

  cd ${ROOT}
  python tools/shot.py --seed pinned-1 -o shots/x.png -w 1280 -H 720 --drive 2 --keys up
  python tools/shot.py --seed pinned-1 --eval "<js>"                    # returns JSON
  python tools/shot.py --seed pinned-1 --pre-eval "<js>" -o shots/x.png # run JS then shoot
  python tools/verify.py --only boot --only perf --only mission
  python tools/gallery.py --set places

Screenshots land in shots/ and you can Read them back as images. LOOK at them.
window.__zr exposes { engine, vehicle, roadNet, terrain, roads, props, missions, hud, weather,
THREE, RAPIER, physicsWorld }.

CRITICAL: headless software rendering runs the rAF loop at a few fps, so the car barely moves
during --drive and you CANNOT judge motion by watching. Step physics by hand:
  g.running=false;
  for(let i=0;i<300;i++){ g.vehicle.preStep(1/60,{throttle:1,brake:0,steer:0,handbrake:false},{grip:1});
                          g.physicsWorld.step(); g.vehicle.postStep(1/60); }
Rigs are in ${ROOT}/tools/rigs/. Kill stray headless_shell processes between timed-out runs.

=== HARD RULES ===
- No external assets, no CDN, no network at runtime. Everything generated in code.
- Colours from src/core/palette.js. Never hardcode a colour inline.
- Edit ONLY your assigned files. main.js, index.html, styles.css, tools/ and the docs belong to
  the integrator; every other src file belongs to another slice.
- Seeded determinism: use the passed rng, never Math.random().
- 60 fps on integrated graphics at 1280x720 is a requirement. At 9x the area, culling and
  instancing ARE the work.
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
    measurements: { type: 'string', description: 'real numbers: counts, draw calls, triangles, distances, times' },
    verified: { type: 'boolean' },
    risks: { type: 'string' },
  },
}

phase('Populate')
log('Phase 2: POI landmarks + density gradient, and the city-to-POI delivery loop')

const out = await parallel([
  () => agent(`${PRE}

YOU OWN: src/world/props.js

props.js is still v1: it walks edges assuming one uniform road width and scatters a flat
density of buildings. On the 3 km map that reads as a thin, even smear with nothing to aim for,
and the 12 POIs -- the whole point of the game now -- have NO buildings at all.

1. THE POIs ARE THE POINT. Every entry in roadNet.pois needs its own distinctive, recognisable
   place, so you know where you are the moment you arrive. A cottage on its hill, a boathouse at
   the water's edge with a jetty, a barn and silo, a quarry with cut faces and machinery, a
   chapel with a tower, a lookout on a ridge, a depot with loading bays. There are only 12, so
   these can be their own bespoke meshes rather than instances -- spend the geometry here,
   this is where the player arrives and it should feel like a destination.
   Use poi.kind to choose the archetype and poi.elevation/difficulty for flavour.
   Seat them properly on sloped ground with a plinth or foundation in PALETTE.concrete rather
   than burying them (an earlier version sank buildings up to 2.6 m into hillsides).

2. DENSITY GRADIENT ACROSS 3 km, derived from the road graph, not hardcoded positions:
   - dense, taller, tight frontage along 'street' edges (node.kind 'town')
   - thinning out along 'artery' edges
   - sparse rural buildings, barns, fences, hedgerows along 'lane' edges
   - wilderness between
   Use edge.kind and edge.width. Note edge.width is the HALF width and varies 3.2..7.0, so any
   setback you compute from the centreline must use it, or lane buildings will sit in the road
   and artery buildings will float far from it.

3. PERFORMANCE IS THE HARD PART AT 9x AREA. Instance everything repeated. Cull by distance or
   region so the whole 3 km of props is not submitted every frame -- the ortho camera sees ~40 m
   at gameplay zoom. Budget is ~120 draw calls. Report draw calls and triangles at gameplay
   zoom (viewSize 20), at speed (40) and wide (130), measured via renderer.info.

KEEP: engine.applyOcclusionFade on building and tree materials (without it the car disappears
behind geometry in isometric view), buildings collidable with colliders that MATCH what is
drawn, roadside furniture NON-collidable so it cannot trap the car, and the existing procedural
shader window work.

Screenshot every POI archetype and the density gradient (town core, artery, rural lane).
You can jump the camera to a POI with --pre-eval, e.g.
  const g=window.__zr,p=g.roadNet.pois[0]; g.vehicle.reset({x:p.x+18,y:p.y+4,z:p.z+18},0);
  g.engine.follow(g.vehicle.position,new g.THREE.Vector3(),1); g.engine.viewSize=40;
  g.hud.setVisible(false); for(let i=0;i<4;i++) g.engine.render(0.016);`,
    { label: 'props', phase: 'Populate', schema: SCHEMA }),

  () => agent(`${PRE}

YOU OWN: src/game/missions.js and src/game/minimap.js

Rebuild the delivery loop around the new map. Mark's ultimate goal, verbatim: "picking something
up in the city and then driving it off to a specific area within a time amount that's reasonable
to complete but challenging."

MISSIONS -- the asymmetry IS the game:
  - PICKUPS in the CENTRAL TOWN only (nodes with node.kind === 'town').
  - DROP-OFFS are the named POIs in roadNet.pois. Never a random junction.
  - Name the job after the POI and give it a line of character -- "Larch Lakehouse, out on the
    west shore", "Stonecrop Lookout, up on the ridge". The player should build a mental map of
    the region over a session.
  - TIME BUDGETS from the A* path length, weighted by difficulty. A 'lane' is slower than an
    'artery'; climbing costs time. Use edge.kind, edge.width, poi.elevation and poi.difficulty.
    DERIVE THE PACE FROM REAL MEASUREMENTS, not a guess: drive the rig along an artery and along
    a lane and measure the actual average speed the car sustains on each, then budget from that.
    Report those measured speeds. It must be "reasonable to complete but challenging".
  - WEATHER AFFECTS GRIP (window.__zr.weather.gripScale, as low as ~0.55 in snow). The budget
    MUST account for it or every snowy run is an unfair loss.
  - Payout scales with distance, difficulty and time remaining; streak multiplier for
    consecutive on-time deliveries.

MINIMAP AT 3 km: it can no longer show the whole world usefully. Use a zoomed, panning view
around the car, with the objective clamped to the edge and a distance readout, plus the A* route
drawn. Distinguish the three road tiers visually (artery thick, street medium, lane thin). Keep
it cheap: pre-render the static network once to an offscreen canvas and blit/rotate it, do NOT
redraw 778 edges every frame. It must stay legible at 220 px and rotate correctly with camera yaw.

Do not invent new DOM: index.html and styles.css are fixed. Use the existing element ids.

Verify a full pickup-to-delivery cycle (python tools/verify.py --only mission) and report real
numbers: measured artery vs lane average speed, typical journey distance, the time budget you
derive from it, and how much margin a good drive actually leaves.`,
    { label: 'missions', phase: 'Populate', schema: SCHEMA }),
])

return out
