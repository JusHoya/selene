# Phase 5 Deviation Register

What Phase 5 was scoped to deliver, what was actually delivered, and every place
those differ. Written 2026-07-30 at commit `19d364c`.

This document exists because a deviation was being carried by a single line in a
shell script. `scripts/validate_phase5.sh` printed, into its own report footer:

> **Known deviation:** FR-MAP-4 (RViz2 visualization, P1) intentionally skipped
> per plan decision D9 — the dashboard's canvas heatmap satisfies operator
> visualization.

**No decision D9 exists.** Searched exhaustively: `"D9"` appears four times in the
tree and three are downstream citations of the fourth. There is no D-numbered
decision scheme at all — the PRD's decision register is DD-1..DD-6
(`docs/PRD.md:954-963`) and stops at DD-6. `SELENE_Project_Plan_1.md` contains
neither "D9" nor "FR-MAP-4" and still lists RViz2 overlay as in scope
(`SELENE_Project_Plan_1.md:410`). `git log --all --grep=descope` returns nothing;
the line was introduced by `473259a` byte-identical to its current form, and that
commit added no decision document.

So the script that certifies the exit gate was also issuing the waiver for the
criterion it could not meet. That is not a deviation record; it is a self-signed
permission slip. This file replaces it.

---

## Status summary

| Requirement | Priority | Status |
|---|---|---|
| FR-DASH-1 Fleet Map View | P0 | Delivered with deviation (D-01) |
| FR-DASH-2 Resource Heatmap | P0 | Delivered with deviation (D-02) |
| FR-DASH-3 Task Queue Panel | P0 | Delivered with deviation (D-03) |
| FR-DASH-4 Robot Detail Panel | P1 | Delivered |
| FR-DASH-5 Manual Task Injection | P1 | Delivered with deviation (D-04) |
| FR-DASH-6 Robot Override | P2 | Delivered with deviation (D-05) |
| FR-DASH-7 Mission Progress | P1 | Delivered with deviation (D-06) |
| FR-SIM-7 Launch & Config (full) | P0 | **Delivered 2026-07-30** (D-07 closed) |
| FR-MAP-4 RViz2 Visualization | P1 | **Delivered 2026-07-30** (D-08 closed) |

All nine Phase 5 requirements are now delivered. Five carry named deviations
(D-01..D-05) that are defects on delivered features rather than unmet
clauses; D-06 is the one substantive gap remaining, and it is not a Phase 5
requirement alone -- it also blocks Phase 6 Demo 1 and SC-1.

Closed on 2026-07-30: D-07 (FR-SIM-7), D-08 (FR-MAP-4) and D-09
(FR-MAP-1(e)(f)). Separately, FR-MAP-3 -- P0 Phase 4 scope that had never
run in a live system -- was wired in on the same day; see the note after
D-10.

---

## D-01 — FR-DASH-1: robot state is not colour-coded by FSM state

**Specified** (`docs/PRD.md:486-494`): robot icons colour-coded by type, with a
state indicator colour-coded by FSM state.

**Actual**: the icon is coloured by type (`selene_dashboard/src/components/FleetMap.jsx:373`).
Of nine FSM states only three get any map encoding — a glow for `WORKING`
(`:395-399`), a ring for `ERROR` (`:402-408`), reduced alpha for `RECHARGING`
(`:411-413`). `STATE_COLORS` exists in `src/utils/colors.js:2-12` and is never
imported by `FleetMap.jsx`.

Also: the robot-ID label and the battery gauge are suppressed below
`LABEL_MIN_SCALE = 0.9` px/m (`FleetMap.jsx:39,326-360`), and the gauge is gated
on the label having been placed (`:454`), so both disappear when zoomed out.

**Impact**: an operator cannot distinguish `IDLE` from `NAVIGATING` from
`SURVEYING` on the map. Full state is available in the detail panel.

---

## D-02 — FR-DASH-2: the heatmap's confidence axis carries no information

