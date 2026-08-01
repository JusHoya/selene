# SELENE — Spacecraft & Extraterrestrial Logistics for Extraction, Navigation & Exploitation

## Project Overview
SELENE is an AI-driven lunar ISRU (In-Situ Resource Utilization) fleet management software suite. It commands, coordinates, and optimizes a heterogeneous fleet of autonomous lunar surface robots across the full ISRU value chain: prospecting, extraction, processing, and transportation.

## Architecture
- **Layered, modular, hardware-agnostic** design
- **Mission Control Layer** (Earth-side): Mission planning, supervisory control, fleet visualization
  (currently a 2D canvas fleet map — a 3D digital twin is an architectural goal, not built)
- **Fleet Orchestration Layer** (Lunar-side): Task decomposition, scheduling, resource allocation
- **Agent Autonomy Layer** (Per-robot): Perception, navigation, task execution, HAL
- **ISRU Process Control Layer**: Prospecting, extraction, processing, logistics

## Tech Stack

### Implemented (present in the repository today)
| Component | Technology |
|---|---|
| Robot middleware | ROS 2 — CI builds in `ros:humble-ros-base-jammy` (`.github/workflows/ci.yaml`); the WSL2 dev/validation path targets Jazzy (`scripts/setup_wsl2.sh`, `scripts/validate_phase5.sh`). Keep both in mind when adding dependencies. |
| Simulation | Gazebo Harmonic (`gz-harmonic`, installed in `docker/Dockerfile` and `scripts/setup_wsl2.sh`) |
| Task planning | HTN planner (`selene_orchestrator/selene_orchestrator/htn_planner.py`) |
| Communication | DDS — Fast DDS, the default RMW; no Cyclone configuration is checked in |
| Dashboard frontend | React 18 + JSX, roslib over rosbridge WebSocket; 2D HTML canvas rendering |
| Languages | Python only |
| Schema validation | Pydantic v2 (RCDL robot descriptors) |
| Tests | pytest (Python) |

### Planned / not yet implemented
Nothing in this list has any code in the repository. Do not describe these as current capabilities.

| Component | Technology | Status |
|---|---|---|
| Simulation (high-fidelity) | NVIDIA Isaac Sim | No imports, no assets, no config |
| 3D scene description | OpenUSD | No `.usd`/`.usda` files, no `pxr` imports |
| Classical planning | PDDL | No `.pddl` files, no parser, no solver. `docs/PRD.md:959` (DD-2) explicitly chose an HTN planner *instead of* STRIPS/PDDL for Sprint 0 |
| ML framework | PyTorch (training) / ONNX Runtime (inference) | No `torch`/`onnx`/`onnxruntime` imports anywhere |
| 3D dashboard view | Three.js | `three@^0.160.0` is declared in `selene_dashboard/package.json` but is imported by no source file |
| Real-time components | C++ | No `.cpp`/`.hpp` files. `selene_msgs/CMakeLists.txt` exists only to run `rosidl` message generation |
| Safety-critical components | Rust | No `.rs` files, no `Cargo.toml` |
| C++ tests | gtest | No C++ code to test |

## Package Structure
```
selene/
├── selene_msgs/          # Custom ROS 2 message/service definitions
├── selene_orchestrator/  # Fleet orchestration engine
├── selene_agent/         # Per-robot autonomy stack
├── selene_hal/           # Hardware Abstraction Layer
├── selene_sim/           # Simulation environment
├── selene_dashboard/     # Web-based mission control
├── selene_isru/          # ISRU process models
```

## Development Conventions
- Python packages use `snake_case`
- ROS 2 message types use `PascalCase`
- All ROS 2 nodes should be composable (lifecycle nodes preferred)
- Use `colcon` for building ROS 2 workspace
- Tests: `pytest` for Python (`gtest` applies only if/when C++ code is added — there is none today)
- Dashboard: React with JSX

## Key Design Principles
1. **Delay-tolerant**: 1.3s Earth-Moon light delay, potential multi-minute comm blackouts
2. **Resource-constrained**: Space-rated processors are orders of magnitude less powerful
3. **Graceful degradation**: No single point of failure
4. **Extensible**: New robot types, ISRU processes, celestial bodies without re-architecting
5. **Hardware-agnostic**: Standard interfaces via HAL and RCDL

## Current Phase
Sprint 0. Phase definitions are in `docs/PRD.md:1169` (summary table) and `docs/PRD.md:1212`–`1559`
(per-phase detail). Honest status:

| Phase | PRD scope | Status |
|---|---|---|
| 1 — Scaffolding & Sim World | FR-SIM-1..6, FR-SIM-7 (partial) | Implemented |
| 2 — Single Agent Autonomy | FR-AGT-1..7 | Implemented |
| 3 — Multi-Agent Coordination | FR-ORC-1/2/4, FR-MAP-1/2 | Implemented |
| 4 — Orchestration Intelligence | FR-ORC-3/5/6, FR-MAP-3, excavate+haul skills, FR-ISRU-1/2 | Implemented; ran end to end for the first time on 2026-07-31 |
| 5 — Dashboard & Integration | FR-DASH-1..7, FR-SIM-7 (full), FR-MAP-4 | Code complete and mostly demonstrated live; **exit gate RUN FIVE TIMES and NOT PASSED** (8/1/2 exit 1, then 9/0/2 exit 2, then 10/1/0 exit 1 at `9c1a4d7`, then **8/2/1** and **8/2/1** exit 1 on 2026-08-01 after the D-42 work) |
| 6 — Polish & Hardening | NFR-1..5 validation, integration demos | Not started as a phase. Substantial hardening landed on branch `phase5-hardening` — see register D-19..D-42 |

**`docs/phase5_deviation_register.md` is the authority on Phase 5 status** and is
considerably more detailed than this section. Read it before describing anything in
Phase 5 as working. The distinction it draws — "implemented" versus "demonstrated" —
is the one that matters here.

Caveats a reader should know:
- **THE EXIT GATE HAS NOW BEEN RUN FIVE TIMES AND IT STILL DOES NOT PASS.** Two more runs on
  2026-08-01, after the D-42 work, both **8 passed / 2 failed / 1 skipped, exit 1**.
  **CHECK 11 PASSES NOW, TWICE, ON TWO DIFFERENT TARGETS** — the row D-42 took down:
  `planned_path ends 0.28 m` and `0.20 m from the commanded target`. **Check 1 also passes**
  after a real defect was found in it: `gz model --list` was sampled ONCE while
  `simulation.launch.py` spawns robots 2 s apart, so the last robots of the fleet were
  reported "absent from Gazebo" on a system that was fine — measured directly, 3 of 4 models
  at t=8 s and all 4 from t=12 s onward, in the same run whose check 4 saw four robots at
  2 Hz. It now polls to the same `READY_TIMEOUT` the node check already uses.
  **TWO ROWS STILL FAIL AND NEITHER HAS BEEN PAPERED OVER.**
  **Check 4**: `scout_01: IDLE for 12 samples over 5.0s but its settled samples span
  0.061 m (>= 0.05 m)` — a parked robot creeping ~1.2 cm/s. That is either a real physical
  behaviour of a brakeless differential drive on a slope or a threshold that was never right;
  **it has not been diagnosed, and the threshold has NOT been widened to make it pass.**
  **Check 6**: the injected task is announced in ~2.5 s and then loses the auction. The
  mechanism is a race, not a missing feature — `get_next_ready` really does take
  `max(priority)` and `wake_deferred_auctions` really is wired to `FleetMonitor.idle_arrivals`
  (both checked; an earlier reading of mine that the wake had no production caller was WRONG
  and is withdrawn). What happens is that the gate frees a robot with `cancel_task` while an
  auction for another task is already in flight, that robot bids on the in-flight task, and
  the injected task's next round finds no bidder. It passed at **11.21 s of a 15 s budget**
  on the third run, so it has been marginal all along. Check 9 SKIPs as a consequence of 6.
- **The exit gate had been RUN THREE TIMES, and it did NOT PASS.**
  `scripts/validate_phase5.sh` ran twice on 2026-07-31 (ROS 2 Jazzy, 2/1/1, `prebuilt:=true`):
  **8 / 1 / 2 (exit 1)**, then **9 / 0 / 2 (exit 2)** — exit 2 is a SKIP, which by the gate's
  own contract is not a pass. It ran a third time on **2026-08-01 against `9c1a4d7`**:
  **10 passed / 1 failed / 0 SKIPPED (exit 1)**.
  **ZERO SKIPS IS THE HEADLINE.** D-34 is fixed on both sides, so checks 6 and 9 produced
  verdicts for the first time and both PASSed — **PRD exit-gate rows 3 and 4 are MEASURED at
  last** (task announced 0.71 s and assigned 11.21 s after injection; queue transport 5 ms,
  median of 554). D-35 is fixed too, and its repairs are visible inside the remaining failure
  line: bearing `+45 deg off heading 0.691 rad` rather than due east, window `11.0s derived`
  from `scout.yaml` rather than a constant 12.
  **What still fails is check 11, and the reason is NEW and UNEXPLAINED**: the gate picked
  `scout_02`, which was reporting **0.0% battery**, and never verified it could perform the
  manoeuvre; the FSM accepted `OPERATOR_GOTO` and **six milliseconds later** the
  energy-critical rule fired, so the planned path ended 0.71 m from the recharge pad and
  4.54 m from the commanded target. **That 0% is register D-42 and its cause is UNKNOWN.**
  An earlier claim of "11/11 twice" is **superseded**: both of those runs passed check 10
  vacuously on a map with `total_observations = 0` (D-29, fixed and demonstrated).
  The regenerated report lives at `$HOME/selene/phase5_validation_report.md` (source commit
  `9c1a4d7`); **`docs/phase5_validation_report.md` in the repo is still the superseded
  eight-check gate at `251e84d`. Do not quote it as current evidence.**
