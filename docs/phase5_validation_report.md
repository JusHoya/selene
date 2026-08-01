# SELENE Phase 5 Exit Gate Validation Report

_Generated Sat Aug  1 10:54:06 AM CDT 2026_

| | |
|---|---|
| Source commit | `e276e60 (working tree dirty)` |
| Workspace | `/root/selene` |
| ROS 2 | jazzy |
| Gazebo (gz sim) | 8.11.0 |
| OS | Ubuntu 24.04.3 LTS |
| Fleet | 4 robots: scout_01,scout_02,excavator_01,hauler_01 |
| Launch arguments | num_scouts:=2 num_excavators:=1 num_haulers:=1 |

| # | Check | Result | Details |
|---|---|---|---|
| 1 | Single launch command starts the full system | PASS | 23 expected nodes present, sim_time 12394ms -> 15534ms, 4 Gazebo models, 5 topics with a live publisher (ready after 12s) |
| 2 | Dashboard bundle is served and is a compiled application bundle | PASS | via asset-manifest.json: main.7e73716a.js (289054 B); contains ws://localhost:9090 and /orchestrator/inject_task. NO BROWSER RAN: this proves the bundle was served and compiled, not that it executes or renders |
| 3 | rosbridge speaks the websocket protocol | PASS | 6 mission_progress publish frames; largest resource_map frame 362 B, under max_message_size 10000000 B (/rosbridge_websocket parameter) |
| 4 | Robot state content, freshness, rate and fleet membership | FAIL | scout_01: IDLE for 12 samples over 5.0s but its settled samples span 0.061 m (>= 0.05 m; whole run 0.089 m, path 0.138 m) |
| 5 | Operator-injected task accepted | PASS | inject_task via rosbridge websocket (call_service) returned task_id=manual_0000 (queued) |
| 6 | Injected task is announced and assigned, correlated by task_id | FAIL | task manual_0000 was announced 2.47s after injection but was never assigned within the following 15s. 2 assignment(s) of OTHER tasks were seen in that window — the auction ran and this task did not win it (no robot became IDLE in 60s, so scout_01 was freed with an operator cancel_task first — this row was measured on a robot the gate perturbed. the accepted cancel_task response is itself the receipt: the agent returns accepted only after firing OPERATOR_CANCEL, which is an unconditional transition to IDLE; corroborated by an IDLE state sample after the cancel) |
| 7 | Robot override (force_recharge) accepted | PASS | scout_01 force_recharge accepted (override force_recharge accepted) |
| 8 | Robot FSM reaches RECHARGING after force_recharge | PASS | scout_01 fsm_state=RECHARGING 0.0s after the override |
| 9 | Task queue reflects orchestrator state within 1 second | SKIP | task manual_0000 was never assigned, so there is no orchestrator event to react to |
| 10 | Resource heatmap and RViz2 overlay derive from one snapshot | PASS | 1556 observed cells, 1556 cubes with 1556 matching colours, one header stamp, frame 'map'; hottest cell 7.833 wt% (flat index 55169) decodes row-major to world (-80.5, -139.5), 0.71 m from the seeded peak deposit_alpha at (-80.0, -140.0) and 0.71 m from the nearest ice_deposits.yaml centre. THE MAP WAS SEEDED BY THIS PROBE: 49 synthetic ResourceMapUpdate readings shaped like deposit_alpha in ice_deposits.yaml were published to /orchestrator/map_update on a 5 m lattice over +/-15 m, raising total_observations by 3920 (predicted 3920) in 1.7s from a baseline of 0. The fleet did not survey this; the fusion, sparse encoding and marker publishing are the system's own. NO IMAGE COMPARED AND NO RViz2 RUN: this proves the fusion -> sparse-encode -> marker path is correct on this input and that both renderers are functions of the same snapshot through the same colour law. It does NOT prove that robots autonomously survey the deposits |
| 11 | Robot override (send_to_location) drives the robot to the target | PASS | scout_02: accepted send_to_location, reached NAVIGATING under its own override_goto task id, closed 1.02 m of the 5.97 m range to the target in 3.0s (needed 1.00 m); bearing +45 deg off heading 0.268 rad, target (-69.30, -73.56), window 11.0s derived at 0.50 m/s from /root/selene/install/selene_hal/share/selene_hal/config/scout.yaml, pose_source localisation; planned_path ends (-69.50, -73.50), 0.20 m from the commanded target |

## PRD exit-gate coverage

Generated from the PRD_ROWS / ROW_CHECKS mapping in this script, which
`selene_orchestrator/test/test_phase5_gate_coverage.py` pins against
`docs/PRD.md` and `scripts/phase5_probe.py` on every push.

A PASS in the Verdict column means the checks named beside it passed.
It does NOT mean the PRD's stated method was performed — read the
Coverage column, which says what each row's checks do and do not reach.