**Specified** (`docs/PRD.md:496-504`): opacity proportional to confidence; colour
ramp gray → blue → red.

**Actual**: `FleetMap.jsx:141-143` computes
`α = clamp(0.7 × (1 − sensor_uncertainty), 0.05, 0.7)`. `sensor_uncertainty`
traces back to a **constant** `noise_stddev: 0.5` (`selene_hal/config/scout.yaml:16`)
via `selene_agent/selene_agent/skills/prospect.py:137-157`. Every reading
therefore produces the identical α = 0.35. The opacity axis is inert.

The ramp is dark-blue → blue → cyan → yellow → red (`src/utils/colors.js:55-77`),
with no gray tier.

**Impact**: the heatmap conveys concentration but not confidence. Compounded by
D-09 — it is built client-side from raw per-reading messages, not from the
orchestrator's fused posterior.

---

## D-03 — FR-DASH-3: task status is inferred, and two statuses are unreachable

**Actual**: no task-status topic exists. The whole panel is reconstructed
client-side from `RobotState.current_task_id` transitions
(`selene_dashboard/src/hooks/useFleetState.js:56-130`). The reducer only ever
writes PENDING / ASSIGNED / IN_PROGRESS / COMPLETED, so the `FAILED` and
`INTERRUPTED` states the UI can render are unreachable.

Consequence: a **cancelled** task renders as completed. The orchestrator re-queues
it as PENDING (`orchestrator_node.py:295-299`); the dashboard sees the id drop off
the robot and marks it COMPLETED (`useFleetState.js:99-108`). Any completion that
happens across a page reload is never recorded.

---

## D-04 — FR-DASH-5: the quantity field is discarded, and a targeted task skips the auction

**Actual**: quantity is collected (`TaskInjector.jsx:69`) and carried in
`selene_msgs/srv/InjectTask.srv`, but `inject_task_logic` never reads
`request.quantity` (`orchestrator_node.py:124-232`) and `TaskQueue.add_task` has
no such parameter (`task_queue.py:38-51`). The control is dead end to end.

"Enters the auction" holds only for the unassigned path. With a robot selected,
`orchestrator_node.py:217-227` force-assigns and publishes `TaskAssignment`
directly — no auction runs.

---

## D-05 — FR-DASH-6: overrides are not visible in the task history

**Specified** (`docs/PRD.md:536-544`): override actions logged and visible in the
task history.

**Actual**: overrides land in three places, none of them the task history — a
`FleetAlert` (`orchestrator_node.py:265-269`) shown in `AlertLog.jsx:63-80`; a
five-entry in-memory "Recent Actions" list that is wiped whenever the operator
selects a different robot (`RobotDetail.jsx:75-88` with `key=` at `App.jsx:252`);
and the task queue **deliberately excludes** ids prefixed `override_`
(`useFleetState.js:79,89,99`).

The override mechanism itself works and is verified by the exit gate (checks 7
and 8).

---

## D-06 — FR-DASH-7: the mission progress bar has a structurally zero numerator

**Specified** (`docs/PRD.md:546-554`): progress bar reflects material deposited at
the depot; ice extracted / deposited, fleet distance, energy, uptime.

**Actual**: `MaterialInventory` (`selene_isru/selene_isru/inventory.py:62`) has
**zero production callers** for `register_site`, `record_extraction`,
`record_load` and `record_unload`. It is constructed at
`orchestrator_node.py:410` and read at `:701`, so
`extracted_quantity` / `in_transit_quantity` / `deposited_quantity` are
permanently 0.0. The dashboard detects this and prints "delivered mass not
instrumented" (`MissionProgress.jsx:84,105-113`) rather than showing a false 0 %,
which is honest but is not the acceptance criterion.