- **Most of Phase 5 has now been observed on a running system, and the register says which
  parts and on whose authority.** `colcon build` compiles all six packages with zero errors,
  so the five new and four amended `.msg` definitions are generated and have carried real
  traffic. The dashboard was opened in Chrome and D-01, D-02, D-03, D-04 and D-17 were
  confirmed rendering. The ISRU chain ran end to end (D-06). **D-11..D-18 are all closed.**
  **Nineteen new deviations (D-19..D-37) were opened on 2026-07-31**, eleven closed on live
  evidence and six left open. **On 2026-08-01 all six of those closed** — D-28, D-30, D-31,
  D-32, D-34, D-35 — and **five more were opened (D-38..D-42)**.
  **D-42 IS NOW CLOSED — ROOT-CAUSED, REPRODUCED ON DEMAND, FIXED, AND THE FIX
  DEMONSTRATED AGAINST THE REPRODUCTION.** The cause is a **second `battery_node` for the
  same robot on a shared ROS domain**. `ros2 launch` does not take its children with it, so
  an incomplete teardown leaves a complete SELENE stack alive (measured: 50 nodes, every
  node duplicated, `rosbridge: Address already in use`); an orphaned `battery_node` latches
  its last `cmd_vel` forever and keeps integrating locomotion draw with no simulator behind
  it — **measured at 85.0 W, reaching the `max(0.0, …)` clamp in 28.5 minutes and publishing
  EXACTLY 0.0 at 10 Hz thereafter**; and `GazeboBattery._cb` caches whichever message
  arrived last with no notion of source. Robots that never moved sit pinned at **exactly
  1.0** in the same measurement, which is the scout_02-only asymmetry. Nothing sets
  `ROS_DOMAIN_ID` anywhere in this repository outside `docker-compose.yaml`, and
  `GZ_PARTITION` isolates Gazebo transport only. The 0.1 % that the register could not
  explain is the **fingerprint**: net solar for a stationary scout outside the PSR is
  exactly 40 − 10 = 30 W into 50 Wh, so `.1%` formatting prints "0.1%" for t ∈ [3.0, 9.0] s
  from empty. **One deviation is still open and its cause is still unknown: D-37**, and the
  rule about not inventing a cause for it stands. **D-37's campaign HAS now been run**
  (`scripts/d37_drive_campaign.sh`, 45 min, 4/3/3): **7,569.9 fleet-metres and 26,970
  robot-seconds with no abort, at 0.281 m per robot-second — INSIDE the crash runs'
  0.174–0.368 band**, where the two clean runs the register already had sat at 0.053.
  Both hazard models are rejected at **p<0.01** (survival 0.0047 per-second, 0.0026
  per-metre). The blocker dissolved rather than being worked around: nothing in the
  physics consumes `BatteryState`, so a fleet driven at the simulator layer with no
  agents cannot be stopped by a flat battery, and no line of `selene_agent` is on the
  aborting stack. **THE LARGEST CAVEAT IS THAT THIS IS NOT THE CONFIGURATION THAT
  CRASHED** — circles under direct `cmd_vel`, no skills, no actuators, no excavate or
  haul — so a hazard depending on something an agent does is not covered. Note also the
  grep trap this run exposed: `grep -c "ODE INTERNAL ERROR"` returns **1 on a clean
  run**, because D-26's diagnostic banner quotes the assertion verbatim on ANY simulator
  exit. The real signature is `exit code 134`, which was 0; the actual return code was
  −9, from the campaign's own teardown.
- **Four of the five new deviations came from running the CHECKING APPARATUS, not the
  system.** D-38: CI's `dashboard-tests` job had never fired on this branch (SELENE CI
  triggers only on main/develop/PR/dispatch), and when dispatched it could not `npm ci` at
  all — the lockfile resolved `typescript@6.0.2` against `react-scripts@5.0.1`'s peer range
  of `^3.2.1 || ^4`, inconsistent since `1aec25e`. D-39: two world files were **invalid XML**
  (a literal `--` inside an XML comment, forbidden by XML 1.0 §2.5); Gazebo never cared
  because libsdformat is lenient, but `check_env.sh`'s **next** check printed
  `[ OK ] world-scope <gravity> =` against an **empty value**, certifying lunar gravity while
  measuring nothing. D-40: the Resource Knowledge Map's **animation loop was never started** —
  an empty-state early return rendered no canvas and no ref, all three canvas effects bailed
  on null refs and their dependency arrays never changed again; `FleetMap` has the identical
  loop and no early return, which is why one worked and its sibling did not. D-41: `gz sim -s`
  segfaults in `Ogre2DepthCamera::CreateDepthTexture` with no GL context, which counterfeited
  **four "cannot climb" results at 10° and 15°** in the slope campaign — indistinguishable
  from a real failure, and it would have set the slope limit far too low. **D-41 IS NOT D-37**:
  that one aborts on an ODE assertion with physics on the stack; this segfaults in Ogre with
  no physics on the stack at all.
