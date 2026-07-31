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
| 5 — Dashboard & Integration | FR-DASH-1..7, FR-SIM-7 (full), FR-MAP-4 | Code complete and mostly demonstrated live; **exit gate RUN TWICE on 2026-07-31 and NOT PASSED** (8/1/2 exit 1, then 9/0/2 exit 2) |
| 6 — Polish & Hardening | NFR-1..5 validation, integration demos | Not started as a phase. Substantial hardening landed on branch `phase5-hardening` — see register D-19..D-37 |

**`docs/phase5_deviation_register.md` is the authority on Phase 5 status** and is
considerably more detailed than this section. Read it before describing anything in
Phase 5 as working. The distinction it draws — "implemented" versus "demonstrated" —
is the one that matters here.

Caveats a reader should know:
- **The exit gate has been RUN, and it does NOT PASS.** `scripts/validate_phase5.sh` was
  executed twice on 2026-07-31 (ROS 2 Jazzy, gz-sim 8.11.0, 2/1/1, `prebuilt:=true`):
  **8 passed / 1 failed / 2 skipped (exit 1)**, then **9 / 0 / 2 (exit 2)**. Exit 2 is a SKIP,
  which by the gate's own contract is not a pass. Checks 6 and 9 SKIPped on both runs and
  check 11 flipped between them. **Both non-passes are defects in the gate's measuring
  apparatus, not in the system** — register D-34 (the gate cannot observe an FSM state
  shorter than its 0.5 s sampler; the two SKIPs cost PRD rows 3 and 4) and D-35 (check 11 is
  a coin flip separated by 33 cm). Neither was patched, deliberately. An earlier claim of
  "11/11 twice" is **superseded**: both of those runs passed check 10 vacuously on a map with
  `total_observations = 0` (D-29, now fixed and demonstrated).
  `docs/phase5_validation_report.md` is still the output of the superseded eight-check gate
  at commit `251e84d`. Do not quote it as current evidence.
- **Most of Phase 5 has now been observed on a running system, and the register says which
  parts and on whose authority.** `colcon build` compiles all six packages with zero errors,
  so the five new and four amended `.msg` definitions are generated and have carried real
  traffic. The dashboard was opened in Chrome and D-01, D-02, D-03, D-04 and D-17 were
  confirmed rendering. The ISRU chain ran end to end (D-06). **D-11..D-18 are all closed.**
  **Nineteen new deviations (D-19..D-37) were opened on 2026-07-31**, eleven closed on live
  evidence and **seven still open**: D-28, D-30, D-31, D-32, D-34, D-35, D-36 — plus **D-37,
  the ODE abort, whose cause is UNKNOWN.**
- **Three deviations were mission-fatal and none of them was findable by reading tests.**
  D-19: `recharge_threshold` was declared by the orchestrator and read by nobody while the
  agent recharged unconditionally after every task at ~90% charge, so `SelectSite` never
  resolved and **the ISRU ledger was empty from Phase 4 onward**. D-23: every ice deposit
  sits inside a PSR crater whose rim is **34.3–39.2°** and every depot sat outside it, so
  **no haul in this system had ever been physically possible**; the depot is now on the
  crater floor at (-100, -150). D-24/D-25: dead reckoning was the only position estimate, its
  error reached **166 m**, and a hauler once reported a perfect 19 kg delivery while standing
  **241.577 m** from the depot with its wheels spinning at 100% slip.
- **The "wired but never called" pattern has bitten this repository FIVE times** and is the
  first thing to check in any new code. `AdaptiveSurveyPlanner` shipped with green unit tests
  and zero call sites (fixed, FR-MAP-3); `MaterialInventory`'s four write methods had zero
  production callers (fixed, D-06); `resource_map_publish_rate` was declared and never read
  for two phases, which is why FR-MAP-4 went unbuilt (fixed, D-09); `recharge_threshold` was
  declared, configured and never read, which cost the mission its entire ISRU cycle (fixed,
  D-19); and **`navigation.max_traversable_slope_deg` has had zero readers since Phase 2 and
  still has none outside a test — D-28, OPEN**, which is why nothing noticed the crater.
  `selene_orchestrator/test/test_no_orphan_parameters.py` fails the build on any *declared*
  parameter nothing reads, and its allow-list is down to one name. **It cannot see D-28's
  shape**: a YAML key no node declares at all is not an orphan, it is absent.
  `_publish_assignment_msg` is a current instance, documented as having no caller.
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
  been rendered in Chrome**. **RViz2 has never been started**, and the side-by-side comparison
  `docs/PRD.md:1504` asks for has never been performed — that is the largest remaining gap in
  Phase 5. What exists instead is a machine comparison: the exit gate recomputes the marker
  array from the `ResourceMap` message and asserts point-and-colour equality, through the same
  module the publisher uses.
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
  **39 Jest tests** over the real reducer and the real mark planner. D-17's replacement — a
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
                     selene_agent/test selene_sim/test -q                     # 947 passed, 1 skipped

  PYTHONPATH="selene_orchestrator;selene_isru;selene_hal;selene_agent" \
    python -m pytest selene_orchestrator/test selene_isru/test \
                     selene_hal/test selene_agent/test -q                     # 826 passed, 1 skipped
  python -m pytest selene_sim/test -q                                         # 120 passed, 1 skipped
  cd selene_dashboard && CI=true npx react-scripts test --watchAll=false      # 39 passed, 2 suites
  ```

  **One documented lane is currently RED — register D-36.**
  `PYTHONPATH="selene_orchestrator;selene_isru" python -m pytest selene_orchestrator/test
  selene_isru/test -q` gives **1 failed, 518 passed**:
  `selene_orchestrator/test/test_terrain_guard.py:343` does a bare
  `from selene_agent.navigator import OccupancyGrid` with no `importorskip`, so the lane fails
  rather than skips when `selene_agent` is not on the path. Neither CI's `cross-package-tests`
  job nor the four-package lane above can see it, because both put every package on the path.

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