**Wiring the inventory up would not fix it.** `mass_kg` is never populated by
either HAL — `selene_hal/selene_hal/gazebo_hal.py:256-261` and
`stub_hal.py:95-96` both build a `FillLevelReading` without it (default 0.0,
`data_types.py:69`). So `excavate.py:151` computes `0.0 - 0.0` and `haul.py:115`
delivers 0.0. There is a companion unit defect: `selene_sim/selene_sim/hopper_node.py:86-88`
publishes **kilograms** into a field documented as a 0–1 fraction
(`data_types.py:67`) and compared against `FILL_THRESHOLD = 0.95`
(`excavate.py:146`) — the hopper reports full at 0.95 kg.

Also in this requirement: fleet uptime has no field in `MissionProgress.msg` and
`FleetMonitor.get_uptime_sec()` (`fleet_monitor.py:154-159`) is never called;
energy uses a fixed 50 Wh capacity for every robot regardless of its RCDL
(`fleet_monitor.py:9,16,65`); "elapsed simulation time" is orchestrator wall-clock
uptime (`orchestrator_node.py:711-712`) because `use_sim_time` is set nowhere in
the repository (0 occurrences).

**This is the most consequential deviation.** It blocks Phase 6 Integration
Demo 1 step 3 (`docs/PRD.md:895`) and SC-1, and it means FR-ISRU-2's acceptance —
extracted equals hauled plus in transit — cannot be demonstrated at all;
`check_conservation()` (`inventory.py:142`) passes trivially as 0 == 0 + 0 and is
never called in production.

---

## D-07 - FR-SIM-7: robot counts and world files not configurable - CLOSED 2026-07-30

**Was**: `simulation.launch.py` declared `num_scouts` / `num_excavators` /
`num_haulers` and then built the fleet from literal `range(2)`, `range(1)`,
`range(1)`. The arguments existed and did nothing. Worse than a no-op:
`unified_sim.launch.py` honours the same arguments for the orchestrator and the
agents and passes them down, so `num_scouts:=3` started a third agent that
registered with the fleet, bid on tasks and won them, with no Gazebo model behind
it. It presented as a coordination bug. The world file and deposit layout were
hardcoded, so clause (d) was unmet too.

**Now**: the file is an `OpaqueFunction`, which is what allows the counts to be
read at all -- a `LaunchConfiguration` cannot be resolved at description time,
which is why the literals were there. Spawn, bridge and sensor nodes are built
from a single fleet list that cannot disagree with itself. `world`,
`ice_config` and `spawn_config` are launch arguments, and
`unified_sim.launch.py` passes all six through.

**No procedural spawn fallback.** Asking for more robots than
`spawn_positions.yaml` describes fails the launch with a message naming the
shortfall and how to survey another pose. Every z in that file is a measured
collision surface plus 0.30 m; inventing one puts a robot inside the terrain,
which is the defect this project spent months on.

So `spawn_positions.yaml` now describes a ten-robot fleet (4 scouts, 3
excavators, 3 haulers), because a configurable count is useless if the config
describes four robots. That is what NFR-1.1 and NFR-1.4 ("up to 10 robots")
need. The six new poses were geometry-checked before being measured -- that
pre-check rejected two candidates at 9.4 m and 8.2 m from the depot, inside its
10 m radius -- then surveyed with `check_terrain.sh` in the same run as the
original four.

**MEASURED, and the first measurement was wrong.** Requesting 4/3/3 initially
reported 5 of 10 models in Gazebo while all ten create nodes logged "Entity
creation successful" -- the signature of querying the wrong server. A leftover
`gz sim` from the previous probe was answering. Re-run with each launch in its
own `GZ_PARTITION` and a straggler check first:

    2/1/1 -> 4 models    scout_01 scout_02 excavator_01 hauler_01
    4/3/3 -> 10 models   all ten, correctly named

`num_scouts:=9` exits 1 naming the file and the shortfall.
`world:=/nonexistent` exits 1 saying so. `check_terrain.sh` reads every entry,
so it now gates all ten poses -- all pass at +0.30/+0.31 m -- and
`check_drive.sh` on `scout_03`, a new pose, drives 98.0% of command and settles
downward.