- **Three deviations were mission-fatal and none of them was findable by reading tests.**
  D-19: `recharge_threshold` was declared by the orchestrator and read by nobody while the
  agent recharged unconditionally after every task at ~90% charge, so `SelectSite` never
  resolved and **the ISRU ledger was empty from Phase 4 onward**. D-23: every ice deposit
  sits inside a PSR crater whose rim is **34.3–39.2°** and every depot sat outside it, so
  **no haul in this system had ever been physically possible**; the depot is now on the
  crater floor at (-100, -150). D-24/D-25: dead reckoning was the only position estimate, its
  error reached **166 m**, and a hauler once reported a perfect 19 kg delivery while standing
  **241.577 m** from the depot with its wheels spinning at 100% slip.
- **THE PATH FOLLOWER ORBITED ITS WAYPOINTS, AND IT COST THE MISSION THE WHOLE ISRU CHAIN
  (D-43, fixed 2026-08-01).** `_find_lookahead` stops steering toward a waypoint inside
  `lookahead_distance` (2.0 m) and scans forward FROM `_target_idx`, while the retirement
  loop advanced that index only inside `waypoint_tolerance` (1.0 m). On a reversal the
  follower curves away, never closes to 1 m, and re-acquires the same waypoint forever.
  **The follower code is older than the symptom**: `9c1a4d7` closed D-28 by enforcing the
  slope limit per STEP, which turned crater-wall routes into chains with 135° reversals —
  exactly the geometry that makes a 2 m lookahead miss a 1 m tolerance. **A correct fix
  exposed a latent defect one layer down, for the second time in this register.** The
  remedy is the invariant, `max(tolerance, lookahead)`, not a retuned constant; arrival
  stays tight and a test asserts so. Measured A/B on two identical 16-minute runs:
  surveys completed **6/10 → 10/10**, first reading **802.5 s → 240.4 s**, path/net
  **5.29× → 2.59×**, `(excavate)` auctions **0 → 1**, and **the excavator drove 48.2 m
  having previously recorded a single FSM transition in sixteen minutes.**
- **A SECOND SELENE STACK IS A HAZARD THIS SYSTEM HAS NO DEFENCE AGAINST, and it is now
  the first thing to check when a live number looks impossible.** `ros2 launch` leaves
  children running; nothing sets `ROS_DOMAIN_ID`; `GZ_PARTITION` covers Gazebo transport
  only; TCP ports are not isolated at all. Two stacks share every topic, and no message in
  this system carries producer identity — `sensor_msgs/BatteryState` leaves `frame_id`,
  `location` and `serial_number` empty, so `ros2 topic echo` on a contaminated domain looks
  exactly like one node behaving erratically. This cost the 2026-08-01 exit gate its green
  (D-42) and invalidated the first RViz2 side-by-side (open item 22(a)) **on the same day**.
  Defences added 2026-08-01: every agent logs a CRITICAL `FleetAlert` naming the publisher
  count on its own battery topic and **suspends the energy rule while the channel is
  unattributable**; `scripts/validate_phase5.sh` refuses to start (exit 3) when 9090 or 3000
  is already held and warns, naming processes, when SELENE nodes are already running.
  **`scripts/start.sh` is a separate live hazard**: it still spawns the abandoned ring — all
  four robots at 44.7–57.0 m from the PSR centre against a 60 m radius, i.e. **all inside**,
  where the solar branch can never open and the batteries can only go down.
