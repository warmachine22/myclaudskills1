export const meta = {
  name: 'zen-racer-drift-robust',
  description: 'Make the drift behave consistently across worlds, not just on favourable roads',
  phases: [{ title: 'Robustness', detail: 'widen the sliding basin so drift is not knife-edge' }],
}

const ROOT = 'C:/Users/mark5/Desktop/claudcodechat/zen-racer'

const PROMPT = `You own src/vehicle/vehicle.js in "Zen Racer", a working isometric delivery racing
game (three.js r170 + Rapier 0.14 + Vite). PROJECT ROOT: ${ROOT}

READ FIRST: ${ROOT}/PROGRESS.md and ${ROOT}/WORLD_V2.md section 6 (the feel spec, including the
research findings Mark asked for). The game passes 9/10 verification checks; drift is the one
that fails, and only on some worlds.

=== THE PROBLEM: DRIFT IS BISTABLE AND ROAD-DEPENDENT ===

Measured with \`python tools/verify.py --only drift --seed <seed>\`. Same standard entry
(full throttle to ~80 km/h on the longest wide straight, handbrake turn, then hold with throttle
and countersteer):

  seed zen-777 : held 1.9-2.65s, peak 46-50deg, retained 0.67-0.92   PASS
  seed c       : held 1.7-1.83s, peak 48deg,    retained 0.97        PASS
  seed pinned-1: held 0.77-0.88s, peak 64-66deg, retained 0.91-0.96  FAIL

I checked whether the test roads differ. THEY DO NOT:
  pinned-1  run=1020m halfWidth=7  grade avg 0.060 max 0.060  camber max 0.006  overcast grip 0.94
  c         run=1060m halfWidth=7  grade avg 0.057 max 0.060  camber max 0.013  snow     grip 0.55
  zen-777   run=1020m halfWidth=7  grade avg 0.058 max 0.060  camber max 0.013  overcast grip 0.94
(The rig passes grip:1 explicitly, so weather is not a factor in the measurement.)

So pinned-1 and zen-777 have effectively IDENTICAL road geometry AND identical weather, similar
entry speed (~80 km/h), and yet one settles at ~49deg and holds a 1.9 s drift while the other
overshoots to ~65deg and straightens in 0.83 s.

A previous tuning pass on this file diagnosed the mechanism and I believe it: the tyre model is
BISTABLE - a gripping attractor near 10deg of slip and a sliding attractor near 40deg, with a
repelling boundary around 28deg. Near that boundary a 2% change in a single constant flips a run
between "drifts for 3 s" and "straightens at 1.6 s". That pass added a drift attitude governor
(AIM_* PD term targeting 32-38deg), a drift latch, and counter-steer yaw damping. It got the
median case good. It did not make the system ROBUST.

=== YOUR JOB: MAKE IT CONSISTENT, NOT JUST GOOD ON AVERAGE ===

The player must not experience "the handbrake works on this road but not that one". Widen the
basin of attraction for the sliding state so small differences in micro-relief, entry speed and
approach angle cannot flip the outcome.

Ideas worth investigating (you decide, these are not instructions):
  - the governor currently overshoots to 65deg on pinned-1 despite targeting 32-38. Find out WHY
    the PD term fails to arrest it there. Insufficient authority? Rate limit? Sign flip near the
    boundary? A term that saturates?
  - make the governor's authority scale with how far past target the car is, so a big overshoot
    is pulled back harder rather than the same as a small one.
  - consider damping the *rate of change* of slip angle, not just the angle, so the car cannot
    accelerate through the target band and out the far side.
  - reduce the repelling character of the boundary near 28deg so the state does not get pushed
    to one extreme or the other.

TARGETS - the check must pass on ALL THREE seeds (pinned-1, c, zen-777), not just two:
  python tools/verify.py --only drift --seed pinned-1
  python tools/verify.py --only drift --seed c
  python tools/verify.py --only drift --seed zen-777
Each requires: >=3 of 9 inputs sustain 20-75deg slip for >=2 s; no input peaks past 80deg;
>=2 inputs both sustain >=2 s AND retain >=45% of entry speed.

ALSO: python tools/verify.py --only physics must keep passing on all three
(0-100 in ~5.5 s, braking, correct steering sign), and DO NOT regress airborne time - a previous
fix eliminated it and it has started creeping back (0.35-0.75 s on some runs). Investigate that
too: on a 7 m artery with 0.06 gradient the car should not be leaving the ground during a drift.

=== HOW TO WORK ===
A dev server is ALREADY RUNNING at http://127.0.0.1:5183. Do not start another.
Headless software rendering runs the rAF loop at a few fps, so you CANNOT judge driving by
watching. Step physics by hand (set g.running=false first):
  g.running=false;
  for(let i=0;i<300;i++){ g.vehicle.preStep(1/60,{throttle:1,brake:0,steer:0,handbrake:false},{grip:1});
                          g.physicsWorld.step(); g.vehicle.postStep(1/60); }
  python tools/shot.py --seed pinned-1 --eval "<js>"     # returns JSON
Rigs: ${ROOT}/tools/rigs/. The file already has ~25 __T() tuning hooks (inert unless
window.__zrTune is set) so you can sweep without editing between runs - use them.
Kill stray headless_shell processes between timed-out Playwright runs.

HARD RULES:
- Edit ONLY src/vehicle/vehicle.js.
- DO NOT touch _placeOnGround / _groundY / RIDE_HEIGHT or the queryPipeline priming inside
  _groundY. Those fixed a bug where the car hovered out of suspension reach forever.
- Heading convention: forward is -Z, so facing (dx,dz) needs atan2(-dx,-dz). Do not reintroduce
  atan2(dx,-dz), which is correct only for north.
- Handbrake must stay same-frame with no ramp (latency is the genre's biggest complaint).
- Counter-steer assist stays subtle and gated; too much "destroys the feeling for drifting".
- No external assets, no network. Verify with esbuild before finishing.
- Do not git commit.

Report the full 9-row sweep table for ALL THREE seeds, before and after. If you cannot make all
three pass, say so plainly and report what you achieved and what the remaining failure mode is -
an honest partial result is far more useful than a claim I have to disprove.`

phase('Robustness')
const out = await agent(PROMPT, {
  label: 'drift-robust',
  phase: 'Robustness',
  schema: {
    type: 'object',
    additionalProperties: false,
    required: ['summary', 'verified', 'risks'],
    properties: {
      summary: { type: 'string' },
      measurements: { type: 'string', description: 'before/after sweep tables for all three seeds' },
      allThreeSeedsPass: { type: 'boolean' },
      verified: { type: 'boolean' },
      risks: { type: 'string' },
    },
  },
})
return out