## D-08 - FR-MAP-4: RViz2 resource-map visualization - CLOSED 2026-07-30

**Was**: nothing existed. `visualization_msgs` had zero occurrences repo-wide;
`selene_sim/rviz/selene_sim.rviz` had two displays (Grid, TF); rviz2 was
launched only from `simulation.launch.py:214-221` behind `rviz:=true`
defaulting false, and `unified_sim.launch.py` - the file the exit gate launches
- had no rviz node. It was also blocked on D-09: no fused posterior existed on
the wire to display.

**Now**: the orchestrator publishes `/orchestrator/resource_map_markers`, a
`visualization_msgs/MarkerArray` holding one `CUBE_LIST` marker with per-cell
`ColorRGBA`, at the same rate and from the same snapshot as the posterior.

Against the four clauses of `docs/PRD.md:451`:

| clause | how |
|---|---|
| (a) OccupancyGrid **or** Marker array | Marker array. `nav_msgs/OccupancyGrid` carries one `int8` per cell, so colour and alpha would both be functions of the same scalar and cannot encode two independent quantities - clause (c) is unrepresentable in it. Verified against the shipped RViz2 library, which exports exactly three compiled-in palettes and one global alpha property. |
| (b) blue (low) to red (high) | A verbatim port of the dashboard's `iceConcentrationColor()` (`selene_dashboard/src/utils/colors.js:52-77`), so the overlay and the dashboard heatmap render the same posterior the same colour - which is what `docs/PRD.md:1504`'s side-by-side comparison requires. Ported, not reinvented. |
| (c) alpha encodes certainty | `variance_to_alpha()`, log-scaled against the map's own prior variance. Log rather than linear because the first reading at a cell takes variance 100 -> ~0.09; on a linear map that is alpha 0.999 and every later reading is lost in the last 0.1% of the range. |
| (d) updates in real time | One timer at `resource_map_publish_rate`; measured live at exactly 0.500 Hz. |

**Measured on the running system** (2026-07-30, ROS 2 Jazzy, full
`unified_sim.launch.py`, 256 readings shaped like `ice_deposits.yaml`):
frame_id `map`, CUBE_LIST, ADD, 3779 points and 3779 colours, scale
(1.0, 1.0, 0.2), `pose.orientation.w = 1.0`, per-point alpha 0.453-0.662, ramp
spanning 233 red-dominant and 3546 blue-dominant cubes. **The acceptance
criterion "matches underlying data" is met concretely: the hottest cell,
7.877 wt%, decodes row-major to world (-80.5, -140.5) - 0.7 m from the
`ice_deposits.yaml` deposit centred (-80, -140) with peak 8.0 wt%.**

Three traps this had to avoid, each of which fails silently:

- RViz2 ignores the per-point `colors` array entirely when its length differs
  from `points`, falling back to the flat `marker.color` with no error. The
  publisher asserts the lengths are equal.
- That fallback `marker.color` defaults to `(0,0,0,0)` - transparent black - so
  a mismatch would have made the overlay *disappear*. It is set to an opaque
  blue so the failure mode is visibly wrong rather than invisible.
- Per-point alpha blending only engages once some colour has `a != 1.0`, and an
  all-zero-alpha CUBE_LIST raises a marker warning. Alpha is clamped to
  [0.05, 0.85].

**Frames.** Nothing in this repo publishes TF - `/tf` and `/tf_static` have
zero publishers. RViz2 can still transform a message whose `frame_id` is
identical to its fixed frame, so the overlay is published in `map` and
`selene_sim/rviz/selene_sim.rviz` now sets `Fixed Frame: map` (it said `odom`,
which no publisher used - the navigator's `nav_msgs/Path` is already stamped
`map`, so that display would not have rendered either). Expect a yellow TF row
in RViz while the tree is empty; the overlay renders regardless.