- **The "wired but never called" pattern has bitten this repository SIX times in production
  and once, found 2026-08-01, INSIDE THE MEASURING APPARATUS** — the exit-gate probe
  recorded `battery_level` on every RobotState sample and read it in exactly one place, a
  `0.0 <= x <= 1.0` range assertion in check 4 that `0.0` satisfies. So check 4 PASSED on a
  robot reporting zero charge and said nothing, on the same run whose check 11 that robot
  took down. It is the
  first thing to check in any new code. `AdaptiveSurveyPlanner` shipped with green unit tests
  and zero call sites (fixed, FR-MAP-3); `MaterialInventory`'s four write methods had zero
  production callers (fixed, D-06); `resource_map_publish_rate` was declared and never read
  for two phases, which is why FR-MAP-4 went unbuilt (fixed, D-09); `recharge_threshold` was
  declared, configured and never read, which cost the mission its entire ISRU cycle (fixed,
  D-19); `navigation.max_traversable_slope_deg` had zero readers from Phase 2 until
  2026-08-01, which is why nothing noticed the crater (**fixed, D-28** — it now has readers at
  `agent_node.py:219` and in six places in `navigator.py`); and `FleetMonitor.get_robot_distance`
  had **zero callers anywhere** while `get_total_distance` had zero test callers, which is why
  D-31 shipped a dashboard number that was 2.21× the truth (fixed, D-31).
  **Two guards now exist and they see different shapes.**
  `selene_orchestrator/test/test_no_orphan_parameters.py` fails the build on any *declared*
  parameter nothing reads, and its allow-list is down to one name
  (`fleet_state_publish_rate`) — but **it cannot see D-28's shape**, because a YAML key no
  node declares at all is not an orphan, it is absent.
  `selene_agent/test/test_nav_params_are_read.py` sees that shape: **`nav_params.yaml` had 26
  leaf keys of which 17 had no reader; it now has 22 keys with 5 unread**, all
  `obstacle_avoidance.*`, allow-listed with a written reason because `ObstacleAvoidance`
  itself has no production caller — the same pattern again, one frame smaller.
  `_publish_assignment_msg` is a current instance, documented as having no caller.
- **The slope limit is 20°, it is MEASURED, and it is enforced PER STEP — not per cell.**
  `scripts/measure_slope_capability.sh` ran **54 trials** (3 robot types × 9 grades ×
  2 directions), judging world displacement against the COMMAND, never against odometry:
  scout 35/25, excavator 20/25, hauler 20/25 (ascent/descent), so round trips are governed by
  **20°**. Artefacts are committed (`docs/slope_capability_2026-08-01.json`, `.log`,
  `.PROVENANCE.md` — **read the provenance file: the artefact's `git_commit` is WRONG and the
  measurement stands only because all four input SHA-256s verify**). The crater rim is a
  **34.02° minimax barrier** (binary search over connected-component labelling, so a winding
  route would have been found), yet the fleet delivered 94.85 kg inside it. Both are true
  because **a vehicle climbs along its own heading, not the fall line**: a path crossing
  slope `S` at `theta` off the fall line climbs at `atan(tan(S)·cos(theta))`, so at 34.02° a
  route ≥ 57.4° off the fall line climbs at 20° for a 1.85× length penalty — a switchback.
  The campaign measured `theta = 0` by construction. **Enforced per CELL the map is
  unreachable at 10/15/20/25° and reachable only at 34; enforced per STEP it is one connected
  component at 20°.** Every agent logs a `[TERRAIN]` startup audit naming what the limit
  excludes and whether the depot and the recharge pad are reachable — it is a report, never a
  gate. **NOT MEASURED: side-slope rollover**, usually the binding limit on a real vehicle and
  exactly the mode a switchback lives in; nothing in SELENE bounds it. **No vehicle has driven
  a switchback** — the 132.0 m and 130.2 m route figures are executed plans, not journeys.
- FR-MAP-1(e)(f) and FR-MAP-4 were implemented on 2026-07-30 and D-03 added a seventh
  publisher. The orchestrator now has seven `create_publisher` calls: the original four
  (`task_announcement`, `task_assignment`, `alerts`, `mission_progress`) plus
  `/orchestrator/resource_map` (`selene_msgs/msg/ResourceMap`, the fused posterior,
  sparse-encoded), `/orchestrator/resource_map_markers` (a `visualization_msgs/MarkerArray`
  CUBE_LIST overlay for RViz2 — hue is concentration, alpha is certainty) and
  `/orchestrator/task_queue` (`selene_msgs/msg/TaskQueueState`, a complete 2 Hz snapshot of
  the task table plus a bounded operator-event ring). The first two come from one snapshot on
  one timer at `resource_map_publish_rate`. `selene_sim/rviz/selene_sim.rviz` now carries a
  MarkerArray display on the overlay topic alongside Grid and TF. See
  `docs/phase5_deviation_register.md` D-03/D-08/D-09.