| PRD exit-gate row (docs/PRD.md:1503-1509) | Covering checks | Coverage | Verdict |
|---|---|---|---|
| Dashboard shows all robots with correct real-time state | 4:FAIL | proxy: message content, rate, freshness and the exact fleet membership the dashboard's own rosapi discovery call returns. No browser renders any of it, so 'shows' is not tested — only that correct state is available to be shown. | FAIL |
| Resource heatmap matches RViz2 visualization | 10:PASS | proxy: both renderers are proven to be functions of ONE snapshot through ONE colour law, and the hottest cell of the fused posterior is proven to decode row-major onto the ice. THE MAP IS SEEDED BY THE GATE to make that second half reachable: the probe publishes synthetic ResourceMapUpdate readings shaped like ice_deposits.yaml onto /orchestrator/map_update, so the fusion, sparse encoding and marker publishing are the system's own but the readings are not. That proves the map pipeline is correct on that input; it does NOT prove that robots autonomously survey the deposits, which is a slower property this gate does not measure. RViz2 is never launched and no image is compared; the recomputation uses selene_orchestrator.resource_map_viz, the same module the publisher used, so a defect inside that module is invisible to this check. | PASS |
| Task queue reflects orchestrator state within 1 second | 9:SKIP | proxy: measured from the orchestrator's TaskAssignment to websocket arrival only. The 2 Hz snapshot carries up to 500 ms of quantisation and the React reducer and canvas draw are unmeasured, so this bounds the row from below — it can prove a violation, not conformance. | SKIP |
| Operator-injected task enters auction and gets assigned | 5:PASS 6:FAIL | end-to-end: the injected task_id is correlated through announcement and assignment with the target matched to 1e-3. Check 5 names the transport actually used; it is the dashboard's own rosbridge call_service path unless it reports the rclpy fallback. No browser issues the call. | FAIL |
| Robot override (send-to-location) works | 11:PASS | proxy: the override is issued over the ROS service and verified through FSM state, the agent's own override_goto_ pseudo-task id, the planned path and odometry. The dashboard's transport and its UI are not exercised. The displacement is read off /<rid>/odom_world, which since 2026-07-31 carries the SIMULATOR'S TRUE WORLD POSE rather than dead reckoning whenever pose_source is localisation (register D-24/D-33) — the check reads that parameter off each world_odom node and prints what it found, and world_odometry_node falls back to dead reckoning only with an ERROR log and a CRITICAL FleetAlert. scripts/check_drive.sh is still the only thing here that asks Gazebo directly. The planned-path assertion is what proves the target itself was honoured. | PASS |
| Single launch command starts full system | 1:PASS 2:PASS 3:PASS | end-to-end: one ros2 launch, then the derived node set, Gazebo stepping with every model present, and publisher counts on the orchestrator's topics. 'Full system' here means the ROS graph plus a served bundle — the dashboard half is check 2, which inspects the bundle and never executes it. | PASS |
| Dashboard renders at 1 Hz with 4 robots without lag | — | not covered | **NOT COVERED** — needs a browser: frame timing and dropped frames are visible only in devtools, and no browser is started anywhere in this gate. Check 2 fetches and inspects the bundle and MUST NOT be read as a proxy for it. |

Checks that cover no PRD row, and why they are kept:

* check 7 (PASS) — force_recharge override, FR-DASH-6. PRD row 5 names send-to-location, which is check 11; this is kept because it was the one end-to-end path the pre-D-10 gate had.
* check 8 (PASS) — the FSM consequence of check 7, kept with it.

**Summary:** 8 passed, 2 failed, 1 skipped.

## What this run does and does not mean

**This run was not green** — 8 passed, 2 failed,
1 skipped — so no positive claim is made here. Read the coverage
table above and the per-check rows: each states what was measured, or the
reason it could not be. The paragraph describing what a green run would mean
is printed only on a green run, deliberately.

**Does not mean.** NO BROWSER IS STARTED ANYWHERE IN THIS GATE. Nothing
here proves the dashboard bundle executes, that React mounts, that roslib
connects, or that a single pixel is drawn — check 2 fetches and inspects
the bundle and is not a substitute for running it. NO IMAGE IS COMPARED
and no RViz2 process runs, so check 10 is not the PRD's "side-by-side
comparison". Every METHOD the PRD names for these rows — visual
inspection, side-by-side comparison, observing robot execution, browser
devtools profiling — is a human method, and none of them was performed.
Check 9 bounds the task-queue latency row from below only: it can prove a
violation, and proves conformance only as far as the websocket, since the
React reducer and canvas draw are unmeasured.

**Check 10 ran on a map this gate seeded.** The probe published 49 synthetic
`selene_msgs/msg/ResourceMapUpdate` readings onto `/orchestrator/map_update`,
shaped like `deposit_alpha` in `selene_sim/config/ice_deposits.yaml`, because a
gate-length run cannot reach the observation count the hottest-cell assertion
needs — a scout drives ~100 m to its first waypoint and returns to base after
every task. Everything downstream of that stimulus is the system's own code:
`_on_map_update`, `ResourceMap.update`'s Bayesian fusion, the sparse encoder,
the colour law and both publishers. So check 10 proves the fusion ->
sparse-encode -> marker path is correct on seeded input, and the map was
perturbed by the measurement. It does **not** prove that robots autonomously
survey the deposits; nothing in this gate measures that.

**Deviations:** see `docs/phase5_deviation_register.md` (D-01..D-10) for
what is delivered, what is deviated, and what remains open.

**Launch log:** /tmp/selene_unified_launch.log
**Probe stderr:** /tmp/selene_phase5_probe.10821.log
**Probe measurements (JSON):** /tmp/selene_phase5_probe.10821.json