**Still open, and not an overlay defect**: `ResourceMapUpdate.location` comes
from `/odom`, which DiffDrive dead-reckons from each robot's spawn pose rather
than world coordinates. The map is internally consistent - the neutron
spectrometer evaluates the deposit field at the *same* odom coordinate that
becomes the map index, so every cell holds the true value for its own
coordinate - but which region gets sampled is not where the robot physically
is. Fixing that is a sim-fidelity change with knock-on effects on
`battery_node._is_in_psr()` and navigation, tracked separately from FR-MAP-4.

## D-09 - FR-MAP-1(e)(f): the fused resource map is never published - CLOSED 2026-07-30

**Was**: the orchestrator had exactly four publishers;
`resource_map_publish_rate` was declared at `orchestrator_node.py:379`, set in
`orchestrator_params.yaml`, and never read by anything; `ResourceMap.msg` did
not exist; and the `ResourceMap` class had no serialisation of any kind.

**Now**: `selene_msgs/msg/ResourceMap.msg` exists and the orchestrator
publishes it on `/orchestrator/resource_map` from a timer whose period is
`1.0 / resource_map_publish_rate` - the first timer in the file driven by a
parameter rather than a literal. A rate <= 0 disables publishing with a warning
instead of dividing by zero.

**Sparse snapshot encoding, chosen by measurement.** The grid is 250,000 cells
but only observed ones go on the wire, and every message is a complete snapshot
rather than a delta, so a late or lossy subscriber is correct from the next
message. Measured: 88 bytes of overhead plus 16 bytes per observed cell. A
10-waypoint survey observes ~0.3% of the grid, giving ~12.6 kB against ~3.0 MB
for the equivalent dense float32 grid - a 237x reduction, confirmed by
serialising the real message on Jazzy.

DDS is not what makes the dense form untenable; a 3 MB sample was measured
delivering cross-process over Fast DDS without loss. Two other things are:
rosbridge's `extract_values` burns ~284 ms of GIL-held Python per dense message
per client, in the single process carrying every dashboard topic; and roslibjs
cannot reassemble the fragments rosbridge emits above `max_message_size`, so
oversized messages are dropped client-side in silence. Sparse inverts past ~75%
coverage, which this mission does not approach.

**Anti-regression.** `selene_orchestrator/test/test_no_orphan_parameters.py`
parses `orchestrator_node.py` and fails on any parameter declared but never
read. This requirement was not descoped by anyone - it evaporated because a
parameter existed with nothing behind it and nothing noticed for two phases.
The test carries an explicit allow-list of the two remaining orphans
(`recharge_threshold`, `fleet_state_publish_rate`) so they stay visible.

**Not delivered**: FR-MAP-1(b)'s per-cell last-update timestamp. `ResourceMap`
tracks three grids (mean, variance, count) and no per-cell time, and a per-cell
time array would add ~1 MB per message for a field nothing reads.
`header.stamp` is the map-level acquisition time. That clause remains open.

## D-10 — the exit gate tests less than its report implies

`scripts/validate_phase5.sh` runs eight checks and all eight pass. Mapped against
the PRD's own seven exit-gate rows (`docs/PRD.md:1499-1509`):

| PRD exit-gate row | Coverage |
|---|---|
| Dashboard shows all robots with correct real-time state | weak proxy — counts topic *names* (≥4 ending `/state`), asserts nothing about content, rate, or the dashboard |
| Resource heatmap matches RViz2 visualization | no check (see D-08) |
| Task queue reflects orchestrator state within 1 s | no check — nothing measures dashboard latency |
| Operator-injected task enters auction and gets assigned | partial — injection is via CLI service, not the dashboard, and the script deliberately does not verify assignment; the observed `task_id` is never compared to the injected one, and ten HTN survey tasks are queued at startup, so an announcement appears whether or not the injection worked |
| Robot override (send-to-location) works | tests `force_recharge` instead; `send_to_location` is never exercised |
| Single launch command starts full system | weak proxy — `kill -0` on the launch PID. `ros2 launch` survives child node crashes, so this can pass with Gazebo dead |
| Dashboard renders at 1 Hz with 4 robots without lag | no check — check 2 is `curl` returning 200, which a static file server satisfies with a broken bundle |