- The dashboard heatmap builds from the orchestrator's fused posterior
  (`/orchestrator/resource_map`), not from raw per-reading `ResourceMapUpdate` messages, and
  the RViz2 overlay and the dashboard render it through ported halves of one colour law whose
  **whole** extent — the gray lerp and the alpha ramp as well as the concentration ramp — is
  machine-checked across the language boundary with no per-channel tolerance by
  `selene_orchestrator/test/test_dashboard_colour_parity.py`. The dashboard half **has now
  been rendered in Chrome**, and **the `docs/PRD.md:1504` SIDE-BY-SIDE HAS NOW BEEN PERFORMED**
  — register open item 22 is discharged on all four of its clauses. One stack (publisher count
  1 on the markers, on the posterior and on `/tf_static`; one rviz2; one orchestrator), a map
  the FLEET surveyed rather than one the probe seeded (9 prospect completions, 793
  observations, nothing injected), the same top-down orthographic projection on the
  dashboard's own `DEFAULT_VIEW` centre, and no hand-run transform — RViz2 reports
  `Global Status: Ok`. A surveyed map renders as **discrete overlapping discs, one per
  waypoint reached**, visibly not the smooth radial Gaussian a synthetic seed produces; that
  difference is what makes the pair evidence rather than decoration. **(b) was not discharged
  by trying harder — it was discharged by D-43**, without which the first reading arrived at
  t=802 s and only 6 of 10 waypoints ever completed. Residue stated: the two images share a
  centre, a projection, an orientation and a 50 m grid but NOT an aspect ratio, so the
  comparison is "count the cells", not "identical rectangles". The machine comparison still
  stands alongside it: the exit gate recomputes the marker array from the `ResourceMap`
  message and asserts point-and-colour equality, through the same module the publisher uses.
- **The `ImageData` row flip in `FleetMap.jsx` has been checked and is CORRECT**, and the
  raster has now been rendered in a browser. Three independent passes executed the round trip
  outside a browser — producer flat index, consumer decode, and the `translate`/negative-`scale`
  blit — and all three reproduced `ResourceMap.grid_to_world()` exactly, one of them over
  36,000 cells with zero mismatches. The counterfactual was checked too: omitting the flip
  mirrors the map about y = 0. **Note the hot-cell coordinate those passes used, world
  (-80.5, -140.5), is SUPERSEDED** — it was measured in the odom frame (see the frame bullet
  below and register D-08/D-33). The geometry argument is unaffected; the coordinate is not a
  physical location.
- **D-01 and D-02 were closed on 2026-07-30 with no adversarial review**, unlike every other
  entry closed that day — the reviewer assigned to them died mid-stream with an API error and
  nobody recorded the gap. The review was finally run on 2026-07-31 and found nine defects,
  four of which became D-15..D-18. **All four are now fixed and closed**, and the dashboard
  has a JavaScript test runner for the first time: `selene_dashboard/src/__tests__/`,
  39 Jest tests over the real reducer and the real mark planner on 2026-07-31, **101 over
  7 suites as of 2026-08-01** — the new ones cover the resource view's canvas lifecycle and
  node identity, the state-history reducer and pose validity. D-17's replacement — a
  2-D legend swatch evaluated through the same function the raster applies — was confirmed
  rendering in Chrome, and that observation found a defect **no arithmetic in the register
  predicted**: the old legend's three labels collided on screen into `unsure5 wt% shownconfident`.
  The lesson is in the register's own voice: a closure written the same day by the implementer
  is not evidence, and neither is a green test.
- **The ISRU mass ledger has run end to end** (D-06, demonstrated 2026-07-31): sim publishes a
  fill *fraction* → the HAL derives `mass_kg` from the RCDL's `capacity_kg` → the skill measures
  a delta → the agent publishes `selene_msgs/msg/MaterialEvent` → the orchestrator dedupes it,
  resolves the site from `task_id` and writes `MaterialInventory` → `MissionProgress` carries
  real masses. Mass is **never estimated**: a skill that cannot read its fill sensor publishes
  nothing rather than a zero. Measured on a 30-minute ten-robot run: **five deliveries,
  `deposited_quantity` 94.85 kg, `unaccounted_quantity` exactly 0.0**, hauler ground truth
  1.539 m from the depot marker. **The conservation identity is not the interesting check** —
  `extracted == at_site + in_transit + deposited` is an algebraic invariant of
  `MaterialInventory` and can only fail on float drift. `unaccounted_quantity` is the one that
  can fail. An earlier run produced an identically clean ledger for a delivery that happened
  241 m from the depot; read register D-06's status block before quoting any ledger figure.
- Nothing in the repository publishes TF: `/tf` and `/tf_static` still have zero publishers.
  (`tf2_msgs/msg/TFMessage` *is* now used — it is the type `ros_gz_bridge` carries the model
  pose on — but it is remapped to `/<robot_id>/pose_truth`, not to `/tf`.) RViz2 resolves a
  frame only when `header.frame_id` equals its fixed frame, so the overlay is published in
  `map`, and `resource_map_frame_id` (orchestrator_params.yaml) and `Fixed Frame` in
  `selene_sim/rviz/selene_sim.rviz` must stay in agreement with it.
