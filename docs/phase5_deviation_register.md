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
| FR-SIM-7 Launch & Config (full) | P0 | Delivered with deviation (D-07) |
| FR-MAP-4 RViz2 Visualization | P1 | **Not delivered** (D-08) |

Seven of nine requirements are code-complete. One is partially delivered
(FR-SIM-7). One was never started (FR-MAP-4).

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

## D-07 — FR-SIM-7: robot counts and world files are not actually configurable

**Specified** (`docs/PRD.md:256-264`): parameterised robot counts; configurable
world file and ice deposit layout.

**Actual**: `simulation.launch.py` declares `num_scouts` / `num_excavators` /
`num_haulers` (`:41-46`) and then spawns with literal `range(2)`, `range(1)`,
`range(1)` (`:125,127,129`; sensor nodes at `:166,180`). `unified_sim.launch.py`
honours the arguments for the orchestrator and agent nodes and passes them to a
launch file that ignores them — so `num_scouts:=3` starts a third agent that bids
on and wins tasks **with no Gazebo model behind it**. The file documents this
itself at `unified_sim.launch.py:21-37`.

The world file and deposit layout are hardcoded at `simulation.launch.py:26,31`
and are not launch arguments.

**Impact**: the fleet cannot be staged above 2/1/1, so NFR-1.1 and NFR-1.4
("up to 10 robots") cannot be exercised in Phase 6 without launch work first.

---

## D-08 — FR-MAP-4: RViz2 resource-map visualization was never implemented

**Specified** (`docs/PRD.md:444-452`, P1, Phase 5 scope at `docs/PRD.md:1175`):
RViz2 display of the resource map, side-by-side comparable with the dashboard
(`docs/PRD.md:1504`).

**Actual — nothing exists.**
- `selene_sim/rviz/selene_sim.rviz` contains exactly two displays, Grid and TF.
  No Map, no MarkerArray, no Path — it would not even render the `nav_msgs/Path`
  the agents already publish.
- `visualization_msgs` has **zero occurrences** repo-wide.
- RViz2 is launched only from `simulation.launch.py:214-221`, gated on
  `rviz:=true`, which defaults to `false` (`:47-48`). `unified_sim.launch.py` —
  the file the exit gate actually launches — has no rviz node at all.

**It is blocked on D-09, not merely unstarted.** There is no fused resource map on
the wire for RViz2 to display.

**Disposition**: carried into Phase 6 as an open requirement, not waived. The
previous claim that the dashboard's canvas heatmap satisfies it does not hold on
its own terms — the PRD criterion is a *side-by-side comparison* of the two
(`docs/PRD.md:1504`), which presupposes both exist, and the heatmap is built from
raw readings rather than the fused posterior (D-09).

---

## D-09 — FR-MAP-1(e)(f): the fused resource map is never published

**Specified** (`docs/PRD.md:421-422`, P0, Phase 3): the resource map published as a
custom `ResourceMap` message at a configurable rate, default 0.5 Hz.

**Actual**: the orchestrator has exactly **four** `create_publisher` calls —
task_announcement, task_assignment, alerts, mission_progress
(`orchestrator_node.py:443-452`). `resource_map_publish_rate` is declared at
`:379` and set in `orchestrator_params.yaml:10` and is **never read**; no timer is
bound to it. `ResourceMap.msg` does not exist — `selene_msgs/msg/` contains seven
messages and that is not one of them. The `ResourceMap` class
(`resource_map.py:6`) has no serialisation method of any kind; its grids are read
only by `htn_planner.py:242-243` for site selection.

This is Phase 3 scope that was never met, surfaced here because it blocks two
Phase 5 items (D-02, D-08). Note FR-MAP-1's own acceptance row tests only grid
initialisation and dimensions, so the requirement could be marked met while (e)
and (f) were unimplemented.

---

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

## Recommended disposition

Phase 5 is **code-complete against seven of nine requirements** and its executable
gate passes 8/8 on three consecutive runs (`docs/phase5_validation_report.md`).

It should **not** be recorded as "exit gate passed" without either:

1. closing Phase 5 against this register, with D-01..D-10 accepted explicitly by
   whoever owns the phase; or
2. strengthening checks 1, 2, 4 and 6, adding a `send_to_location` check, and
   performing the PRD's visual methods — then closing on evidence.

D-06 and D-09 are the two that propagate: both block Phase 6 acceptance criteria,
and neither is an orchestrator one-liner. D-06 needs a HAL and simulation change.