One of seven rows has a real end-to-end check (check 8, override → orchestrator →
agent → FSM), and it tests a different override than the row names. Three rows
have weak liveness proxies. Three have no check. Every row's stated *method* in
the PRD is human or visual; none was performed, and no demo recording exists
in-tree (`docs/PRD.md:1511`).

**A green run of `validate_phase5.sh` means: the system launches, rosbridge and a
web server answer, two services accept calls, and one override reaches a robot's
state machine.** It is not by itself evidence that the Phase 5 exit gate was met.

---

---

## FR-MAP-3 - adaptive survey never ran - CLOSED 2026-07-30

Not a Phase 5 deviation: FR-MAP-3 is P0 **Phase 4** scope
(`docs/PRD.md:434-442`), and Phase 4 was recorded as complete. It is listed here
because SC-3 is a Phase 6 acceptance criterion and the gap was found during this
work.

`AdaptiveSurveyPlanner` shipped with 8 green unit tests and zero production call
sites -- `self._adaptive_survey` appeared exactly once in `orchestrator_node.py`,
the assignment that created it. What ran was a fixed hex lattice of 10 points
computed once at decomposition, before any reading existed.

**Wiring it up alone would not have worked.** At the shipped defaults
`min_spacing` (8.0 m) exceeds `ResourceMap._footprint_radius` (5.0 m), so no
admissible candidate has ever been observed -- and `_get_neighbor_signal` probed
at the map *resolution*, 1.0 m, sampling points 7-9 m from the nearest reading,
outside every footprint. Measured over a full survey: `max(signal) == 0.0` on
every one of 10 selections across all ~360-434 candidates, with the variance
term identically `prior_variance` for the same reason. Both terms constant, so
the score collapsed to pure nearest-neighbour. The 8 existing tests passed only
because they use `min_spacing` of 3.0 or 5.0, at or below the footprint radius.

Now: PENDING survey targets are re-scored on a timer at
`adaptive_survey_replan_rate`, with the lattice seeding the first two waypoints;
committed targets (AUCTIONING / ASSIGNED / IN_PROGRESS) are never rewritten;
termination is structural because the function cannot create a task.

SC-3 measured over the real deposit field, deterministic:

    static    first half 2.21 -> second half 3.40 wt%,  60% of second half >=4
    adaptive  first half 3.86 -> second half 5.34 wt%,  80%

1.57x the second-half mean, with waypoints landing 5.0 m from deposit centres at
7.33 wt%. Live on ROS 2 Jazzy the replan fires and logs its re-targets.

**Still true**: readings are indexed in each robot's dead-reckoned odom frame
(see D-08), so "converge on the deposits" is measured in that frame. The map is
self-consistent; the region sampled is not where the robot physically is.


## Recommended disposition

Phase 5 is **code-complete against seven of nine requirements** and its executable
gate passes 8/8 on three consecutive runs (`docs/phase5_validation_report.md`).

It should **not** be recorded as "exit gate passed" without either:

1. closing Phase 5 against this register, with D-01..D-10 accepted explicitly by
   whoever owns the phase; or
2. strengthening checks 1, 2, 4 and 6, adding a `send_to_location` check, and
   performing the PRD's visual methods — then closing on evidence.

Closed on 2026-07-30: D-07, D-08, D-09, and FR-MAP-3. **D-06 is now the only
remaining substantive gap**, and it is the one that propagates: it blocks
Phase 6 Integration Demo 1 step 3 and SC-1, and it is not an orchestrator
one-liner -- no HAL populates `mass_kg`, and `hopper_node.py` publishes
kilograms into a field documented as a 0-1 fraction, so it needs a HAL and
simulation change. D-01..D-05 are defects on delivered dashboard features and
are not Phase 6 blockers.