- **Positions are world coordinates now, and they were not before 2026-07-31.** `/odom` is
  dead-reckoned by DiffDrive from each robot's **spawn pose**, and every consumer used to read
  it as if it were world. The offset is a **full SE(2)** — a ~133° rotation, measured by
  `scripts/check_drive.sh` (bearing difference -2.3678 rad against a spawn yaw of -2.3300); an
  earlier translation-only model was wrong by that whole angle. It is now converted **once**,
  in `selene_sim/selene_sim/world_odometry_node.py`, which publishes `/<rid>/odom_world` in
  frame `map`. The three RCDLs, `neutron_spectrometer_node`, `hopper_node`, `extraction_node`
  and `battery_node` all read `odom_world`; `selene_orchestrator/.../terrain_guard.py` and
  `AStarPlanner.plan` refuse off-terrain goals. **A `pose_source` parameter chooses what that
  topic carries**: `localisation` (default) publishes the simulator's true world pose — the
  simulator standing in for a localisation stack — and `dead_reckoning` reproduces the old
  behaviour exactly. The divergence is measured and alerted in **both** modes. Consequences:
  (a) any position measured before 2026-07-31 is in the old frame and is not comparable;
  (b) `dead_reckoning` mode has never been run; (c) on real hardware this node is a stub with
  a real estimator behind it, and every error bar comes back. See register D-33 and D-24.
- **`RobotState` has a new trailing field, `bool pose_valid`, and three consumers read it.**
  It exists because the agent used to publish a **fabricated** pose: `GazeboOdometrySensor`
  returns a cached reading with `is_valid=False, x=0.0, y=0.0` before odometry arrives
  (`gazebo_hal.py:357-359`) and `_publish_state` copied it with no validity test, so
  `FleetMonitor` seeded from (0,0) and booked `|spawn|` as travel — **1096.580 m** over the
  ten-robot fleet, every increment under the 500 m jump guard (register D-31). `pose` is
  **still populated** when the flag is false; the flag carries the meaning. Readers: the
  orchestrator directly, the gate probe via `getattr(msg, 'pose_valid', True)` so a pre-D-31
  workspace degrades rather than crashes, and the dashboard (robots without a fix go to an
  amber **"NO POSITION FIX"** roster reading "not drawn — position unknown, not (0, 0)").
  **The fail-safe default has a cost**: ROS 2 initialises `bool` to false and a subscriber
  cannot tell "set false" from "never set", so **rebuild all six packages in one `colcon
  build`** or robots silently drop out of the distance total. **Sufficiency is NOT
  established**: 1096.580 m *over*-explains the measured 913.07 m excess by ~442 m, and a
  second mechanism (a truth/dead-reckoning flip in `world_odometry_node`) is not eliminated.
- **The 2026-08-01 browser evidence came from a rosbridge TEST DOUBLE, not the real stack**,
  and every claim resting on it says so. That covers D-40's canvas lifecycle (canvas mounts
  at **1240 × 576**, not the 300 × 150 default — the number that proves `updateCanvasSize`
  re-ran), the `pose_valid` roster, and a **247 ms IDLE hand-off** appearing in `RobotDetail`'s
  state history (which the old `throttle_rate: 500` would have dropped). It proves what the
  browser does when messages of that shape arrive and **nothing about ROS, DDS or QoS**. The
  2026-07-31 Chrome pass (D-01..D-04, D-17) was against a **live** rosbridge and is stronger
  evidence; do not quote the two as if they were the same.
- **`use_sim_time` is set by nothing**, and this is a deliberate deferral rather than an oversight.
  No node declares it, no launch file passes it, and `/clock`, `gz.msgs.Clock` and `rosgraph_msgs`
  have zero occurrences — every hit for the name is a comment saying exactly this. Every duration in
  the system is wall clock, including `MissionProgress.elapsed_sim_time`, which keeps its misleading
  name because renaming a published field breaks the dashboard and PRD MSG-7. Making it real needs
  three changes together and doing fewer than all three is worse than doing none; the reasoning is in
  `docs/phase5_deviation_register.md`, "Open items carried forward" item 1.
- **Running the tests.** Counts below were measured on **2026-07-31 (evening)**, Python 3.11.6
  / pytest 9.1.1, on the working tree. Treat the baseline comparison, not the absolute number,
  as the invariant — repairs add tests.

  ```bash
  # Everything, one process, either collection order
  PYTHONPATH="selene_orchestrator;selene_isru;selene_hal;selene_agent;selene_sim" \
    python -m pytest selene_orchestrator/test selene_isru/test selene_hal/test \
                     selene_agent/test selene_sim/test -q            # 1220 passed, 1 skipped

  # The gate lane — the two-package path CI now runs whole (job `gate-lane-tests`)
  PYTHONPATH="selene_orchestrator;selene_isru" \
    python -m pytest selene_orchestrator/test selene_isru/test -q    # 649 passed, 3 skipped

  cd selene_dashboard && CI=true npx react-scripts test --watchAll=false
                                                                     # 101 passed, 7 suites
  python -m flake8 selene_orchestrator selene_isru selene_hal selene_agent \
                   selene_sim scripts                                # 0 findings, exit 0
  ```

  Counts above were re-measured on 2026-08-01 after the D-42 work (they were 1150/1 and
  623/3 earlier that day, 947/1 and 518/1 on 2026-07-31; repairs add tests). The delta is
  exactly the three new files: `selene_sim/test/test_battery_model.py` (14),
  `selene_orchestrator/test/test_phase5_probe_goto_subject.py` (26) and
  `selene_agent/test/test_battery_validity_is_wired.py` (16) — 1150 + 56 = 1206. **The
  energy model had ZERO tests of any kind until 2026-08-01** — `battery_node.py`'s
  arithmetic sat behind a module-level `import rclpy`, so no documented lane could reach
  it, which is why D-42's arithmetic had to be re-derived by hand in the register twice.
  It now lives in `selene_sim/selene_sim/battery_model.py` as pure Python, the same shape
  as `localisation.py`. The four-package and `selene_sim`-only lanes still work and are
  documented in the register.

  The gate lane was **1 failed, 518 passed** until 2026-07-31 (register D-36):
  `selene_orchestrator/test/test_terrain_guard.py` did a bare
  `from selene_agent.navigator import OccupancyGrid` with no `importorskip`, so the lane failed
  rather than skipped when `selene_agent` was not on the path. Neither CI's `cross-package-tests`
  job nor the four-package lane could see it, because both put every package on the path.
  The three skips are all `importorskip`-guarded with that reason, and **the cross-package lane
  still runs every one of those assertions with zero skips** — a skip is only safe while some
  lane still makes the assertion. **D-36's remainder is now closed**: CI job `gate-lane-tests`
  (`.github/workflows/ci.yaml:121`) runs the gate lane whole, installs the same dependency set
  as `cross-package-tests` so `PYTHONPATH` is the only variable, and was **mutation-tested
  before commit** — with the guard removed the gate lane goes 1 failed / 518 passed while the
  cross-package lane stays green at 51 passed, which is exactly D-36's shape.

  **SELENE CI is green on this branch**: 9/9 jobs at `d390315`, `7727ba8` and `9c1a4d7`
  (8/8 at `c4548ce`, before `gate-lane-tests` existed), including the Humble `colcon
  build`/`colcon test` lane and `shellcheck -S warning scripts/*.sh`. The separate
  **Simulation gates** workflow (real Gazebo: `check_terrain.sh`, `check_drive.sh`) is also
  green at `7727ba8` and `9c1a4d7`. Note SELENE CI triggers only on push to `main`/`develop`,
  PR to `main`, or `workflow_dispatch` — **on a feature branch it must be dispatched, and a
  job that has never fired is not a check** (that is D-38).

  Three rules follow and all three are earned. **Do not "complete" the ROS-free stubs** in
  `selene_orchestrator/test/conftest.py` so another package's imports resolve against them —
  that trades a loud abort for `selene_hal`'s Gazebo tests silently running against
  hand-written fakes in one invocation and skipping in another (D-14). **Do not add a test
  lane without a cross-package lane** — no CI job ran one, which is why D-14 survived a full
  closeout. And **do not add a cross-package import without a guard for the lanes that do not
  span those packages** — that is D-36, the same lesson from the other side.
- **This file and the deviation register are honest documents and their value is that honesty.**
  Do not describe a capability as working on the strength of a passing unit test; say
  "implemented" and name what has not been run. Most of Phase 5 **has** now been observed on a
  running system, and `docs/phase5_deviation_register.md` states per entry which claims rest on
  a live run, which on a unit test, and whose authority each live figure is on. The rule that
  produced that discipline is unchanged, and 2026-07-31 vindicated it: running the system found
  **five defects no amount of reading would have caught**, four of them invisible to a green
  suite, and one of them — a 34° crater between every deposit and every depot — had made every
  haul in this system impossible since the world file was written.
  **2026-08-01 added a second rule to that one: run the CHECKING APPARATUS too.** Four of that
  day's five new deviations were instruments, not systems — a CI job that had never fired, a
  preflight check printing OK against an empty string, a canvas whose loop had never started
  under a header showing correct numbers, and a simulator crash that manufactured four
  believable "cannot climb" results. **Three of the four were reporting success.** And D-28,
  the largest finding, was a correct observation attached to a wrong model for four revisions:
  the limit was never ignored so much as unmeasured and expressed in the wrong quantity — per
  cell it refuses the whole mission, per step it admits it. **Still unknown: D-37's cause,
  D-42's cause. Still never run: RViz2. Still not passing: the exit gate.**
