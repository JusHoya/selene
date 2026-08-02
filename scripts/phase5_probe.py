#!/usr/bin/env python3
"""Phase 5 exit-gate probe — the measuring half of ``scripts/validate_phase5.sh``.

WHY THIS FILE EXISTS
--------------------
Deviation D-10 (``docs/phase5_deviation_register.md``) is that the exit gate
tested less than its report implied. Of the seven PRD exit-gate rows
(``docs/PRD.md:1503-1509``) the old script covered one end to end, three with
liveness proxies, and three not at all. Every one of the missing measurements is
a *rate*, a *freshness*, a *latency*, or a *correlation between two messages* —
and none of those is expressible with ``ros2 topic echo --once``, which samples
one message from a participant created and destroyed for that one call.

So the strengthening had to move into a process that stays alive: one rclpy node
that subscribes to everything up front, keeps a continuous recording window while
the inject and override stimuli are issued at known offsets inside it, and then
evaluates every check against that single recording. That is this file.

Three consequences worth stating plainly, because they are why this is Python
rather than more shell:

* **One DDS participant, not dozens.** ``validate_phase5.sh`` exports
  ``FASTDDS_BUILTIN_TRANSPORTS=UDPv4`` to stop short-lived CLI participants
  exhausting ``/dev/shm`` on WSL2. This probe creates one participant for its
  whole run, so that pressure stays a shell-side problem only.
* **Subscribe before you stimulate.** ``ros2 topic echo --once`` issued after a
  service call cannot see the message that call caused if it arrived during
  discovery. Check 6 (does the *injected* task get announced and assigned?) is
  unanswerable that way, which is why the old check 6 asserted only that *some*
  announcement existed while ten HTN survey tasks were queued at startup.
* **PASS / FAIL / SKIP.** A measurement that could not be taken is a SKIP with a
  reason, never a PASS. See ``validate_phase5.sh``'s exit-code contract.

WHAT THIS FILE DOES NOT DO
--------------------------
No browser is started. Nothing here proves that the dashboard bundle executes,
that React mounts, that roslib connects, or that anything is drawn. PRD row 7
("Dashboard renders at 1 Hz with 4 robots without lag") is reported NOT COVERED
by the shell, and check 2 must never be read as a substitute for it.

EXECUTION PROVENANCE
--------------------
Stated by half, because the two halves of this file have different histories and
a single sentence covering both would be false about one of them.

* **The ROS half — ``ProbeNode``, ``RosbridgeClient``, and checks 3 to 11 — was
  written blind** on a Windows box with no ROS 2, no Gazebo, no rosbridge and no
  browser. It was linted (flake8, 100 columns) and byte-compiled, and every
  constant, topic name, node name, field name and file:line citation in it was
  read out of the working tree, but not one line of it had executed against a
  live system when it was written.

  **It has since been run. REPORTED, not measured here: the operator ran the
  full gate twice against a live 10-robot mission on 2026-07-31**, and those two
  runs are what found the hole this file's ``seed_resource_map`` now closes —
  check 10 reported PASS both times with the detail "0 observed cells, 0 cubes
  ... hottest-cell check skipped: total_observations=0 < 200". The
  seeding path added on 2026-07-31 has never touched ROS either.

* **The seeding half — ``read_ice_config``, ``deposit_field_concentration``,
  ``seed_lattice``, ``seed_resource_map`` and ``evaluate_map_parity`` — was
  executed standalone on 2026-07-31**, on that same Windows box, by importing
  this module (its module-level imports are stdlib only, so it imports with no
  ROS present) and driving those functions against a stand-in ``ProbeNode``
  whose fused grid was the REAL ``selene_orchestrator.resource_map.ResourceMap``
  and whose two messages were built by the REAL
  ``selene_orchestrator.resource_map_viz``, float32 wire encoding included. Ten
  scenarios were run: the happy path (PASS, 1556 cells, hottest cell 7.833 wt%
  at flat index 55169 decoding to (-80.5, -139.5), 0.707 m from the seeded
  ``deposit_alpha`` centre); nothing subscribed to ``/orchestrator/map_update``
  (FAIL); every reading dropped (FAIL); the posterior publishing while the
  overlay does not (FAIL); ``--no-seed-map`` on an empty map (SKIP); a missing
  ice_deposits.yaml with and without seeding (SKIP); 0.5 m and 2.0 m grid
  resolutions (PASS at 0.354 m and 1.414 m, both inside the one-cell
  tolerance); and a map the fleet had already partly filled elsewhere (PASS,
  unchanged hottest cell).

  What that run did **not** involve: no ROS, no rclpy, no DDS, no orchestrator
  process, no rosbridge, and not ``ProbeNode`` itself — the publisher, the
  subscription callbacks and ``get_subscription_count`` were all stood in for.
  It proves the arithmetic, the verdict logic and the report strings. It proves
  nothing about whether a ``ResourceMapUpdate`` published by this node reaches
  the orchestrator on a live system. Treat the first WSL2 run as part of the
  change, not as a formality.
* **The HTTP half — ``_http_get``, ``_bundle_urls``, ``_inspect_bundle`` and
  ``check_dashboard_bundle``, i.e. the whole of check 2 — was executed
  standalone on 2026-07-30**, on that same Windows box, by importing this module
  and calling those four functions against ``python3 -m http.server`` serving
  ``selene_dashboard/build`` — the same static server ``dashboard.launch.py``
  runs for ``prebuilt:=true``. Both discovery paths were exercised (the
  ``asset-manifest.json`` path, and the ``index.html`` fallback against a copy of
  the build with the manifest removed), the bundle was fetched and inspected, the
  HTML-is-not-a-bundle assertion was exercised by feeding ``index.html`` to
  ``_inspect_bundle``, and ``check_dashboard_bundle`` returned PASS.

  What that run did **not** involve: no ROS, no rosbridge, no browser, no
  dashboard process, and not this file's ``Results`` class (a two-method
  stand-in supplied ``set`` and ``measured``). A static file server and this
  module's own urllib code, nothing else. Every note below that says "measured"
  belongs to that run and names it; no other measurement in this file was taken
  by running it.
* **The D-34 and D-35 repairs — ``samples_since``, ``ProbeNode.states_since``,
  ``freeing_receipt``, ``evaluate_idle_motion`` and the whole of check 11 —
  were written on 2026-07-31 on that same Windows box and are IMPLEMENTED AND
  NOT YET DEMONSTRATED.** Their pure halves are unit-tested in the ROS-free
  lane by ``selene_orchestrator/test/test_pick_prospect_robot.py`` and
  ``selene_orchestrator/test/test_phase5_probe_send_to_location.py``, and every
  one of those tests was checked by mutation — each fix was reverted in a copy
  of this file and the corresponding test confirmed to go red. But a green unit
  test is not evidence that a gate measures a running system, which is the
  lesson this whole register is built on. Nothing below has been run against
  ROS, and the numbers the new window rests on (a 0.26 rad/s ACHIEVED yaw rate)
  are n = 1, back-derived from one manoeuvre in one run. Until
  ``scripts/validate_phase5.sh`` runs on WSL2 and checks 6, 9 and 11 report
  PASS or FAIL rather than SKIP, D-34 and D-35 stay OPEN.
* **The EMERGENCY half — ``injection_carries_emergency``, the emergency flag on
  both injection transports, the ``TaskAnnouncement.emergency`` read in
  ``_on_announcement`` and its assertion in check 6, ``queue_snapshots``,
  ``preemption_precondition``, ``preemption_outcome``, ``evaluate_preemption``
  and ``preemption_sentence`` — was written on 2026-08-01 on that same Windows
  box and is IMPLEMENTED AND NOT YET DEMONSTRATED.** Its pure halves are
  unit-tested in the ROS-free lane by
  ``selene_orchestrator/test/test_phase5_probe_emergency.py``. NO PART OF IT HAS
  SEEN A LIVE ORCHESTRATOR: no run of this file has yet issued an emergency
  injection, no ``auction_preempted`` has been observed on
  ``/orchestrator/task_queue``, and the corroboration clause has never returned
  anything but the value a unit test handed it. What it changes is the STIMULUS
  for checks 5 and 6, which is why both rows now state in their own words that
  they measure the emergency path and that the non-emergency path is
  deliberately untested by them.

OUTPUT PROTOCOL
---------------
One line per check on **stdout**::

    CHECK|<n>|<PASS|FAIL|SKIP>|<title>|<details>

Pipe-delimited rather than JSON, because the consumer is bash: ``IFS='|' read -r``
parses this with one builtin, whereas JSON in bash needs either ``jq`` (not a
declared dependency of this repo) or a python3 subprocess per line. The full
structured record — every measured number, not only the ones that fit in a report
cell — is written to ``--json-out``, so nothing is lost by the simpler format.

Progress and diagnostics go to **stderr** and are never parsed.

Exit status: 0 when the probe ran to completion, whatever the checks said (the
shell aggregates verdicts); 3 when the probe itself could not run, in which case
it has still printed a line for every check so the report has no silent holes.
"""

import argparse
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------
# Check catalogue. THIS IS THE SINGLE SOURCE OF TRUTH FOR CHECK TITLES.
#
# selene_orchestrator/test/test_phase5_gate_coverage.py parses these numbers and
# titles out of this file, requires validate_phase5.sh's CHECK_CATALOG to agree
# with them exactly, and requires every one of them to be mapped either to a PRD
# exit-gate row or to the script's explicitly-reasoned EXTRA_CHECKS list. That
# test is to D-10 what test_no_orphan_parameters.py is to D-09: the failure being
# guarded against is a gate covering less than its report implies, with nothing
# connecting the two.
#
# Check 1 belongs to the shell (process and graph liveness through the ros2 and
# gz CLIs) and is deliberately absent here.
# --------------------------------------------------------------------------
CHECK_TITLES = {
    2: 'Dashboard bundle is served and is a compiled application bundle',
    3: 'rosbridge speaks the websocket protocol',
    4: 'Robot state content, freshness, rate and fleet membership',
    5: 'Operator-injected task accepted',
    6: 'Injected task is announced and assigned, correlated by task_id',
    7: 'Robot override (force_recharge) accepted',
    8: 'Robot FSM reaches RECHARGING after force_recharge',
    9: 'Task queue reflects orchestrator state within 1 second',
    10: 'Resource heatmap and RViz2 overlay derive from one snapshot',
    11: 'Robot override (send_to_location) drives the robot to the target',
}

PASS = 'PASS'
FAIL = 'FAIL'
SKIP = 'SKIP'

# ---- Thresholds. Each one is justified where it is used. -----------------

#: RobotState is published on a 0.5 s timer (agent_node.py:253), i.e. 2.0 Hz.
#: 1.8 Hz leaves 10% headroom for scheduler jitter on a loaded WSL2 box.
MIN_STATE_RATE_HZ = 1.8

#: ``now - stamp`` for the newest sample of each robot. Both are the same wall
#: clock: ``use_sim_time`` has zero code occurrences repo-wide, so no node in
#: this system runs on Gazebo time and there is no clock-domain crossing here.
MAX_STATE_AGE_SEC = 1.0

#: Excursion below which a robot counts as stationary, metres.
MOTION_EPS_M = 0.05

#: Consecutive same-state samples required before a motion rule is applied.
MOTION_MIN_SAMPLES = 3

#: Wall-clock span a run of same-state samples must ALSO cover before the
#: stationary rule is applied to it, seconds.
#:
#: MOTION_MIN_SAMPLES used to encode a DURATION. Samples arrived on a fixed
#: 0.5 s timer, so "3 consecutive samples" meant "in this state for about a
#: second". Since D-34 the agent publishes a RobotState at the instant of every
#: FSM transition as well (``selene_agent/selene_agent/agent_node.py:1176``),
#: so a sample count no longer measures a duration: a two-sample IDLE window
#: with one transition sample dropped into it is promoted past the threshold
#: without the robot having been IDLE any longer than before. 0.9 s restores
#: the meaning the count used to carry -- (MOTION_MIN_SAMPLES - 1) x the 0.5 s
#: publish period, less the same 10% jitter headroom MIN_STATE_RATE_HZ already
#: allows against the same nominal rate.
MOTION_MIN_SPAN_SEC = 0.9

#: How long after an IDLE run starts the stationary rule waits before it begins
#: measuring, seconds. One RobotState publish period.
#:
#: THIS IS NOT NEW TOLERANCE. It is the tolerance the 2 Hz sampler was already
#: granting at random, made deterministic. A robot entering IDLE from a moving
#: state is decelerating: ``operator_command.py:126-127`` zeroes the drive
#: command, and the wheels obey it some unmeasured time later. Until D-34 the
#: first sample LABELLED IDLE arrived uniformly 0-0.5 s after the transition,
#: so that stopping transient was excluded from the run by whenever the timer
#: happened to tick. Publishing on the transition puts a sample at the instant
#: of the state change, which would silently make this rule STRICTER than it
#: has ever been -- and strictly on a physical transient nobody in this
#: repository has measured. Excluding one publish period keeps the assertion at
#: the strength it was designed with; motion continuing beyond it is still a
#: FAIL, and the unsettled excursion is reported either way so a genuine
#: stopping defect is visible in the report rather than forgiven in silence.
MOTION_SETTLE_SEC = 0.5

#: PRD row 3: "Task queue reflects orchestrator state within 1 second".
MAX_QUEUE_REACTION_SEC = 1.0

#: How much longer than MAX_QUEUE_REACTION_SEC check 9 keeps looking for the
#: snapshot that carries the assignment, and how often it looks. The margin
#: absorbs the websocket hop and this loop's own poll period so that the
#: measuring apparatus cannot be what fails a conforming system. It decides only
#: how long to WAIT: a reaction that lands inside the margin but outside
#: MAX_QUEUE_REACTION_SEC is still a FAIL.
QUEUE_POLL_MARGIN_SEC = 0.5
QUEUE_POLL_INTERVAL_SEC = 0.05

#: DDS plus rosbridge only, from a message's own stamp to websocket arrival.
MAX_TRANSPORT_LATENCY_SEC = 0.25

#: A compiled bundle for this app measured 282,106 bytes when it was fetched
#: over HTTP by the 2026-07-30 run described in the module docstring. 100 kB is
#: far below that and far above any error page or SPA fallback. The build's
#: content hash changes on every rebuild, so that figure is evidence of SCALE,
#: not an expected filename or an exact size to compare against.
MIN_BUNDLE_BYTES = 100 * 1024

#: Literals that must appear in the served bundle. Both were observed present in
#: the fetched body by the 2026-07-30 run described in the module docstring.
#: They separate "a JavaScript file was served" from "the SELENE dashboard was
#: served".
BUNDLE_LITERALS = ('ws://localhost:9090', '/orchestrator/inject_task')

#: rosbridge fragments a sample above this size and roslibjs cannot reassemble
#: the fragments — both silently. D-09 chose the sparse ResourceMap encoding
#: specifically to stay under it. Read from the rosbridge node's own parameter
#: when possible; this is the documented rosbridge_suite default used when not.
DEFAULT_ROSBRIDGE_MAX_MESSAGE_SIZE = 10000000

#: The nav grid is 1.0 m (selene_agent/config/nav_params.yaml:2) and
#: AStarPlanner returns CELL CENTRES, so a planned path's last pose is up to
#: 0.707 m from a commanded target that is not itself a cell centre. See
#: run_send_to_location.
NAV_GRID_RESOLUTION_M = 1.0

# ---- Check 11's kinematics. The whole argument is in run_send_to_location. --
#
# D-35: check 11 used to command a target 6 m due EAST of the robot and give it
# a flat 12.0 s to show a positive displacement dot product. The fleet spawns at
# x = -45 and drives south-west, so "due east" was a ~165 deg about-turn every
# run; the register measured the sign crossing at t ~= 10.2 s against that 12 s
# window and the two gate runs landed either side of it, 33 cm apart. The window
# was not widened. It was deleted, and replaced by a bearing chosen relative to
# the robot's own heading plus a window derived from the vehicle's kinematics.

#: How far from the robot the commanded target is placed, metres. Unchanged.
GOTO_RANGE_M = 6.0

#: Bearings tried, degrees RELATIVE TO THE ROBOT'S CURRENT HEADING, in order.
#: Why not 0 and not 180: see goto_target().
GOTO_BEARINGS_DEG = (45.0, -45.0, 90.0, -90.0)

#: Range closure that counts as "drove toward the target", metres. One nav grid
#: cell: below one cell the robot has not provably left the cell it started in,
#: and assertion (4) already tolerates 0.707 m of cell-centre quantisation.
#: This REPLACES a sign test on a dot product, which any favourable millimetre
#: satisfied -- it is a strictly stronger assertion, not a relaxed one.
GOTO_CLOSURE_M = NAV_GRID_RESOLUTION_M

#: Yaw rate the vehicle ACHIEVES, rad/s. Not the 1.0 rad/s PathFollower
#: commands (``selene_agent/selene_agent/navigator.py:477``); about 26% of it.
#:
#: DERIVED, by arithmetic EXECUTED on D-35's three measured figures rather than
#: by a new measurement: a 164.8 deg sweep whose maximum excursion was 3.745 m
#: at 0.5 m/s closes on one constant-curvature arc of radius
#: 3.745 / (2 sin(164.8/2)) = 1.889 m, i.e. 0.5/1.889 = 0.2647 rad/s; the
#: register's ~10.2 s crossing gives 1.953 m and 0.2560 rad/s the same way.
#: n = 1: one scout, one manoeuvre, one run. GOTO_KINEMATIC_DERATE exists to
#: cover exactly that, and the right permanent fix is to record the achieved
#: yaw rate as measured data on every gate run and revisit this when n > 1.
GOTO_MEASURED_YAW_RATE_RAD_S = 0.26

#: One named safety factor on the whole kinematic model above, because every
#: number in it is n = 1. Applied to the derived manoeuvre time, never to the
#: distance the robot must actually cover.
GOTO_KINEMATIC_DERATE = 2.0

#: Dead time allowed before the derived manoeuvre time starts, seconds: the
#: unconditional drive stop (``operator_command.py:126-127``), one 10 Hz agent
#: tick, and one 2 Hz state sample.
GOTO_SETTLE_S = 1.0

#: Displacement from the baseline below which the robot has not moved at all,
#: metres. Well below the 0.15 m even an excavator running at 10% of its
#: nominal 0.3 m/s would cover in GOTO_STALL_S.
GOTO_MOTION_EPS_M = 0.05

#: How long a robot may show no motion at all before check 11 stops waiting,
#: seconds. PathFollower's own ``stall_timeout`` default
#: (``navigator.py:478``), so the probe gives up no sooner than the follower
#: does. This does NOT false-fire during the turn: PathFollower scales linear
#: speed by 0.3 at a heading error above 45 deg but the product is still
#: clamped to max_speed at a 6 m goal (``navigator.py:542-549``), so the robot
#: drives an arc from the first tick and never turns on the spot.
GOTO_STALL_S = 5.0

#: Total wall clock across all bearings, seconds. The same budget the old
#: docstring already declared for its worst case, 4 x (15 s service timeout +
#: 3 s to NAVIGATING + 12 s window); nothing here buys more gate time.
GOTO_BUDGET_S = 120.0

#: How long a bearing has to produce a NAVIGATING sample carrying an
#: ``override_goto_`` task id before it is treated as unplannable, seconds.
GOTO_NAVIGATING_S = 3.0

#: How long after the override response a NAVIGATING sample may still carry a
#: FOREIGN task id, seconds. Two 0.5 s publish periods, by which time both the
#: on-transition publish (D-34) and the next timer publish must have carried
#: the new id. Beyond it, the agent is navigating something that is not this
#: override and that is a FAIL, not a retry.
GOTO_TASK_ID_GRACE_S = 1.0

#: Slowest RCDL max_speed in the fleet (``selene_hal/config/excavator.yaml:3``).
#: Used ONLY when the RCDL cannot be read, and reported whenever it is used.
GOTO_DEFAULT_MAX_SPEED_MPS = 0.3

#: Distinct state samples required before check 11 will return any motion
#: verdict. Fewer than this is a SKIP -- the D-34 rule: an instrument that
#: cannot see must say so rather than blame the system.
GOTO_MIN_SAMPLES = 4

#: How often the motion loop re-evaluates, seconds.
GOTO_POLL_INTERVAL_SEC = 0.25

#: Charge fraction check 11 requires ON TOP OF the agent's own
#: ``energy_critical_threshold`` before it will command a robot.
#:
#: DERIVED, from arithmetic register entry D-42 already established for a scout:
#: the largest draw that robot's own sim model can produce is about 235 W
#: against a 50 Wh pack, i.e. about 4.7 percentage points per minute, and the
#: longest window ``goto_window_seconds`` produces at the shipped bearings is
#: 19.8 s (excavator at 90 deg) -- about 1.6 points. 5 points is roughly 3x
#: that. n = 1 on the power model, which is why the margin is 3x rather than
#: 1.1x, and why it is a named constant and not a bare number.
GOTO_MIN_BATTERY_MARGIN = 0.05

#: ``energy_critical_threshold``'s DECLARED DEFAULT in
#: ``selene_agent/selene_agent/agent_node.py``. Used ONLY when ``/agent_<rid>``
#: does not answer a parameter read, and named in the report whenever it is
#: used -- the same rule ``read_rcdl_max_speed`` follows.
GOTO_DEFAULT_CRITICAL_THRESHOLD = 0.15

#: FSM states in which a robot is ALREADY under a rule that outranks the
#: operator command check 11 issues, so commanding it would measure the rule and
#: not the override.
#:
#: RETURNING and RECHARGING are what the energy rules produce. OFFLINE and ERROR
#: are refused by ``operator_command_logic`` itself, so commanding them measures
#: nothing. On 2026-08-01 the subject was in RETURNING at selection and this
#: list did not exist; see register D-42.
GOTO_UNFIT_STATES = ('OFFLINE', 'ERROR', 'RETURNING', 'RECHARGING')

#: Rejection reasons that are ABOUT THE GATE rather than about the fleet.
#: Spelled as constants because ``select_goto_robot`` writes them and
#: ``goto_no_subject_verdict`` reads them to decide FAIL versus SKIP, and a
#: drifting literal across that boundary would silently turn a system failure
#: into a skipped measurement.
GOTO_RESERVED_REASON = 'reserved for check 7 (force_recharge)'
GOTO_NO_STATE_REASON = 'publishes no state'

#: How long ``pick_prospect_robot`` looks for durable corroboration that the
#: robot it cancelled really was freed, seconds. Unchanged in value from the
#: settle loop it replaces; what changed is that its expiry is no longer a
#: verdict. See freeing_receipt().
FREE_CORROBORATION_SEC = 10.0

# ---- Checks 5 and 6: the EMERGENCY injection. -----------------------------
#
# The stimulus for these two rows changed on 2026-08-01. It is now an EMERGENCY
# operator injection, and that is a change to the orchestrator's auction
# semantics rather than a defect fix, so the rows have to say what they now
# measure and what they deliberately no longer measure. Everything in this block
# exists to keep those two sentences identical wherever they are printed.

#: What "emergency" means, in one sentence. Spelled once because checks 5 and 6
#: describe the SAME stimulus in the same report, and two hand-written
#: paraphrases of one semantics change is how a reader ends up believing the
#: gate tested two different things.
EMERGENCY_SEMANTICS = (
    'emergency=True means the orchestrator MAY abort an auction that is '
    'already in flight and announce this task in the same 0.5s tick instead of '
    'waiting for that auction to resolve — a deliberate change to auction '
    'semantics, not a defect fix')

#: Said by BOTH rows, because a reader who sees only one of them must still be
#: told what this gate did not measure. The old behaviour is still the behaviour
#: of every non-emergency injection, including every priority-10 one, and
#: nothing in this gate exercises it.
EMERGENCY_NOT_TESTED = (
    'a NON-emergency priority-10 injection keeps the old wait-your-turn '
    'behaviour and is deliberately NOT exercised by this row')

#: ``/orchestrator/task_queue``, spelled once. It now has two readers — check
#: 9's reaction latency and check 6's preemption corroboration — and a literal
#: that drifted between them would leave one of them silently measuring an empty
#: buffer, which is a PASS-shaped failure.
TASK_QUEUE_TOPIC = '/orchestrator/task_queue'

#: The ``TaskStatus.status`` a queue entry carries while its auction is open.
QUEUE_STATUS_AUCTIONING = 'AUCTIONING'

#: ``selene_orchestrator.task_feed.AUCTION_PREEMPTED``. Duplicated here rather
#: than imported: this file's module-level imports are stdlib only by design, so
#: that it imports on a box with no ROS and the ROS-free lane can pin its pure
#: halves. The duplication is guarded — ``test_phase5_probe_emergency.py``
#: compares this literal against ``task_feed``'s own when that package is
#: importable, and ``importorskip``s when it is not (register D-36). Without
#: that guard a drift here would turn the corroboration clause into a permanent
#: "not corroborated", i.e. a FAIL naming the wrong system.
AUCTION_PREEMPTED = 'auction_preempted'

#: How stale the newest ``/orchestrator/task_queue`` snapshot before the
#: injection may be and still be read as describing the injection instant,
#: seconds. The snapshot comes off a 2 Hz timer, so this is four periods:
#: enough that scheduler jitter or one dropped websocket frame does not void the
#: clause, short enough that a snapshot from a different phase of the run cannot
#: stand in for the injection. Past it the clause is NOT APPLICABLE and asserts
#: nothing — a gate must not certify what it did not measure.
PREEMPT_SNAPSHOT_STALENESS_SEC = 2.0

#: The orchestrator's auction-tick period, seconds —
#: ``OrchestratorNode.__init__``'s ``create_timer(0.5, self._auction_tick)``.
#:
#: WHY THE CLAUSE NEEDS IT, AND WHY MAX_TRANSPORT_LATENCY_SEC WAS NOT ENOUGH.
#: A preemption can only happen on a tick, and the first tick after the
#: injection lands up to one whole period later. Proving an auction was still
#: open AT the injection therefore proves nothing about whether the orchestrator
#: ever got a chance to preempt it: with 0.05 s of window left the orchestrator
#: correctly takes ``_auction_tick``'s ``is_timed_out`` branch, resolves the
#: auction and preempts nothing — exactly as specified — and a clause with no
#: tick margin would call that a FAIL. MAX_TRANSPORT_LATENCY_SEC is 0.25 and is
#: there for websocket arrival lag; borrowing it would cover half a period and
#: would be borrowing a number for a purpose it was not measured for.
#:
#: Requiring the auction to still be open one full period after the injection is
#: STRICTER, not looser: it makes the clause say NOT APPLICABLE on runs where it
#: previously named a victim, and NOT APPLICABLE asserts nothing.
ORCHESTRATOR_AUCTION_TICK_SEC = 0.5

#: Verdicts of the preemption corroboration clause.
#:
#: NOT_APPLICABLE asserts nothing and can never fail a row. NOT_CORROBORATED is
#: a FAIL. THERE IS DELIBERATELY NO VALUE THAT PASSES CHECK 6: the clause only
#: ever adds a problem or a sentence, and the row is passed by its own
#: announcement/assignment correlation or not at all. A corroboration that could
#: pass a row on its own would be a second, weaker definition of check 6 hiding
#: inside the first.
PREEMPT_CORROBORATED = 'corroborated'
PREEMPT_NOT_APPLICABLE = 'not_applicable'
PREEMPT_NOT_CORROBORATED = 'not_corroborated'

#: visualization_msgs/Marker constants, spelled out so this file needs no
#: message class to interpret a recorded marker.
MARKER_CUBE_LIST = 6
MARKER_ADD = 0

# ---- Check 10's seed. The whole argument is in seed_resource_map(). -------

#: Pitch and half-extent of the seeded reading lattice, metres, laid out around
#: the strongest deposit in ice_deposits.yaml. 5.0 m over +/-15.0 m is 7x7 = 49
#: readings.
#:
#: THESE TWO NUMBERS WERE CHOSEN BY MEASUREMENT, NOT BY TASTE, and the
#: near-misses matter more than the winner. The quantity check 10 asserts is
#: *which cell the fused posterior peaks in*, and the fused posterior is a 5 m
#: Gaussian smoothing (ResourceMap footprint_radius 5.0, footprint_sigma 3.0) of
#: a field whose own sigma is 12 m — so its top is nearly FLAT and the argmax is
#: decided by small effects. MEASURED 2026-07-31 on the Windows box by running
#: the real ``ResourceMap`` + ``resource_map_viz`` offline over a sweep of
#: lattice geometries, decoding the argmax through the float32 wire encoding:
#:
#:     pitch 5.0 half 15.0   0.707 m from the centre, margin 0.0389 wt%   <- this
#:     pitch 5.0 half 10.0   0.707 m,                 margin 0.0389 wt%
#:     pitch 5.0 half 20.0   0.707 m,                 margin 0.0389 wt%
#:     pitch 6.0 half 18.0   0.707 m,                 margin 0.0     (a tie)
#:     pitch 4.0 half 12.0   2.121 m  -- would FAIL the tolerance below
#:     pitch 2.0 half  4.0   2.915 m  -- would FAIL, and by a plateau: the top
#:                                       ten cells spanned 0.7-4.9 m
#:
#: "margin" is the gap between the hottest cell and the runner-up. 0.0389 wt% is
#: about 7e4 float32 quanta at 7.8 wt%, so the ordering is not a numerical
#: coin-flip; the 6.0/18.0 row, which lands in the right place with margin
#: exactly 0.0, is the shape to avoid even though its distance passes.
#:
#: The same sweep found the result invariant to sensor sigma (0.1 to 2.0 wt%
#: all give 0.707 m), invariant to unrelated pre-existing readings elsewhere in
#: the grid, and proportional to resolution (0.354 m at 0.5 m cells, 1.414 m at
#: 2.0 m cells) — which is why the tolerance below is one resolution rather than
#: a fixed metre count.
SEED_LATTICE_PITCH_M = 5.0
SEED_LATTICE_HALF_EXTENT_M = 15.0

#: Sigma put on every seeded reading, wt%. The shipped scout's RCDL
#: ``noise_stddev`` (selene_hal/config/scout.yaml:16), which is what
#: GazeboScalarFieldSensor reports as ``ScalarFieldReading.uncertainty``
#: (gazebo_hal.py:118) and therefore what a real ResourceMapUpdate carries.
#: Using the real figure keeps the posterior VARIANCE — and so the overlay's
#: alpha channel — in the band a real survey produces; the posterior MEAN is a
#: precision-weighted average and is insensitive to it.
SEED_SENSOR_SIGMA_WT = 0.5

#: ``scout_id`` on every seeded reading. Not a robot id, deliberately: it is
#: what an orchestrator log line or a rosbag replay shows if anyone later asks
#: where these readings came from.
SEED_SCOUT_ID = 'phase5_probe_seed'

#: Gap between seeded publishes, seconds. The orchestrator subscribes to
#: /orchestrator/map_update with KEEP_LAST depth 10 (orchestrator_node.py:1096),
#: so a burst faster than its executor drains is droppable. MEASURED on the
#: Windows box: ``ResourceMap.update()`` costs 0.23 ms per reading at the
#: shipped footprint, so 30 ms is ~130x the work each message causes and the
#: whole 49-reading pattern takes 1.5 s to emit.
SEED_PUBLISH_INTERVAL_SEC = 0.03

#: How long to wait for the orchestrator's subscription to appear on the
#: probe's /orchestrator/map_update publisher before giving up on seeding.
SEED_MATCH_TIMEOUT_SEC = 20.0

#: How long to wait for a ResourceMap snapshot that carries the seed. The map
#: publishes at resource_map_publish_rate (0.5 Hz shipped), so one period is 2 s
#: and this is ~12 periods of margin on a loaded box.
SEED_SETTLE_TIMEOUT_SEC = 25.0

#: Observations the fused map must hold before the hottest-cell assertion is
#: allowed to mean anything. Unchanged in value from the threshold this file
#: has always used; what changed is the CONSEQUENCE of falling below it. It was
#: a note attached to a PASS, which is how check 10 passed on a completely empty
#: map twice; it is now a FAIL (seeded run) or a SKIP (--no-seed-map), never a
#: PASS.
MIN_MAP_OBSERVATIONS = 200


def _sanitise(text):
    """Make *text* safe for the pipe-delimited stdout protocol."""
    return str(text).replace('|', '/').replace('\n', ' ').replace('\r', ' ')


def log(msg):
    sys.stderr.write('[probe] %s\n' % (msg,))
    sys.stderr.flush()


class Results:
    """Verdict store, written from two threads (check 2 runs concurrently).

    Every check starts as a SKIP with a reason. Pre-seeding matters: if the
    probe dies half way through, the shell still receives a line for every
    check and the report has no silent holes — a missing row and a passing row
    look identical to anyone skimming a table.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._verdicts = {}
        self._data = {}
        for number in CHECK_TITLES:
            self._verdicts[number] = (SKIP, 'probe did not reach this check')

    def set(self, number, result, details, **data):
        if number not in CHECK_TITLES:
            raise KeyError('undeclared check number %r' % (number,))
        with self._lock:
            self._verdicts[number] = (result, details)
            if data:
                self._data.setdefault(number, {}).update(data)

    def measured(self, number, **data):
        """Record numbers for --json-out without changing the verdict."""
        with self._lock:
            self._data.setdefault(number, {}).update(data)

    def emit(self, stream=sys.stdout):
        with self._lock:
            rows = sorted(self._verdicts.items())
        for number, (result, details) in rows:
            stream.write('CHECK|%d|%s|%s|%s\n' % (
                number, result,
                _sanitise(CHECK_TITLES[number]), _sanitise(details)))
        stream.flush()

    def as_dict(self):
        out = {}
        with self._lock:
            for number, (result, details) in self._verdicts.items():
                out[str(number)] = {
                    'title': CHECK_TITLES[number],
                    'result': result,
                    'details': details,
                    'measured': self._data.get(number, {}),
                }
        return out


# ==========================================================================
# Check 2 — the dashboard bundle. No ROS, no browser.
# ==========================================================================

def _http_get(url, timeout):
    """Return (status, lowercased_headers, body_bytes); raises on transport error.

    HEADER NAMES ARE LOWER-CASED HERE, and that is load-bearing rather than
    tidy. HTTP header names are case-insensitive and servers disagree about
    which case they send. ``python3 -m http.server`` — exactly what
    ``dashboard.launch.py`` runs for ``prebuilt:=true`` — sends
    ``Content-type``, lower-case "t", because CPython's
    ``SimpleHTTPRequestHandler.send_head`` spells the literal that way
    (confirmed by reading ``inspect.getsource`` of it: the only line is
    ``self.send_header("Content-type", ctype)``). A plain
    ``dict(response.headers)`` keyed on ``'Content-Type'`` therefore misses it
    and check 2 FAILS on a perfectly good bundle.

    Both halves of that were OBSERVED, not argued, by the 2026-07-30 run in the
    module docstring: the served header names came back
    ``['Server', 'Date', 'Content-type', 'Content-Length', 'Last-Modified']``
    and ``'Content-Type' in dict(response.headers)`` was ``False``.

    The header VALUE is not asserted anywhere and must not be: it came back
    ``application/javascript`` on that Windows box, where the ``.js`` mapping is
    read from the registry, while a Linux CPython >= 3.12 answers
    ``text/javascript``. ``_inspect_bundle`` therefore tests only that the value
    contains ``javascript``.
    """
    request = urllib.request.Request(url, headers={'Accept': '*/*'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        headers = {name.lower(): value
                   for name, value in response.headers.items()}
        return response.getcode(), headers, response.read()


def _bundle_urls(base_url, timeout):
    """Locate the entry-point JavaScript asset(s) of the served dashboard.

    Two modes, matching selene_sim/launch/dashboard.launch.py:
      * ``prebuilt:=true`` serves selene_dashboard/build, which contains
        asset-manifest.json with a ``files`` map whose ``main.js`` entry is the
        entry-point path;
      * ``prebuilt:=false`` runs react-scripts, which serves a dev bundle and no
        manifest, so the ``<script src=...>`` in index.html is the only handle.

    BOTH PATHS WERE EXERCISED by the 2026-07-30 run in the module docstring —
    the manifest path against ``selene_dashboard/build`` itself, and the
    index.html path against a copy of that build with ``asset-manifest.json``
    removed. Each returned the same single absolute URL, tagged with the source
    it came from, which is the string the report row names. The manifest's
    ``main.js`` value is NOT quoted here: it embeds a content hash that changes
    on every ``npm run build``, and a comment pinning one would be stale by the
    next rebuild.
    """
    base = base_url.rstrip('/')
    try:
        status, _headers, body = _http_get(base + '/asset-manifest.json',
                                           timeout)
        if status == 200:
            manifest = json.loads(body.decode('utf-8', 'replace'))
            main_js = (manifest.get('files') or {}).get('main.js')
            if main_js:
                return [base + main_js], 'asset-manifest.json'
    except (urllib.error.URLError, ValueError, OSError):
        pass

    status, _headers, body = _http_get(base + '/index.html', timeout)
    if status != 200:
        raise urllib.error.URLError('index.html returned HTTP %s' % (status,))
    srcs = re.findall(r'<script[^>]+src="([^"]+\.js)"',
                      body.decode('utf-8', 'replace'))
    if not srcs:
        raise urllib.error.URLError('index.html references no .js asset')
    return [base + s if s.startswith('/') else base + '/' + s
            for s in srcs], 'index.html'


def _inspect_bundle(url):
    """Return a list of problem strings and the asset size in bytes."""
    try:
        status, headers, body = _http_get(url, timeout=30.0)
    except (urllib.error.URLError, OSError) as exc:
        return ['%s unreachable (%s)' % (url, exc)], 0

    problems = []
    content_type = str(headers.get('content-type', '')).lower()
    head = body[:16].lstrip().lower()
    if status != 200:
        problems.append('%s HTTP %s' % (url, status))
    if 'javascript' not in content_type:
        problems.append('%s Content-Type %r' % (url, content_type))
    if len(body) < MIN_BUNDLE_BYTES:
        problems.append('%s only %d bytes' % (url, len(body)))
    if head.startswith(b'<!doctype') or head.startswith(b'<html'):
        # An SPA-fallback server answers 200 with index.html for a missing
        # asset. Without this assertion that is a PASS. Exercised directly by
        # the 2026-07-30 run in the module docstring: this function was pointed
        # at the served index.html and returned five independent problems for
        # it — Content-Type text/html, only 619 bytes, "served HTML, not a
        # bundle", and one per absent BUNDLE_LITERALS string.
        problems.append('%s served HTML, not a bundle' % (url,))
    text = body.decode('utf-8', 'replace')
    for literal in BUNDLE_LITERALS:
        if literal not in text:
            problems.append('%s lacks %r' % (url, literal))
    return problems, len(body)


def check_dashboard_bundle(results, base_url, deadline_sec):
    """Check 2. Runs on its own thread; see the note in ``main``.

    EXPECTED WALL CLOCK: under a second against a prebuilt bundle
    (``prebuilt:=true``, a python http.server over selene_dashboard/build); up
    to about two minutes against the react-scripts dev server, which must
    compile the bundle before port 3000 answers at all. That is exactly why this
    runs concurrently with the ROS recording window: in the old script it was
    moved to the very end for the same reason and still added its full compile
    time to the run.

    WHAT A PASS MEANS, EXACTLY: an HTTP server on this port served a JavaScript
    asset large enough to be a real bundle, which is not an HTML error page or
    an SPA fallback, and which contains this application's own rosbridge URL and
    inject-task service name. WHAT IT DOES NOT MEAN: no browser executed it.
    React may still fail to mount and roslib may still fail to connect. PRD row
    7 is NOT COVERED by this gate and this check is not a proxy for it.
    """
    end = time.time() + deadline_sec
    last_error = 'no attempt made'
    attempt = 0
    while time.time() < end:
        attempt += 1
        try:
            urls, source = _bundle_urls(base_url, timeout=10.0)
        except (urllib.error.URLError, OSError) as exc:
            last_error = 'no page: %s' % (exc,)
            time.sleep(3.0)
            continue

        problems = []
        checked = []
        for url in urls:
            asset_problems, size = _inspect_bundle(url)
            problems.extend(asset_problems)
            checked.append((url, size))

        results.measured(2, assets=[{'url': u, 'bytes': n} for u, n in checked],
                         discovered_via=source, attempts=attempt)
        if problems:
            results.set(2, FAIL, 'via %s: %s' % (source, '; '.join(problems)))
        else:
            served = ', '.join('%s (%d B)' % (u.rsplit('/', 1)[-1], n)
                               for u, n in checked)
            results.set(
                2, PASS,
                'via %s: %s; contains %s. NO BROWSER RAN: this proves the '
                'bundle was served and compiled, not that it executes or '
                'renders' % (source, served, ' and '.join(BUNDLE_LITERALS)))
        return
    results.set(2, FAIL, 'port never served a usable page in %.0fs (%s)'
                % (deadline_sec, last_error))


# ==========================================================================
# The rosbridge websocket client.
# ==========================================================================

class RosbridgeClient:
    """Minimal rosbridge v2 protocol client over tornado.

    WHY TORNADO. ``rosbridge_server`` depends on ``python3-tornado``, so a
    websocket client is already installed wherever rosbridge runs. ASSUMED, NOT
    CONFIRMED: that dependency was read from rosbridge_suite's packaging, not
    observed in the gate environment. If the import fails, every websocket-borne
    measurement degrades to a SKIP with a reason and the injection falls back to
    the ROS service — never silently, because the transport actually used is
    named in the report row.

    WHY ITS OWN THREAD. Two event loops on two threads is the same number of
    loops however they are arranged; putting *both* the IOLoop and the rclpy
    executor off the main thread leaves ``main()`` as a plain linear timeline —
    issue stimulus, wait, read what was recorded — which is the part that has to
    be right by reading. Cross-thread sends go through ``IOLoop.add_callback``,
    the one tornado API documented as safe to call from another thread.
    """

    def __init__(self, url):
        self.url = url
        self.available = False
        self.connected = threading.Event()
        self.error = ''
        self._lock = threading.Lock()
        self._frames = []            # (arrival_wall_time, topic, msg, nbytes)
        self._service_replies = {}
        self._reply_events = {}
        self._conn = None
        self._io_loop = None
        self._thread = None
        self._seq = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self, timeout_sec):
        try:
            import tornado                              # noqa: F401
        except ImportError as exc:
            self.error = 'tornado not importable: %s' % (exc,)
            return False
        self._thread = threading.Thread(target=self._run, name='rosbridge-ws',
                                        daemon=True)
        self._thread.start()
        self.connected.wait(timeout_sec)
        self.available = self.connected.is_set() and self._conn is not None
        if not self.available and not self.error:
            self.error = 'no websocket connection within %.0fs' % (timeout_sec,)
        return self.available

    def _run(self):
        import asyncio

        from tornado.ioloop import IOLoop
        from tornado.websocket import websocket_connect

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._io_loop = IOLoop.current()

        async def connect():
            try:
                self._conn = await websocket_connect(
                    self.url, on_message_callback=self._on_message)
            except Exception as exc:
                self.error = 'websocket_connect failed: %s' % (exc,)
            finally:
                self.connected.set()

        self._io_loop.add_callback(connect)
        self._io_loop.start()

    def stop(self):
        if self._io_loop is not None:
            self._io_loop.add_callback(self._io_loop.stop)

    # -- protocol ----------------------------------------------------------

    def _on_message(self, raw):
        # tornado delivers None when the peer closes the connection.
        if raw is None:
            self.error = self.error or 'websocket closed by peer'
            return
        arrived = time.time()
        nbytes = len(raw if isinstance(raw, bytes) else raw.encode('utf-8'))
        try:
            frame = json.loads(raw)
        except ValueError:
            return
        op = frame.get('op')
        if op == 'publish':
            with self._lock:
                self._frames.append(
                    (arrived, frame.get('topic', ''), frame.get('msg'), nbytes))
        elif op == 'service_response':
            call_id = frame.get('id', '')
            with self._lock:
                self._service_replies[call_id] = frame
                event = self._reply_events.get(call_id)
            if event is not None:
                event.set()

    def _send(self, obj):
        if self._conn is None or self._io_loop is None:
            return False
        self._io_loop.add_callback(self._conn.write_message, json.dumps(obj))
        return True

    def subscribe(self, topic, msg_type):
        return self._send({'op': 'subscribe', 'topic': topic,
                           'type': msg_type, 'throttle_rate': 0,
                           'queue_length': 0})

    def call_service(self, service, srv_type, args, timeout_sec):
        """Blocking service call over the websocket. Returns the reply frame."""
        self._seq += 1
        call_id = 'probe-%d' % (self._seq,)
        event = threading.Event()
        with self._lock:
            self._reply_events[call_id] = event
        if not self._send({'op': 'call_service', 'id': call_id,
                           'service': service, 'type': srv_type,
                           'args': args}):
            return None
        if not event.wait(timeout_sec):
            return None
        with self._lock:
            return self._service_replies.get(call_id)

    # -- recorded frames ---------------------------------------------------

    def frames(self, topic=None):
        with self._lock:
            if topic is None:
                return list(self._frames)
            return [f for f in self._frames if f[1] == topic]

    def max_frame_bytes(self, topic):
        sizes = [f[3] for f in self.frames(topic)]
        return max(sizes) if sizes else 0


# ==========================================================================
# The rclpy half.
# ==========================================================================

def _stamp_to_sec(stamp):
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def _parameter_value(value):
    """Unpack an rcl_interfaces/msg/ParameterValue into a Python value."""
    kind = int(value.type)
    if kind == 1:
        return bool(value.bool_value)
    if kind == 2:
        return int(value.integer_value)
    if kind == 3:
        return float(value.double_value)
    if kind == 4:
        return str(value.string_value)
    return None


def samples_since(samples, cut):
    """Copies of every sample in *samples* with ``recv >= cut``, oldest first.

    Pure, so the ROS-free lane can pin the property that matters: it returns
    EVERY sample at or after the cut, not the newest one. Returning
    ``[samples[-1]]`` here would restore D-34's aliasing exactly, which is the
    mutation ``test_pick_prospect_robot.py`` runs against it.

    The cut is inclusive because callers hand it a timestamp taken before the
    stimulus; a sample that arrived in the same clock tick belongs to the
    window being asked about.
    """
    return [dict(sample) for sample in samples if sample['recv'] >= cut]


class ProbeNode:
    """Owns the single rclpy node, its subscriptions and its recording."""

    def __init__(self, fleet, types):
        from rclpy.callback_groups import ReentrantCallbackGroup
        from rclpy.node import Node

        self.node = Node('phase5_probe')
        self._group = ReentrantCallbackGroup()
        self.fleet = list(fleet)
        self.lock = threading.Lock()
        self._inject_type = types['InjectTask']
        self._override_type = types['OverrideRobot']
        self._map_update_type = types['ResourceMapUpdate']

        # robot_id -> list of sample dicts, oldest first.
        self.states = {rid: [] for rid in self.fleet}
        # (recv_time, task_id, task_type, x, y, emergency)
        self.announcements = []
        self.assignments = []        # (recv_time, task_id, robot_id, x, y)
        self.maps = {}               # (sec, nanosec) -> ResourceMap message
        self.markers = {}            # (sec, nanosec) -> Marker message
        self.paths = {}              # robot_id -> (recv_time, [(x, y), ...])

        for rid in self.fleet:
            self.node.create_subscription(
                types['RobotState'], '/%s/state' % (rid,),
                self._make_state_cb(rid), 10, callback_group=self._group)
            self.node.create_subscription(
                types['Path'], '/%s/planned_path' % (rid,),
                self._make_path_cb(rid), 10, callback_group=self._group)

        self.node.create_subscription(
            types['TaskAnnouncement'], '/orchestrator/task_announcement',
            self._on_announcement, 10, callback_group=self._group)
        self.node.create_subscription(
            types['TaskAssignment'], '/orchestrator/task_assignment',
            self._on_assignment, 10, callback_group=self._group)
        self.node.create_subscription(
            types['ResourceMap'], '/orchestrator/resource_map',
            self._on_map, 10, callback_group=self._group)
        self.node.create_subscription(
            types['MarkerArray'], '/orchestrator/resource_map_markers',
            self._on_markers, 10, callback_group=self._group)

        # THE ONLY PUBLISHER THIS PROBE OWNS, and check 10's stimulus. Depth 64
        # against a 49-message pattern so the writer's own history can hold the
        # whole burst; the reader's depth is the orchestrator's 10, which is
        # what SEED_PUBLISH_INTERVAL_SEC is really pacing against.
        self._map_update_pub = self.node.create_publisher(
            self._map_update_type, '/orchestrator/map_update', 64)

        self._inject_client = self.node.create_client(
            self._inject_type, '/orchestrator/inject_task',
            callback_group=self._group)
        self._override_client = self.node.create_client(
            self._override_type, '/orchestrator/override_robot',
            callback_group=self._group)

        self._executor = None
        self._spin_thread = None

    # -- spin --------------------------------------------------------------

    def spin_in_background(self):
        from rclpy.executors import MultiThreadedExecutor
        self._executor = MultiThreadedExecutor(num_threads=4)
        self._executor.add_node(self.node)
        self._spin_thread = threading.Thread(
            target=self._executor.spin, name='rclpy-spin', daemon=True)
        self._spin_thread.start()

    def shutdown(self):
        if self._executor is not None:
            try:
                self._executor.shutdown(timeout_sec=2.0)
            except TypeError:                    # pragma: no cover - API drift
                self._executor.shutdown()
        try:
            self.node.destroy_node()
        except Exception as exc:                 # teardown only
            log('destroy_node: %s' % (exc,))

    # -- callbacks ---------------------------------------------------------

    def _make_state_cb(self, rid):
        def _cb(msg):
            sample = {
                'recv': time.time(),
                'robot_id': msg.robot_id,
                'robot_type': msg.robot_type,
                'fsm_state': msg.fsm_state,
                'battery_level': float(msg.battery_level),
                'current_task_id': msg.current_task_id,
                'capabilities': list(msg.capabilities),
                'x': float(msg.pose.x),
                'y': float(msg.pose.y),
                # RobotState.pose is a geometry_msgs/Pose2D and the agent fills
                # theta from the HAL odometry yaw (``RobotState.msg:4``,
                # ``agent_node.py`` ``_build_state_msg``), so the heading check
                # 11 needs to place a heading-relative bearing is already on
                # the wire. Until D-35 this callback recorded x and y and threw
                # the rest away -- a published field with no reader in the gate.
                'theta': float(msg.pose.theta),
                'speed': float(msg.velocity.linear.x),
                # D-31's flag. ``getattr`` rather than a plain read because a
                # workspace built before the field exists must degrade to the
                # pre-D-31 behaviour (trust the pose) instead of killing this
                # callback with an AttributeError for every sample, which would
                # void every check that reads state. When the field IS present
                # its false means "this pose is a placeholder", and check 11
                # refuses to measure displacement from one.
                'pose_valid': bool(getattr(msg, 'pose_valid', True)),
                'stamp': _stamp_to_sec(msg.stamp),
            }
            with self.lock:
                self.states[rid].append(sample)
        return _cb

    def _make_path_cb(self, rid):
        def _cb(msg):
            poses = [(float(p.pose.position.x), float(p.pose.position.y))
                     for p in msg.poses]
            with self.lock:
                self.paths[rid] = (time.time(), poses)
        return _cb

    def _on_announcement(self, msg):
        # ``emergency`` is index 5 and IS READ — by check 6, which asserts that
        # the flag the injection carried came back out on the wire. It is
        # recorded here rather than left off because a field written by
        # ``_publish_announcement`` and read by nobody is this repository's
        # single most-repeated defect (CLAUDE.md lists seven), and the honest
        # way to close that pattern is a reader, not a comment about its
        # absence. ``getattr`` with a False default so a workspace built before
        # the field existed degrades to "no emergency was announced" instead of
        # crashing the callback thread — the same shape as the ``pose_valid``
        # read in ``_make_state_cb``.
        with self.lock:
            self.announcements.append((
                time.time(), msg.task_id, msg.task_type,
                float(msg.target_location.x), float(msg.target_location.y),
                bool(getattr(msg, 'emergency', False))))

    def _on_assignment(self, msg):
        with self.lock:
            self.assignments.append((
                time.time(), msg.task_id, msg.robot_id,
                float(msg.target_location.x), float(msg.target_location.y)))

    def _on_map(self, msg):
        with self.lock:
            self.maps[(msg.header.stamp.sec, msg.header.stamp.nanosec)] = msg

    def _on_markers(self, msg):
        with self.lock:
            for marker in msg.markers:
                key = (marker.header.stamp.sec, marker.header.stamp.nanosec)
                self.markers[key] = marker

    # -- reads -------------------------------------------------------------

    def latest_state(self, rid):
        """The NEWEST recorded sample for *rid*, or None.

        A LEVEL READ, and the reason D-34 cost two PRD rows. This returns
        ``samples[-1]`` and nothing else, so any state the publisher held for
        less than the gap between two samples is invisible to it however long
        the caller polls. Callers that ask "was it ever X?" must use
        ``states_since`` instead; this one answers only "is it X now?".
        """
        with self.lock:
            samples = self.states.get(rid) or []
            return dict(samples[-1]) if samples else None

    def states_since(self, rid, cut):
        """Every recorded sample for *rid* with ``recv >= cut``, oldest first.

        The history has always been recorded (``_make_state_cb`` appends every
        sample); until D-34 nothing read it. This is the edge-preserving read:
        a 0.247 s IDLE window between an operator cancel and the next bid is in
        here whenever any sample landed in it, and no amount of polling
        ``latest_state`` can recover it once the next sample has arrived.
        """
        with self.lock:
            samples = self.states.get(rid) or []
            return samples_since(samples, cut)

    def snapshot_states(self):
        with self.lock:
            return {rid: [dict(s) for s in samples]
                    for rid, samples in self.states.items()}

    def forget_path(self, rid):
        with self.lock:
            self.paths.pop(rid, None)

    def latest_map(self):
        """Newest recorded ResourceMap as (stamp_key, message), or None.

        The keys are ``(sec, nanosec)`` tuples, so ``max`` over them is
        chronological rather than merely deterministic.
        """
        with self.lock:
            if not self.maps:
                return None
            key = max(self.maps)
            return key, self.maps[key]

    def maps_since(self, key):
        """Recorded ResourceMaps stamped strictly after *key*, oldest first."""
        with self.lock:
            items = sorted(self.maps.items())
        return [(k, grid) for k, grid in items if key is None or k > key]

    # -- the one topic this probe publishes on -----------------------------

    def map_update_subscribers(self):
        """How many subscribers DDS has matched to the seed publisher."""
        try:
            return int(self._map_update_pub.get_subscription_count())
        except Exception as exc:                 # graph race, not a verdict
            log('get_subscription_count: %s' % (exc,))
            return 0

    def publish_map_update(self, x, y, reading, sigma, scout_id):
        """Publish one synthetic ``selene_msgs/msg/ResourceMapUpdate``.

        The same message an agent publishes from ``_publish_map_update``
        (``agent_node.py:1006-1015``), on the same topic, so the orchestrator's
        ``_on_map_update`` -> ``ResourceMap.update`` path cannot tell the
        difference and nothing downstream of it is stubbed.
        """
        msg = self._map_update_type()
        msg.scout_id = str(scout_id)
        msg.location.x = float(x)
        msg.location.y = float(y)
        msg.location.z = 0.0
        msg.ice_concentration = float(reading)
        msg.sensor_uncertainty = float(sigma)
        msg.stamp = self.node.get_clock().now().to_msg()
        self._map_update_pub.publish(msg)

    def state_topic_publishers(self):
        """Topics carrying selene_msgs/msg/RobotState with >= 1 publisher.

        ``ros2 topic list`` reports names the graph has *heard of*; a topic can
        appear there with no live publisher. ``get_publishers_info_by_topic`` is
        the question this check actually wants to ask, and it is how the D-07
        symptom — an agent running with no Gazebo model behind it — shows up.
        """
        found = set()
        for name, types in self.node.get_topic_names_and_types():
            if 'selene_msgs/msg/RobotState' not in types:
                continue
            try:
                info = self.node.get_publishers_info_by_topic(name)
            except Exception as exc:             # graph race, not a verdict
                log('get_publishers_info_by_topic(%s): %s' % (name, exc))
                continue
            if info:
                found.add(name)
        return found

    def node_names(self):
        names = set()
        for name, namespace in self.node.get_node_names_and_namespaces():
            names.add('%s/%s' % (namespace.rstrip('/'), name))
        return names

    # -- service calls -----------------------------------------------------

    def _call(self, client, request, timeout_sec):
        """Call *client* and block for the reply.

        ``rclpy.spin_until_future_complete`` must not be used here: the executor
        is already spinning this node on another thread, and two spinners on one
        node is undefined. Polling ``future.done()`` needs no second spinner.
        """
        if not client.wait_for_service(timeout_sec=timeout_sec):
            return None
        future = client.call_async(request)
        end = time.time() + timeout_sec
        while time.time() < end:
            if future.done():
                return future.result()
            time.sleep(0.02)
        return None

    def injection_carries_emergency(self):
        """Does THIS WORKSPACE's ``InjectTask.srv`` have the emergency field?

        ASKED OF THE GENERATED TYPE, NOT INFERRED FROM A SERVICE REPLY, AND
        ASKED ONCE FOR BOTH TRANSPORTS. rosbridge builds its request out of the
        same generated type this node imported, so a single answer is correct
        for the websocket ``call_service`` path and for the rclpy fallback
        alike. That is what stops the two transports asking for different
        auction semantics inside one run — the failure mode where check 6
        measures emergency preemption on a box with tornado and wait-your-turn
        on a box without it, and reports the same sentence for both.

        WHY IT IS ASKED AT ALL. A workspace built before the field exists must
        DEGRADE, not crash. Generated request classes use ``__slots__``, so
        assigning a field they do not have raises AttributeError, and
        rosbridge's ``populate_instance`` raises NonexistentFieldException on
        the same input — either would take out check 5 and, through it, checks 6
        and 9, on a build whose only sin is being older than this probe. Same
        rule and same reason as the ``pose_valid`` ``getattr`` in
        ``_make_state_cb`` (register D-31).
        """
        try:
            return hasattr(self._inject_type.Request(), 'emergency')
        except Exception as exc:                 # pragma: no cover - type drift
            log('InjectTask.Request() would not build: %s' % (exc,))
            return False

    def inject_task(self, task_type, x, y, quantity=0.0, robot_id='',
                    emergency=False):
        request = self._inject_type.Request()
        request.task_type = task_type
        request.target_location.x = float(x)
        request.target_location.y = float(y)
        request.target_location.z = 0.0
        request.quantity = float(quantity)
        request.assigned_robot_id = robot_id
        if hasattr(request, 'emergency'):
            # Written even when False, so this path can never leave the field
            # at whatever the generated default happens to be and call it a
            # decision. Guarded by hasattr for the reason
            # injection_carries_emergency() states.
            request.emergency = bool(emergency)
        return self._call(self._inject_client, request, 10.0)

    def override(self, robot_id, command, x=0.0, y=0.0):
        request = self._override_type.Request()
        request.robot_id = robot_id
        request.command = command
        request.target.x = float(x)
        request.target.y = float(y)
        request.target.z = 0.0
        return self._call(self._override_client, request, 15.0)

    def get_remote_parameters(self, node_name, names, timeout_sec=10.0):
        """Read parameters off another node. Returns {name: python value}.

        Used instead of hardcoding ``auction_timeout_sec`` and
        ``resource_map_max_marker_cells``: a gate that assumes a value the
        running system does not have is measuring its own assumptions.

        This is not hypothetical here, and the history is worth keeping.
        ``orchestrator.launch.py`` used to name the node ``orchestrator`` while
        ``orchestrator_params.yaml``'s top-level key was ``orchestrator_node:``,
        and a ROS 2 parameter file is matched against the *runtime* node name —
        so under launch the whole file applied nothing and every value silently
        reverted to its ``declare_parameter`` default (register D-12, fixed
        2026-07-31 by dropping the ``name=`` override). Asking the node is still
        the only way to learn what it is really using: a parameter file that
        matches nothing is indistinguishable, from outside, from one that
        matches and agrees.
        """
        from rcl_interfaces.srv import GetParameters

        client = self.node.create_client(
            GetParameters, '%s/get_parameters' % (node_name,),
            callback_group=self._group)
        try:
            request = GetParameters.Request()
            request.names = list(names)
            response = self._call(client, request, timeout_sec)
            if response is None:
                return {}
            return {name: _parameter_value(value)
                    for name, value in zip(names, response.values)}
        finally:
            self.node.destroy_client(client)


# ==========================================================================
# Check 4 — robot state content, freshness, rate, membership, motion.
# ==========================================================================

def _run_path_length(run):
    """Total path length over a run of samples, metres.

    Path length rather than start-to-end distance: a robot that drives out and
    back inside one run has zero net displacement and is obviously not still.
    """
    total = 0.0
    for previous, current in zip(run, run[1:]):
        total += math.hypot(current['x'] - previous['x'],
                            current['y'] - previous['y'])
    return total


def _run_excursion(run):
    """Largest distance between any two samples in *run*, metres.

    THE RATE-INVARIANT REPLACEMENT FOR ``_run_path_length`` AS A VERDICT, and
    the reasoning matters more than the code.

    ``_run_path_length`` sums ``|dp|`` once per sample. Its value is therefore a
    function of how often the publisher publishes: insert a sample between two
    existing ones and the sum can only grow, and under per-sample position noise
    it grows without bound in the sample count (EXECUTED against the real
    ``FleetMonitor``, which has the same accumulator: a stationary robot with
    1 cm noise books 1.729 m over 100 samples and 7.120 m over 400 -- see the
    D-34 diagnosis). Since D-34 the agent publishes on FSM transition as well as
    on its 0.5 s timer, so the sample rate is now variable BY DESIGN, and a
    verdict that moves when the publisher's rate moves is a statement about the
    instrument rather than about the robot.

    The diameter of the sample set is invariant in the sense that matters: extra
    samples can only refine it toward the true supremum of the excursion, never
    inflate it without limit. It keeps the property ``_run_path_length`` was
    chosen for -- a robot that drives out and back inside one run has zero net
    displacement but a non-zero diameter, so it is still caught -- and it drops
    the property that made it unusable, sensitivity to sampling.

    STATED PLAINLY, BECAUSE IT IS A REAL NARROWING: diameter <= path length
    always, so a robot that wanders forever inside a 5 cm ball now passes where
    the old sum would eventually have failed it. That case is indistinguishable
    from position noise at this threshold, and the path length is still computed
    and REPORTED for every IDLE run, so wandering is visible in the report and
    in --json-out; it just no longer decides a verdict it cannot decide
    honestly.
    """
    worst = 0.0
    for index, first in enumerate(run):
        for second in run[index + 1:]:
            worst = max(worst, math.hypot(second['x'] - first['x'],
                                          second['y'] - first['y']))
    return worst


def _settled_tail(run, settle_sec):
    """Samples of *run* at least *settle_sec* after the run's first sample."""
    if not run:
        return []
    start = run[0]['recv']
    return [sample for sample in run if sample['recv'] - start >= settle_sec]


def _runs_in_state(samples, state):
    """All maximal runs of >= MOTION_MIN_SAMPLES consecutive samples in state.

    A SAMPLE COUNT IS NOT A DURATION any more; callers that need one must also
    apply MOTION_MIN_SPAN_SEC to the run's wall-clock span. See that constant.
    """
    runs = []
    run = []
    for sample in list(samples) + [None]:
        if sample is not None and sample['fsm_state'] == state:
            run.append(sample)
            continue
        if len(run) >= MOTION_MIN_SAMPLES:
            runs.append(run)
        run = []
    return runs


def evaluate_idle_motion(samples):
    """The IDLE stationary rule for one robot. Returns (problems, reports).

    ``problems`` are FAILures of check 4; ``reports`` is one dict per IDLE run
    considered, recorded to --json-out whatever the verdict.

    THREE CONDITIONS, and each is here because a sample count stopped meaning
    what it used to mean when D-34 made the publish rate variable:

    1. the run must hold >= MOTION_MIN_SAMPLES samples (unchanged), AND span
       >= MOTION_MIN_SPAN_SEC of wall clock. Without the span, one extra sample
       published at the instant of the transition into IDLE promotes a
       two-sample window past the count threshold without the robot having been
       IDLE for any longer.
    2. the stopping transient is excluded -- see MOTION_SETTLE_SEC. It is the
       allowance the 2 Hz sampler was already granting by accident.
    3. what is measured is the excursion (``_run_excursion``), not the summed
       path, so the number does not depend on how often the robot publishes.

    A run that is too short after the settle allowance to hold two samples is
    REPORTED AND NOT JUDGED. That is D-34's own rule applied to this file: an
    instrument that cannot see must say so rather than return a verdict.
    """
    problems = []
    reports = []
    for run in _runs_in_state(samples, 'IDLE'):
        span = run[-1]['recv'] - run[0]['recv']
        report = {
            'samples': len(run),
            'span_sec': round(span, 2),
            'path_length_m': round(_run_path_length(run), 3),
            'excursion_all_m': round(_run_excursion(run), 3),
        }
        if span < MOTION_MIN_SPAN_SEC:
            report['verdict'] = 'not judged: span < %.1fs' % (
                MOTION_MIN_SPAN_SEC,)
            reports.append(report)
            continue
        settled = _settled_tail(run, MOTION_SETTLE_SEC)
        if len(settled) < 2:
            report['verdict'] = ('not judged: %d samples after the %.1fs '
                                 'settle allowance' % (len(settled),
                                                       MOTION_SETTLE_SEC))
            reports.append(report)
            continue
        excursion = _run_excursion(settled)
        report['settled_samples'] = len(settled)
        report['excursion_settled_m'] = round(excursion, 3)
        if excursion >= MOTION_EPS_M:
            report['verdict'] = 'FAIL'
            problems.append(
                'IDLE for %d samples over %.1fs but its settled samples span '
                '%.3f m (>= %.2f m; whole run %.3f m, path %.3f m)'
                % (len(run), span, excursion, MOTION_EPS_M,
                   report['excursion_all_m'], report['path_length_m']))
        else:
            report['verdict'] = 'PASS'
        reports.append(report)
    return problems, reports


def evaluate_state_checks(results, probe, fleet, samples_by_robot,
                          legal_states, ws_topics):
    """Check 4 — content, freshness, rate, fleet membership, motion coherence.

    EXPECTED WALL CLOCK: zero. It is evaluated from samples already recorded
    across the whole window, so it costs nothing beyond the window itself.

    THE RATE IS ``(n-1)/(t_last-t_first)``, NOT ``n/window``. Discovery settles
    asynchronously, so the first sample arrives some unknown time after the
    subscription is created; dividing by the nominal window folds that dead time
    into the measurement and understates a healthy publisher.

    THE STATE RATE IS A MINIMUM AND HAS NO MAXIMUM, WHICH IS WHY D-34 COULD NOT
    BREAK THIS CHECK'S RATE ASSERTION. Since D-34 the agent publishes on every
    FSM transition as well as on its 0.5 s timer, so the measured rate is now
    2 Hz plus an irregular transition term. MIN_STATE_RATE_HZ is a floor and
    MAX_STATE_AGE_SEC is a max-age test; both only get easier. The motion rule
    was the part that did NOT survive a variable rate unchanged -- see
    ``evaluate_idle_motion``.

    MOTION COHERENCE IS SPLIT, DELIBERATELY, AND NOT AS FIRST DESIGNED.

    * IDLE for >= 3 samples spanning >= MOTION_MIN_SPAN_SEC must stay inside a
      5 cm ball once it has had one publish period to stop. This FAILS the
      gate. It cannot be satisfied spuriously. ``evaluate_idle_motion`` holds
      the whole argument for why it is an excursion over a settled window and
      no longer a per-sample path sum.
    * NAVIGATING should move. REPORTED, NEVER FAILS, and the reason was
      REWRITTEN on 2026-07-31 because the old one had gone false. It used to say
      ``RobotState.pose`` is dead-reckoned, so it advances perfectly while a
      robot is buried in terrain with its wheels spinning in solid rock and a
      "pose changes" assertion is satisfied by the exact defect it looks like it
      is testing. That is true only under ``pose_source: dead_reckoning``; under
      the shipped default ``localisation`` the pose is the SIMULATOR'S TRUE
      WORLD POSE (``selene_sim/selene_sim/world_odometry_node.py``, registers
      D-24 and D-33), which the wheels cannot fake. This check does not read
      that parameter — check 11 does, for the topic it measures — so it does not
      know which mode produced the samples in front of it, and a rule whose
      meaning depends on an unread parameter must not decide a verdict.
      ``scripts/check_drive.sh`` is still the only thing here that asks Gazebo
      directly.
    * RECHARGING IS EXCLUDED FROM THE STATIONARY RULE, and this gate is itself
      why. ``fsm.py:101-105`` maps ``OPERATOR_RECHARGE`` from every state except
      OFFLINE/ERROR straight to ``RECHARGING``, and ``operator_command.py:149-151``
      fires it and *then* calls ``start_recharge()``, which creates a
      ``RechargeSkill`` that still has to drive to the station — ticked from the
      RECHARGING handler at ``agent_node.py:572-577``. So check 7's own stimulus
      produces a robot that is RECHARGING and moving, and grouping RECHARGING
      with IDLE would fail this gate on correct behaviour. Only the low-battery
      path reaches RECHARGING already parked, via RETURNING
      (``agent_node.py:566-570``).
    """
    problems = []
    notes = []
    idle_runs = {}
    now = time.time()
    legal = set(legal_states)

    expected_topics = set('/%s/state' % (rid,) for rid in fleet)
    live_topics = probe.state_topic_publishers()
    if live_topics != expected_topics:
        # EQUALITY, not ">=". An extra state publisher is the D-07 symptom
        # exactly: an agent running with no Gazebo model behind it, bidding on
        # and winning tasks. The old ">= 4" literal passed that.
        problems.append('state publishers != fleet (missing=%s extra=%s)'
                        % (sorted(expected_topics - live_topics) or 'none',
                           sorted(live_topics - expected_topics) or 'none'))

    rates = {}
    for rid in fleet:
        samples = samples_by_robot.get(rid) or []
        if len(samples) < 2:
            problems.append('%s: %d samples' % (rid, len(samples)))
            continue

        span = samples[-1]['recv'] - samples[0]['recv']
        rate = (len(samples) - 1) / span if span > 0 else 0.0
        rates[rid] = round(rate, 3)
        if rate < MIN_STATE_RATE_HZ:
            problems.append('%s: %.2f Hz < %.2f' % (rid, rate,
                                                    MIN_STATE_RATE_HZ))

        newest = samples[-1]
        if newest['stamp'] <= 0.0:
            problems.append('%s: zero stamp' % (rid,))
        elif now - newest['stamp'] > MAX_STATE_AGE_SEC:
            problems.append('%s: newest stamp %.2fs old'
                            % (rid, now - newest['stamp']))

        expected_type = rid.rsplit('_', 1)[0]
        for sample in samples:
            if sample['robot_id'] != rid:
                problems.append('%s: robot_id=%r on its own topic'
                                % (rid, sample['robot_id']))
                break
            if sample['robot_type'] != expected_type:
                problems.append('%s: robot_type=%r, expected %r'
                                % (rid, sample['robot_type'], expected_type))
                break
            if sample['fsm_state'] not in legal:
                problems.append('%s: fsm_state=%r not in AgentState'
                                % (rid, sample['fsm_state']))
                break
            if not 0.0 <= sample['battery_level'] <= 1.0:
                problems.append('%s: battery_level=%.3f outside [0,1]'
                                % (rid, sample['battery_level']))
                break

        idle_problems, idle_report = evaluate_idle_motion(samples)
        if idle_report:
            idle_runs[rid] = idle_report
        for text in idle_problems[:1]:
            problems.append('%s: %s' % (rid, text))
        navigating = _runs_in_state(samples, 'NAVIGATING')
        if navigating:
            longest = max(navigating, key=len)
            moved = _run_path_length(longest)
            notes.append('%s NAVIGATING moved %.2f m over %d samples%s'
                         % (rid, moved, len(longest),
                            '' if moved > MOTION_EPS_M else ' (NOT MOVING)'))

    if ws_topics is None:
        notes.append('rosapi topics_for_type not exercised (no websocket)')
    elif set(ws_topics) != expected_topics:
        # This is the code path useFleetDiscovery.js really uses
        # (rosTopics.js:56-94), and the closest headless proxy that exists to
        # "the dashboard shows all robots".
        problems.append('rosapi topics_for_type returned %s, expected %s'
                        % (sorted(ws_topics), sorted(expected_topics)))
    else:
        notes.append('rosapi topics_for_type agrees with the fleet')

    results.measured(4, rates_hz=rates, legal_states=sorted(legal),
                     state_topics=sorted(live_topics),
                     expected_topics=sorted(expected_topics),
                     idle_runs=idle_runs,
                     rosapi_topics=(sorted(ws_topics)
                                    if ws_topics is not None else None))
    if problems:
        results.set(4, FAIL, '; '.join(problems))
    else:
        rate_text = ', '.join('%s %.2f Hz' % (rid, rates[rid])
                              for rid in sorted(rates))
        results.set(4, PASS, '%d robots, %s%s'
                    % (len(fleet), rate_text,
                       '; ' + '; '.join(notes) if notes else ''))


# ==========================================================================
# Check 10 — heatmap / RViz2 overlay parity, on a map the probe seeds.
# ==========================================================================

def seed_lattice(centre_x, centre_y):
    """The seeded reading positions, world metres, in a stable order.

    Its own function so ``selene_orchestrator/test/test_hottest_cell_decode.py``
    can re-derive the same pattern in the ROS-free lane from the same two
    constants and pin the answer check 10 asserts live.
    """
    steps = int(round(SEED_LATTICE_HALF_EXTENT_M / SEED_LATTICE_PITCH_M))
    return [(centre_x + i * SEED_LATTICE_PITCH_M,
             centre_y + j * SEED_LATTICE_PITCH_M)
            for i in range(-steps, steps + 1)
            for j in range(-steps, steps + 1)]


def seed_resource_map(results, probe, ice, resource_map_class):
    """Publish synthetic readings so check 10's correctness half can run.

    Returns a dict of seed facts on success, or None — in which case a FAIL or
    SKIP verdict for check 10 has ALREADY been recorded here and
    ``evaluate_map_parity`` must not overwrite it.

    EXPECTED WALL CLOCK: about 4 s typical — 1.5 s to emit 49 readings at
    SEED_PUBLISH_INTERVAL_SEC, then up to one 2 s map period for the snapshot
    that carries them. Worst case SEED_MATCH_TIMEOUT_SEC + 1.5 s +
    SEED_SETTLE_TIMEOUT_SEC, about 47 s, and every second of that is a system
    that is not answering.

    WHY THIS EXISTS
    ---------------
    Check 10 has two halves. The PARITY half — one header stamp, cube geometry,
    per-cell colours recomputed from the posterior — is a function of whatever
    the map holds and runs on an empty one. The CORRECTNESS half, "matches
    underlying data" (``docs/PRD.md:451``, FR-MAP-4(b)), is the one that needs
    data: the hottest cell of the fused posterior must decode row-major to the
    place the ice actually is.

    That half never ran. MEASURED by the operator on two live gate runs
    (2026-07-31): ``total_observations`` was 0 both times and check 10 reported
    PASS with the note "hottest-cell check skipped ... so an empty map would
    fail on emptiness rather than on correctness". It could not have been
    otherwise. The gate boots and measures inside roughly 90-150 s; a scout
    drives ~100 m at 0.3 m/s to its first waypoint, and
    ``agent_node.py:771`` calls ``_start_recharge()`` UNCONDITIONALLY after
    every task completion, so robots spend most of a run returning to base
    whatever their battery says. The operator measured ``total_observations``
    reaching 155 after ~10 minutes and 316 after ~21 minutes on a live two-scout
    run. A gate-length run cannot reach 200, so the assertion was structurally
    unreachable and the check passed on an empty map.

    WHY SEEDING THROUGH THE REAL TOPIC IS A FIXTURE AND NOT A FAKE
    -------------------------------------------------------------
    Everything downstream of the stimulus is the shipped code, unmodified:
    ``_on_map_update`` (``orchestrator_node.py:1501``), its rejection guard,
    ``ResourceMap.update``'s Bayesian fusion, ``select_observed``'s sparse
    encoding, ``cell_centres``, ``marker_colours`` and both publishers. The only
    thing the probe supplies is the READINGS — the same message an agent
    publishes, on the same topic, with a ``scout_id`` that says where they came
    from. What is NOT proven by a seeded run is stated in the report row and in
    the gate's generated footer: that robots autonomously survey the deposits.
    That is a slower property and a different measurement.

    SIDE EFFECTS, STATED
    --------------------
    The readings permanently alter the orchestrator's fused map for the life of
    the process. Three consequences, all benign for a gate that tears the system
    down afterwards, and none of them silent:
      * ``MissionProgress.total_readings`` and the adaptive survey planner both
        read the same map, so the fleet may re-target toward the seeded patch —
        which sits on a real deposit centre, so it is not a wrong place to go;
      * the dashboard's client-side heatmap subscribes to
        ``/orchestrator/map_update`` directly (FR-DASH-2 / D-02) and will draw
        these readings;
      * ``/orchestrator/resource_map`` grows from an 88-byte empty snapshot to
        about 25 kB. Check 3's frame-size guard is evaluated BEFORE this runs
        (see ``main``) precisely so that its measurement stays a statement about
        the system rather than about the probe's own stimulus.
    """
    if not ice['deposits']:
        results.set(10, SKIP,
                    'check 10 could not be seeded: no deposits were read from '
                    'ice_deposits.yaml (--ice-config %r), so there is no ground '
                    'truth to shape readings from and none to assert the '
                    'hottest cell against. NOT run against an unseeded map: '
                    'that is the hole this seed closes'
                    % (ice['path'] or 'not given',))
        return None

    # ---- 1. A baseline snapshot, and the geometry, off the wire. ----
    # The grid geometry is read from the published message rather than from
    # parameters: ResourceMap.msg carries width, height, resolution and origin
    # for exactly this reason, and a probe that assumed 500x500 at 1.0 m would
    # be measuring its own assumptions the moment map_width changed.
    baseline = probe.latest_map()
    if baseline is None:
        deadline = time.time() + SEED_SETTLE_TIMEOUT_SEC
        while baseline is None and time.time() < deadline:
            time.sleep(0.5)
            baseline = probe.latest_map()
    if baseline is None:
        results.set(10, FAIL,
                    'no /orchestrator/resource_map message arrived in %.0fs, so '
                    'the map could not be seeded and neither half of this check '
                    'could run. It publishes at resource_map_publish_rate '
                    '(0.5 Hz shipped)' % (SEED_SETTLE_TIMEOUT_SEC,))
        return None
    base_key, base_grid = baseline
    base_observations = int(base_grid.total_observations)

    # ---- 2. Wait for the orchestrator to match the seed publisher. ----
    matched = 0
    deadline = time.time() + SEED_MATCH_TIMEOUT_SEC
    while time.time() < deadline:
        matched = probe.map_update_subscribers()
        if matched > 0:
            break
        time.sleep(0.25)
    if matched <= 0:
        # Publishing into an unmatched topic loses every sample with no error
        # anywhere, and the symptom downstream would be an empty map — the
        # exact reading this whole change exists to stop being a PASS.
        results.set(10, FAIL,
                    'nothing subscribed to /orchestrator/map_update within '
                    '%.0fs, so the seed had nowhere to land. The orchestrator '
                    'creates that subscription at orchestrator_node.py:1096; a '
                    'zero here means it is not running, or is not in this DDS '
                    'domain' % (SEED_MATCH_TIMEOUT_SEC,))
        return None

    # ---- 3. Build the pattern, and predict what it must do to the map. ----
    deposit = ice['strongest']
    peak_x, peak_y = deposit['centre']
    points = seed_lattice(peak_x, peak_y)
    readings = [deposit_field_concentration(x, y, ice) for x, y in points]

    # The prediction runs the REAL ResourceMap locally over the same readings.
    # It is used for ONE number — how many (reading, cell) incidences the
    # pattern must produce — and deliberately not for the answer: the hottest
    # cell is asserted against ice_deposits.yaml, which is independent ground
    # truth, so nothing here compares the system against a copy of itself.
    #
    # The count is exactly reproducible because ResourceMap._count[gy, gx] += 1
    # is unconditional (resource_map.py:144), so the delta a batch causes does
    # not depend on what the grid already held.
    #
    # ONE COUPLING, STATED: footprint_radius / footprint_sigma are not on the
    # wire, so this scratch map takes the class defaults (5.0 / 3.0) — which is
    # what the orchestrator gets, since it passes neither
    # (orchestrator_node.py:999-1005). If that ever changes, this check FAILS
    # loudly on a shortfall it can name rather than drifting quietly.
    scratch = resource_map_class(
        width=int(base_grid.width), height=int(base_grid.height),
        resolution=float(base_grid.resolution),
        origin_x=float(base_grid.origin.x), origin_y=float(base_grid.origin.y))
    for (x, y), reading in zip(points, readings):
        scratch.update(x, y, reading, SEED_SENSOR_SIGMA_WT)
    expected_delta = int(scratch.get_total_readings())
    if expected_delta < MIN_MAP_OBSERVATIONS:
        results.set(10, FAIL,
                    'the seed pattern around %s (%.1f, %.1f) would produce only '
                    '%d observations against the published grid geometry '
                    '(%dx%d at %.2f m, origin (%.1f, %.1f)); %d are needed. The '
                    'pattern is probably falling outside the grid'
                    % (deposit['id'], peak_x, peak_y, expected_delta,
                       base_grid.width, base_grid.height, base_grid.resolution,
                       base_grid.origin.x, base_grid.origin.y,
                       MIN_MAP_OBSERVATIONS))
        return None

    # ---- 4. Emit. ----
    log('seeding %d readings around %s (%.1f, %.1f); expecting +%d observations'
        % (len(points), deposit['id'], peak_x, peak_y, expected_delta))
    started = time.time()
    for (x, y), reading in zip(points, readings):
        probe.publish_map_update(x, y, reading, SEED_SENSOR_SIGMA_WT,
                                 SEED_SCOUT_ID)
        time.sleep(SEED_PUBLISH_INTERVAL_SEC)

    # ---- 5. Wait for a snapshot that carries the whole batch. ----
    # STRICTLY NEWER THAN THE BASELINE STAMP, and at least the predicted delta.
    # A snapshot already in flight when the last reading was published carries
    # part of the batch, and comparing against a partial fusion is how a
    # tolerance gets widened to hide a real drop.
    target = base_observations + expected_delta
    settled = None
    deadline = time.time() + SEED_SETTLE_TIMEOUT_SEC
    while time.time() < deadline:
        for key, grid in probe.maps_since(base_key):
            if int(grid.total_observations) >= target:
                settled = (key, grid)
                break
        if settled is not None:
            break
        time.sleep(0.25)

    if settled is None:
        newest = probe.latest_map()
        seen = int(newest[1].total_observations) if newest else base_observations
        results.measured(10, seed_readings=len(points),
                         seed_expected_delta=expected_delta,
                         seed_baseline_observations=base_observations,
                         seed_observed_delta=seen - base_observations,
                         seed_landed=False)
        results.set(10, FAIL,
                    'the seed did not land: %d readings published to '
                    '/orchestrator/map_update (%d subscriber(s) matched) should '
                    'have raised total_observations by %d, from %d to %d, but '
                    'no snapshot in the following %.0fs went past %d. Either '
                    'the orchestrator rejected them (it logs "Rejected map '
                    'update" per orchestrator_node.py:1527) or samples were '
                    'dropped. This check FAILS rather than falling back to the '
                    'unseeded map, because a PASS on an unseeded map is the '
                    'defect it exists to prevent'
                    % (len(points), matched, expected_delta, base_observations,
                       target, SEED_SETTLE_TIMEOUT_SEC, seen))
        return None

    settled_key, settled_grid = settled
    elapsed = time.time() - started
    observed_delta = int(settled_grid.total_observations) - base_observations
    results.measured(10, seed_readings=len(points),
                     seed_expected_delta=expected_delta,
                     seed_baseline_observations=base_observations,
                     seed_observed_delta=observed_delta,
                     seed_landed=True,
                     seed_deposit=deposit['id'],
                     seed_peak=[peak_x, peak_y],
                     seed_lattice=[SEED_LATTICE_PITCH_M,
                                   SEED_LATTICE_HALF_EXTENT_M],
                     seed_sigma_wt=SEED_SENSOR_SIGMA_WT,
                     seed_wait_sec=round(elapsed, 2))
    log('seed landed: total_observations %d -> %d in %.1fs'
        % (base_observations, int(settled_grid.total_observations), elapsed))
    return {
        'seeded': True,
        'deposit': deposit,
        'peak': (peak_x, peak_y),
        'readings': len(points),
        'expected_delta': expected_delta,
        'observed_delta': observed_delta,
        'baseline_observations': base_observations,
        'settled_key': settled_key,
        'elapsed': elapsed,
    }


def evaluate_map_parity(results, probe, params, rviz_fixed_frame,
                        ice, seed, rmviz, numpy):
    """Check 10 — the heatmap and the RViz2 overlay come from one snapshot.

    EXPECTED WALL CLOCK: zero (evaluated from the recording).

    ``_publish_resource_map_once`` builds ONE ``Header`` and assigns it to both
    messages (``orchestrator_node.py:1428-1430`` builds it, ``:1439`` puts it on
    the grid and ``:1469`` on the marker), so a matched pair has
    byte-identical stamps. (``_publish_resource_map`` at ``:1374`` is now only
    the catching timer entry point around it — D-18 moved the body out so an
    exception in the colour law cannot propagate out of ``executor.spin()`` and
    end the node. The one-header property is unchanged.)
    Pairing on the stamp IS the "same snapshot" proof;
    everything after it recomputes the overlay from the posterior alone through
    ``selene_orchestrator.resource_map_viz`` — the same module the dashboard's
    ramp is pinned against by ``test_dashboard_colour_parity.py``.

    BE EXACT ABOUT SCOPE. No image is compared and no RViz2 is run. What this
    proves is that both renderers are functions of the same snapshot through the
    same colour law. It is not the PRD's "side-by-side comparison", which is a
    human method and cannot be performed by a script.

    THE HOTTEST-CELL ASSERTION IS MANDATORY. It used to be a sentence appended
    to whatever verdict the parity half reached, skipped whenever
    ``total_observations`` was under MIN_MAP_OBSERVATIONS — which was every
    single gate run, because a gate-length run cannot get there (see
    ``seed_resource_map``). Two live runs therefore reported PASS on a map with
    zero cells in it. It is now a condition of the PASS: if it cannot be
    evaluated, this check is a FAIL on a seeded run and a SKIP on
    ``--no-seed-map``, and the exit-code contract treats both as not-a-pass.
    """
    if seed is None:
        # seed_resource_map already recorded the FAIL or SKIP and said why.
        # Overwriting it here would replace a precise diagnosis with a generic
        # one, or — worse, and this is the whole defect — with a PASS.
        return

    with probe.lock:
        maps = dict(probe.maps)
        markers = dict(probe.markers)
    common = sorted(set(maps) & set(markers))
    if not common:
        results.set(10, SKIP,
                    'no ResourceMap/MarkerArray pair sharing a header stamp '
                    '(%d maps, %d markers recorded; both publish at '
                    'resource_map_publish_rate, 0.5 Hz by default)'
                    % (len(maps), len(markers)))
        return

    # ONLY PAIRS AT OR AFTER THE SNAPSHOT THAT CARRIED THE SEED. Anything older
    # describes a map the stimulus had not reached yet, and evaluating the
    # correctness half against it would be asserting the hottest cell of a grid
    # the probe knows is incomplete.
    #
    # An empty result here is a real and specific failure rather than a timing
    # gap: seed_resource_map already SAW a ResourceMap carrying the seed, and
    # the two messages come from one snapshot on one timer with one Header
    # (orchestrator_node.py:1428-1430, :1439, :1469). A posterior with no
    # overlay sharing its stamp is the D-18 signature — _publish_resource_map's
    # catch (orchestrator_node.py:1399-1409) swallowing an exception raised
    # between the two publishes, which leaves RViz2 showing a stale overlay and
    # logs one line in a file nobody is reading.
    seeded_key = seed.get('settled_key')
    if seeded_key is not None:
        usable = [key for key in common if key >= seeded_key]
        if not usable:
            results.set(10, FAIL,
                        'the seed landed (total_observations rose by %d) but no '
                        'ResourceMap/MarkerArray pair shares a header stamp at '
                        'or after that snapshot: %d maps and %d markers were '
                        'recorded in all. Both are published from one snapshot '
                        'with one Header, so the overlay publish is failing '
                        'while the posterior succeeds -- see '
                        '_publish_resource_map\'s catch at '
                        'orchestrator_node.py:1399 and the orchestrator log'
                        % (seed['observed_delta'], len(maps), len(markers)))
            return
        common = usable

    grid = maps[common[-1]]
    marker = markers[common[-1]]
    problems = []
    resolution = float(grid.resolution)

    if int(marker.type) != MARKER_CUBE_LIST:
        problems.append('marker.type=%d, expected CUBE_LIST(%d)'
                        % (marker.type, MARKER_CUBE_LIST))
    if int(marker.action) != MARKER_ADD:
        problems.append('marker.action=%d, expected ADD(%d)'
                        % (marker.action, MARKER_ADD))
    if abs(float(marker.pose.orientation.w) - 1.0) > 1e-9:
        # A zero quaternion is rejected outright by RViz2's MarkerBase.
        problems.append('orientation.w=%.6f, expected 1.0'
                        % (marker.pose.orientation.w,))
    if (abs(float(marker.scale.x) - resolution) > 1e-6
            or abs(float(marker.scale.y) - resolution) > 1e-6):
        problems.append('scale (%.3f, %.3f) != resolution %.3f'
                        % (marker.scale.x, marker.scale.y, resolution))

    frame_param = params.get('resource_map_frame_id')
    for label, value in (('ResourceMap', grid.header.frame_id),
                         ('Marker', marker.header.frame_id)):
        if frame_param is not None and value != frame_param:
            problems.append('%s.header.frame_id=%r != resource_map_frame_id=%r'
                            % (label, value, frame_param))
        if rviz_fixed_frame and value != rviz_fixed_frame:
            # Nothing in this repo publishes TF (/tf and /tf_static have zero
            # publishers), so RViz2 can only resolve a frame identical to its
            # fixed frame. A mismatch renders an empty scene with a working
            # publisher and no error anywhere.
            problems.append('%s.header.frame_id=%r != rviz Fixed Frame %r'
                            % (label, value, rviz_fixed_frame))

    # ---- Recompute the overlay from the posterior alone. ----
    width = int(grid.width)
    height = int(grid.height)
    indices = numpy.asarray(grid.cell_index, dtype=numpy.int64)
    counts = numpy.zeros(width * height, dtype=numpy.int64)
    means = numpy.zeros(width * height, dtype=numpy.float64)
    variances = numpy.zeros(width * height, dtype=numpy.float64)
    if indices.size:
        counts[indices] = numpy.asarray(grid.cell_observation_count,
                                        dtype=numpy.int64)
        means[indices] = numpy.asarray(grid.cell_mean, dtype=numpy.float64)
        variances[indices] = numpy.asarray(grid.cell_variance,
                                           dtype=numpy.float64)

    max_cells = params.get('resource_map_max_marker_cells')
    if max_cells is None and len(marker.points) < int(indices.size):
        # The overlay is decimated and the stride that produced it cannot be
        # reconstructed without the cap. Reporting a mismatch here would blame
        # the system for a parameter this probe failed to read.
        results.set(10, SKIP,
                    'the orchestrator did not answer for '
                    'resource_map_max_marker_cells and the overlay is '
                    'decimated (%d cubes from %d observed cells), so the cell '
                    'selection cannot be reproduced'
                    % (len(marker.points), int(indices.size)))
        return

    shown = rmviz.select_observed(counts.reshape(height, width),
                                  max_cells=max_cells)
    xs, ys = rmviz.cell_centres(shown, width, resolution,
                                float(grid.origin.x), float(grid.origin.y))
    colours = rmviz.marker_colours([float(means[i]) for i in shown],
                                   [float(variances[i]) for i in shown],
                                   float(grid.prior_variance))

    if len(marker.colors) != len(marker.points):
        # RViz2 discards the per-point colours entirely on a length mismatch and
        # falls back to the flat marker colour with nothing surfaced. D-08
        # records this as one of three traps that fail silently.
        problems.append('len(colors)=%d != len(points)=%d'
                        % (len(marker.colors), len(marker.points)))
    if len(marker.points) != len(shown):
        problems.append('marker has %d points, recomputation gives %d'
                        % (len(marker.points), len(shown)))
    else:
        worst_point = 0.0
        for point, x, y in zip(marker.points, xs, ys):
            worst_point = max(worst_point,
                              abs(float(point.x) - float(x)),
                              abs(float(point.y) - float(y)))
        if worst_point > 1e-3:
            problems.append('worst point disagreement %.6f m > 1e-3'
                            % (worst_point,))

        worst_colour = 0.0
        for colour, (red, green, blue, alpha) in zip(marker.colors, colours):
            worst_colour = max(worst_colour,
                               abs(float(colour.r) - red),
                               abs(float(colour.g) - green),
                               abs(float(colour.b) - blue),
                               abs(float(colour.a) - alpha))
        # One part in 255 is one integer step of an 8-bit channel. It is also
        # the float32 headroom: ResourceMap.cell_mean is float32 on the wire
        # while the publisher computed the colour from the float64 grid
        # (resource_map.py:30-32), so an exact comparison would be asserting
        # that a lossy encode is lossless.
        if worst_colour > (1.0 / 255.0) + 1e-6:
            problems.append('worst colour disagreement %.5f > 1/255'
                            % (worst_colour,))

    # ---- "Matches underlying data" — FR-MAP-4(b). MANDATORY. ----
    #
    # This is the half the seed exists for, and it is now a condition of the
    # PASS rather than a sentence appended to one. The branch below returns
    # early with a verdict that is NOT a PASS, because a PASS on a map with
    # nothing in it is exactly what two live runs produced.
    total_observations = int(grid.total_observations)
    if not ice['centres']:
        blocker = ('no deposit centres were read from ice_deposits.yaml '
                   '(--ice-config %r), so there is no ground truth to compare '
                   'the hottest cell against' % (ice['path'] or 'not given',))
    elif indices.size == 0 or total_observations < MIN_MAP_OBSERVATIONS:
        blocker = ('total_observations=%d (need %d) over %d observed cells%s'
                   % (total_observations, MIN_MAP_OBSERVATIONS,
                      int(indices.size),
                      ('; the map was seeded with %d readings and they landed, '
                       'so the map lost them again' % (seed['readings'],))
                      if seed['seeded'] else
                      ('; --no-seed-map was given, so this run depended on the '
                       'fleet surveying, which a gate-length run cannot do -- '
                       'the operator measured 155 readings after ~10 minutes')))
    else:
        blocker = ''
    if blocker:
        results.measured(10, cells_on_wire=int(indices.size),
                         cells_in_marker=len(marker.points),
                         total_observations=total_observations,
                         frame_id=grid.header.frame_id,
                         seeded=bool(seed['seeded']))
        results.set(
            10, FAIL if seed['seeded'] else SKIP,
            'the hottest-cell assertion could not be evaluated: %s. The parity '
            'half %s, and is deliberately NOT reported as a pass on its own: '
            '"matches underlying data" is the acceptance criterion this check '
            'exists for'
            % (blocker,
               'found %d problem(s): %s' % (len(problems), '; '.join(problems))
               if problems else 'found no problems'))
        return

    # ONE DECODE, SHARED WITH THE PUBLISHER. rmviz.cell_centres is the function
    # orchestrator_node._publish_resource_map_once used to place the cubes
    # (:1460), and it mirrors ResourceMap.grid_to_world. Open-coding
    # `divmod(index, width)` here — which this check did until 2026-07-31 —
    # meant the arithmetic the whole assertion rests on existed twice and was
    # pinned nowhere. It is now pinned in the ROS-free lane by
    # selene_orchestrator/test/test_hottest_cell_decode.py.
    hot = int(numpy.argmax(numpy.asarray(grid.cell_mean,
                                         dtype=numpy.float64)))
    hot_index = int(indices[hot])
    hot_xs, hot_ys = rmviz.cell_centres([hot_index], width, resolution,
                                        float(grid.origin.x),
                                        float(grid.origin.y))
    hot_x = float(hot_xs[0])
    hot_y = float(hot_ys[0])
    nearest_centre = min(math.hypot(hot_x - cx, hot_y - cy)
                         for cx, cy in ice['centres'])

    # THE TOLERANCE IS ONE CELL, and on a seeded run that is not an inherited
    # constant — it is the measurement. MEASURED offline on 2026-07-31 by
    # running this exact lattice through the real ResourceMap and
    # resource_map_viz with the float32 wire encoding applied: the hottest cell
    # decodes 0.707 m from the deposit centre (the half-diagonal of a 1.0 m
    # cell, i.e. the nearest cell centre to it), with the runner-up 0.0389 wt%
    # behind. It scales with resolution — 0.354 m at 0.5 m cells, 1.414 m at
    # 2.0 m cells — which is why the bound is `resolution` and not a metre
    # count. It also matches D-08's independently measured 0.7 m from a real
    # 256-reading survey, which is the rigour this row is held to.
    if seed['seeded']:
        target_x, target_y = seed['peak']
        distance = math.hypot(hot_x - target_x, hot_y - target_y)
        hottest = ('hottest cell %.3f wt%% (flat index %d) decodes row-major to '
                   'world (%.1f, %.1f), %.2f m from the seeded peak %s at '
                   '(%.1f, %.1f) and %.2f m from the nearest ice_deposits.yaml '
                   'centre'
                   % (float(grid.cell_mean[hot]), hot_index, hot_x, hot_y,
                      distance, seed['deposit']['id'], target_x, target_y,
                      nearest_centre))
        if distance > resolution:
            problems.append('hottest cell %.2f m from the seeded peak (> one '
                            '%.2f m cell)' % (distance, resolution))
    else:
        distance = nearest_centre
        hottest = ('hottest cell %.3f wt%% (flat index %d) decodes row-major to '
                   'world (%.1f, %.1f), %.2f m from the nearest '
                   'ice_deposits.yaml centre'
                   % (float(grid.cell_mean[hot]), hot_index, hot_x, hot_y,
                      distance))
        if distance > resolution:
            problems.append('hottest cell %.2f m from any deposit centre '
                            '(> resolution %.2f)' % (distance, resolution))

    if seed['seeded']:
        provenance = (
            'THE MAP WAS SEEDED BY THIS PROBE: %d synthetic ResourceMapUpdate '
            'readings shaped like %s in ice_deposits.yaml were published to '
            '/orchestrator/map_update on a %.0f m lattice over +/-%.0f m, '
            'raising total_observations by %d (predicted %d) in %.1fs from a '
            'baseline of %d. The fleet did not survey this; the fusion, sparse '
            'encoding and marker publishing are the system\'s own'
            % (seed['readings'], seed['deposit']['id'], SEED_LATTICE_PITCH_M,
               SEED_LATTICE_HALF_EXTENT_M, seed['observed_delta'],
               seed['expected_delta'], seed['elapsed'],
               seed['baseline_observations']))
    else:
        provenance = ('THE MAP WAS NOT SEEDED (--no-seed-map): these %d '
                      'observations came from the fleet'
                      % (total_observations,))

    results.measured(10, cells_on_wire=int(indices.size),
                     cells_in_marker=len(marker.points),
                     total_observations=total_observations,
                     frame_id=grid.header.frame_id,
                     rviz_fixed_frame=rviz_fixed_frame,
                     max_marker_cells=max_cells, hottest=hottest,
                     hottest_cell_index=hot_index,
                     hottest_cell_world=[round(hot_x, 3), round(hot_y, 3)],
                     hottest_cell_error_m=round(distance, 3),
                     seeded=bool(seed['seeded']))
    if problems:
        results.set(10, FAIL, '%s; %s. %s'
                    % ('; '.join(problems), hottest, provenance))
    else:
        results.set(
            10, PASS,
            '%d observed cells, %d cubes with %d matching colours, one header '
            'stamp, frame %r; %s. %s. NO IMAGE COMPARED AND NO RViz2 RUN: this '
            'proves the fusion -> sparse-encode -> marker path is correct on '
            'this input and that both renderers are functions of the same '
            'snapshot through the same colour law. It does NOT prove that '
            'robots autonomously survey the deposits'
            % (int(indices.size), len(marker.points), len(marker.colors),
               grid.header.frame_id, hottest, provenance))


# ==========================================================================
# Stimulus timeline.
# ==========================================================================

def freeing_receipt(success, message, samples, assignments, robot_id, task_id):
    """Did the operator cancel really free *robot_id*? -> (ok, kind, note).

    ``ok`` is False only when the service itself gave no receipt. ``kind`` names
    the DURABLE corroboration found, or '' when the receipt is the service
    response alone. Pure, so the ROS-free lane can pin every branch.

    THE SERVICE RESPONSE IS A CAUSAL RECEIPT, NOT A SAMPLE, and that is the
    whole point of this function. ``/orchestrator/override_robot`` returns
    ``bool(agent_resp.accepted)`` (``orchestrator_node.py:694``);
    ``operator_command_logic`` sets ``accepted = True`` only after firing
    OPERATOR_CANCEL (``operator_command.py:136-137,153-155``); and
    ``OPERATOR_CANCEL`` maps unconditionally to IDLE from every state except
    OFFLINE (``fsm.py``, the OPERATOR_CANCEL wildcard), with OFFLINE rejected by
    the agent's own live check (``operator_command.py:81-85`` -- the
    orchestrator's cached ``fsm_state`` guard is the weaker one, since it is fed
    by the same sampler this deviation is about). So a success here means the
    FSM WAS in IDLE, whether or not any sample carried it.

    THE ONE HOLE, rejected explicitly: a duplicate ``sequence`` returns
    accepted=True WITHOUT firing the event (``operator_command.py:74-77``) and
    the orchestrator forwards that reason verbatim into ``response.message``
    (``orchestrator_node.py:695-697``). The enumeration is complete: the only
    other early returns set ``accepted = False`` (OFFLINE :81-85, ERROR :87-92,
    unknown command :94-99).

    WHY THIS IS NOT WIDENING A THRESHOLD TO GO GREEN. PRD row 4 is "Operator-
    injected task enters auction and gets assigned" (``docs/PRD.md:1506``,
    ROW_CHECKS[3] = "5 6"). Nothing in it concerns a robot being IDLE; the IDLE
    wait is a PRECONDITION this gate invented for itself, and turning a
    precondition's timeout into a SKIP verdict on the row is the category
    error D-34 names. Nothing is asserted less: check 6 still has to correlate
    the injected task_id through announcement AND assignment, and it can still
    FAIL. What changes is that the gate now renders a verdict on rows 3 and 4
    instead of declining to measure them.
    """
    if not success:
        return False, '', ('cancel_task on %s was not accepted: %s'
                           % (robot_id, message or 'no answer'))
    if str(message).strip() == 'duplicate_sequence':
        # Accepted without firing anything. Never a receipt.
        return False, '', ('cancel_task on %s returned duplicate_sequence, '
                           'which is accepted WITHOUT firing OPERATOR_CANCEL, '
                           'so nothing proves the robot was freed' % (robot_id,))

    receipt = ('the accepted cancel_task response is itself the receipt: the '
               'agent returns accepted only after firing OPERATOR_CANCEL, '
               'which is an unconditional transition to IDLE')
    for sample in samples:
        if sample['fsm_state'] == 'IDLE':
            return True, 'idle_sample', (
                '%s; corroborated by an IDLE state sample after the cancel'
                % (receipt,))
    for sample in samples:
        if not str(sample['current_task_id']).strip():
            return True, 'cleared_task_id', (
                '%s; corroborated by a state sample with an empty '
                'current_task_id, the durable post-cancel signature (the id is '
                'cleared at operator_command.py:133 and re-set only on a new '
                'assignment)' % (receipt,))
    if task_id:
        for record in assignments:
            if record[1] == task_id and record[2] == robot_id:
                return True, 'assignment', (
                    '%s; corroborated by the injected task being assigned to '
                    'it' % (receipt,))
    return True, '', ('%s. NO durable corroboration arrived within %.0fs, so '
                      'this row rests on the service response alone'
                      % (receipt, FREE_CORROBORATION_SEC))


def pick_prospect_robot(probe, fleet, deadline_sec, allow_freeing, task_id=''):
    """Wait for a prospect-capable robot to be IDLE. Returns (rid, note).

    WHY THIS WAIT EXISTS. ``_auction_tick`` returns immediately when no robot is
    idle (``orchestrator_node.py:1566-1569``), so with every robot busy **no
    auction starts at all** and an injected task sits PENDING however correct
    everything else is. Failing check 6 for that would be the gate reporting its
    own timing as a system defect.

    CALLED AFTER THE INJECTION, NOT BEFORE IT. The task is already queued at
    priority 10.0, and since 2026-08-01 tagged ``emergency``, by the time this
    runs; see the stimulus-timeline comment in ``main`` for why that ordering is
    what removes the race with the 0.5 s auction tick, and why the emergency
    semantics did not make it unnecessary.

    WHY THE FALLBACK EXISTS. At startup the HTN decomposition queues ten survey
    tasks, and with the default two scouts both go busy within seconds and stay
    busy for minutes. Waiting alone would make SKIP the *normal* outcome of the
    row the PRD cares most about. So, when nothing goes idle in time, the probe
    frees one scout with an ``OverrideRobot`` ``cancel_task`` — itself a
    supported FR-DASH-6 operator path — and SAYS SO in the report row. A gate
    must not certify what it did not measure; it also must not be structurally
    unable to measure the thing it exists for. ``--no-free-robot`` turns the
    fallback off and takes the SKIP instead.

    WHAT THE RETURNED ROBOT IS, AND IS NOT. It is a WITNESS that the fleet
    presented an idle prospect-capable robot to the auction inside the wait --
    nothing downstream measures it. ``correlate_injection`` follows the injected
    ``task_id`` and never compares the auction winner to this robot (an earlier
    draft of this fix claimed it did; it does not), and
    ``evaluate_queue_latency`` follows the same id. So "was any prospect robot
    IDLE at any instant since the injection?" is exactly the question, and it is
    answered from the recorded HISTORY rather than by re-reading a level.

    THAT IS D-34. ``latest_state`` returns ``samples[-1]``, so this loop used to
    ask "is it IDLE right now?" every second about a state the FSM crosses in
    0.247-0.301 s against a 0.5 s publish period. Both 2026-07-31 gate runs
    missed it, both times SKIPped checks 6 and 9, and both times the system had
    done exactly what the rows assert. ``states_since`` reads the same recording
    the probe was already keeping and throwing away.
    """
    wait_start = time.time()
    end = wait_start + deadline_sec
    while time.time() < end:
        for rid in fleet:
            sample = probe.latest_state(rid)
            if sample is None or 'prospect' not in sample['capabilities']:
                continue
            if sample['fsm_state'] == 'IDLE':
                return rid, 'the robot was already idle'
            for past in probe.states_since(rid, wait_start):
                if past['fsm_state'] == 'IDLE':
                    return rid, ('%s was IDLE %.2fs into the wait; the level '
                                 'read this gate used until D-34 would have '
                                 'missed it'
                                 % (rid, past['recv'] - wait_start))
        time.sleep(1.0)

    if not allow_freeing:
        return None, ('no prospect-capable robot became IDLE within %.0fs '
                      'and --no-free-robot was given' % (deadline_sec,))

    candidates = []
    for rid in fleet:
        sample = probe.latest_state(rid)
        if sample is None or 'prospect' not in sample['capabilities']:
            continue
        if sample['fsm_state'] not in ('OFFLINE', 'ERROR'):
            candidates.append(rid)
    if not candidates:
        return None, 'no prospect-capable robot is reachable'

    freed = candidates[0]
    cut = time.time()
    response = probe.override(freed, 'cancel_task')
    success = bool(response.success) if response is not None else False
    message = str(response.message) if response is not None else ''
    ok, kind, note = freeing_receipt(success, message, [], [], freed, task_id)
    if not ok:
        return None, ('no prospect-capable robot became IDLE in %.0fs and %s'
                      % (deadline_sec, note))

    # The verdict is already decided by the line above. This loop only looks
    # for DURABLE corroboration to put in the report, and its expiry costs the
    # row nothing -- which is the whole difference from the settle loop it
    # replaces, whose 10 s expiry was a SKIP on two consecutive runs.
    corroborate_by = time.time() + FREE_CORROBORATION_SEC
    while time.time() < corroborate_by:
        with probe.lock:
            assignments = list(probe.assignments)
        ok, kind, note = freeing_receipt(success, message,
                                         probe.states_since(freed, cut),
                                         assignments, freed, task_id)
        if kind:
            break
        time.sleep(0.25)
    return freed, ('no robot became IDLE in %.0fs, so %s was freed with an '
                   'operator cancel_task first — this row was measured on a '
                   'robot the gate perturbed. %s'
                   % (deadline_sec, freed, note))


def queue_snapshots(frames):
    """Normalise recorded ``/orchestrator/task_queue`` frames for the clause below.

    *frames* is what ``RosbridgeClient.frames`` returns —
    ``(arrived, topic, msg, nbytes)`` — and the result is
    ``[(arrived, {task_id: (status, status_reason)}), ...]``, oldest first, with
    anything undecodable dropped rather than guessed at.

    SEPARATE FROM THE PREDICATES THAT READ IT, and pure, so the ROS-free lane
    can pin the decoding independently of the decisions. These frames are JSON
    this probe did not build; a key that moved would otherwise surface as a
    wrong verdict about the orchestrator rather than as a decoding failure in
    the gate, which is the D-10 shape at reduced amplitude.

    ``status_reason`` defaults to '' rather than raising: a build whose
    TaskStatus predates the field is a build with no preemption to corroborate,
    and ``evaluate_preemption`` refuses that run for a reason it can name.
    """
    out = []
    for frame in frames:
        arrived, _topic, msg, _nbytes = frame
        if not isinstance(msg, dict):
            continue
        tasks = {}
        for task in msg.get('tasks') or []:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get('task_id') or '')
            if not task_id:
                continue
            tasks[task_id] = (str(task.get('status') or ''),
                              str(task.get('status_reason') or ''))
        out.append((float(arrived), tasks))
    out.sort(key=lambda item: item[0])
    return out


def preemption_precondition(snapshots, inject_time, injected_task_id,
                            auction_timeout):
    """Was another task PROVABLY under auction at the injection? -> (id, note).

    The id is None whenever nothing can be proved, and the note always names
    WHICH observation was used and over WHAT window — this clause exists to
    corroborate a semantics change, and a corroboration that cannot say what it
    looked at corroborates nothing.

    THE OBSERVATION. The newest ``/orchestrator/task_queue`` snapshot that
    arrived AT OR BEFORE ``inject_time``. That topic is a complete 2 Hz snapshot
    of the task table (D-03), carrying ``status`` and ``status_reason`` per
    entry, and it is the only instrument in this probe that can see an auction
    that this gate is not itself the cause of. ``probe.announcements`` cannot:
    it records that a task was announced, never that its auction is still open,
    and it can never see a ``status_reason`` at all — so a precondition
    established from the DDS stream could never have its consequence checked by
    the same instrument, and every websocket-less run would become a FAIL about
    the wrong thing.

    THE PROOF OBLIGATION, AND WHY IT IS NOT JUST "IT SAID AUCTIONING". A task
    seen AUCTIONING 0.4 s before the injection may have resolved 0.1 s before
    it, in which case there was nothing to preempt and demanding a preemption
    would fail a conforming system. So this asks for something stronger and
    checkable: the LAST snapshot in which the candidate was NOT auctioning fixes
    an upper bound on when its auction could have opened, and an auction cannot
    CLOSE BY TIMEOUT before that instant plus ``auction_timeout_sec``. When that
    earliest possible timeout is still in the future at the orchestrator's first
    opportunity to act on the injection, the auction was in flight, provably,
    rather than probably.

    "BY TIMEOUT" IS LOAD-BEARING AND IT IS A WEAKER PREMISE THAN THE ONE THIS
    CLAUSE WAS FIRST WRITTEN ON. Until 2026-08-01 ``TaskAuction`` genuinely had
    a single exit — ``is_timed_out``, consumed only by ``_resolve_auction`` —
    and this docstring said so. The emergency-preemption change added a SECOND
    exit, ``_preempt_for_emergency``'s own ``self._auction.reset()``, so
    "cannot have resolved" is no longer implied by the arithmetic: an auction
    can now vanish early, and the thing that vanishes it is a preemption. That
    matters here because the failure it opens is not a missed detection but a
    MISATTRIBUTED one — a preemption caused by something other than this
    injection (a second operator, a dashboard emergency issued mid-run, or the
    D-42 hazard of a whole second SELENE stack on the same domain) leaves
    ``auction_preempted`` on a victim, and ``preemption_outcome`` would credit
    it to this gate's request. The defence is the PRIOR-PREEMPTION SCAN below:
    if any preemption is already visible before the injection, this clause
    refuses the run rather than attributing the next one to itself.

    THREE CONSERVATISMS, ALL IN THE SAFE DIRECTION. ``arrived`` is websocket
    arrival, later than the orchestrator's publish by the transport latency
    check 9 measures, so MAX_TRANSPORT_LATENCY_SEC is subtracted from the bound
    before it is used — without it the bound leans toward claiming "in flight",
    which is the direction that manufactures failures. The staleness cap uses
    the same inflated ``arrived``, which makes a marginal snapshot look older
    and pushes the clause toward NOT APPLICABLE. And the deadline the bound is
    compared against is ``inject_time`` plus one full
    ORCHESTRATOR_AUCTION_TICK_SEC, because a preemption can only happen on a
    tick and the first tick after the injection is up to a period away.
    """
    pre = [item for item in snapshots if item[0] <= inject_time]
    if not pre:
        return None, ('no %s snapshot arrived at or before the injection, so '
                      'the queue state at that instant was never observed'
                      % (TASK_QUEUE_TOPIC,))

    # THE PRIOR-PREEMPTION SCAN. Whole recording up to the injection, every
    # task, not just the eventual victim: any preemption already visible means
    # something OTHER than this request is issuing emergencies at this
    # orchestrator, and this clause cannot then tell its own consequence from
    # somebody else's. NOT APPLICABLE, with the mechanism named, because a gate
    # that credits itself with another actor's effect is worse than one that
    # declines to measure.
    for snap_arrived, snap_tasks in pre:
        for other_id, other in snap_tasks.items():
            if other[1] == AUCTION_PREEMPTED:
                return None, (
                    'a preemption was ALREADY visible before this injection — '
                    '%s carried status_reason %r in the %s snapshot %.2fs '
                    'before it. Something other than this request is issuing '
                    'emergency injections at this orchestrator (a second '
                    'operator, the dashboard, or a second SELENE stack sharing '
                    'the domain — register D-42), so a preemption observed '
                    'after the injection cannot be attributed to it and this '
                    'clause asserts nothing'
                    % (other_id, AUCTION_PREEMPTED, TASK_QUEUE_TOPIC,
                       inject_time - snap_arrived))

    arrived, tasks = pre[-1]
    age = inject_time - arrived
    if age > PREEMPT_SNAPSHOT_STALENESS_SEC:
        return None, ('the newest %s snapshot before the injection arrived '
                      '%.2fs before it, past the %.1fs this clause will treat '
                      'as describing the injection instant, so what the '
                      'orchestrator was auctioning at that moment is unknown'
                      % (TASK_QUEUE_TOPIC, age, PREEMPT_SNAPSHOT_STALENESS_SEC))

    candidates = [task_id for task_id, entry in tasks.items()
                  if entry[0] == QUEUE_STATUS_AUCTIONING
                  and task_id != injected_task_id]
    if not candidates:
        return None, ('no auction was in flight at injection — the %s snapshot '
                      '%.2fs before it showed %d task(s) and none of them, '
                      'other than the injected task itself, in %s'
                      % (TASK_QUEUE_TOPIC, age, len(tasks),
                         QUEUE_STATUS_AUCTIONING))

    unproven = []
    for task_id in candidates:
        opened_after = None
        for snap_arrived, snap_tasks in pre:
            entry = snap_tasks.get(task_id)
            if entry is None or entry[0] != QUEUE_STATUS_AUCTIONING:
                opened_after = snap_arrived
        if opened_after is None:
            unproven.append('%s was already %s in the oldest snapshot '
                            'recorded, so the instant its auction opened was '
                            'never observed and its age cannot be bounded'
                            % (task_id, QUEUE_STATUS_AUCTIONING))
            continue
        earliest_timeout = (opened_after - MAX_TRANSPORT_LATENCY_SEC
                            + float(auction_timeout))
        # The orchestrator's FIRST OPPORTUNITY TO ACT, not the injection
        # instant. _auction_tick runs on a 0.5 s timer and a preemption can
        # only happen on one of those ticks; an auction with 0.05 s of window
        # left at the injection is correctly RESOLVED by that tick rather than
        # preempted, and requiring it to still be open at inject_time would
        # make the gate fail a conforming orchestrator.
        must_survive_until = inject_time + ORCHESTRATOR_AUCTION_TICK_SEC
        if earliest_timeout <= must_survive_until:
            unproven.append('%s was %s at the injection but had been so for '
                            'long enough that its own %.1fs auction window '
                            'could have expired before the orchestrator\'s '
                            'next %.1fs auction tick (%.2fs of slack), so it '
                            'cannot be shown there was anything left to '
                            'preempt when the orchestrator could first have '
                            'acted'
                            % (task_id, QUEUE_STATUS_AUCTIONING,
                               float(auction_timeout),
                               ORCHESTRATOR_AUCTION_TICK_SEC,
                               must_survive_until - earliest_timeout))
            continue
        return task_id, ('%s was %s in the %s snapshot %.2fs before the '
                         'injection, and its auction opened no earlier than '
                         '%.2fs before that, so with a %.1fs auction window it '
                         'could not have timed out for another %.2fs — %.2fs '
                         'past the orchestrator\'s next %.1fs auction tick, so '
                         'it was in flight when the orchestrator could first '
                         'have acted on the injection'
                         % (task_id, QUEUE_STATUS_AUCTIONING, TASK_QUEUE_TOPIC,
                            age, arrived - opened_after,
                            float(auction_timeout),
                            earliest_timeout - inject_time,
                            earliest_timeout - must_survive_until,
                            ORCHESTRATOR_AUCTION_TICK_SEC))
    return None, ('%d task(s) were %s at the injection but none provably still '
                  'in flight: %s'
                  % (len(candidates), QUEUE_STATUS_AUCTIONING,
                     '; '.join(unproven)))


def preemption_outcome(snapshots, victim, inject_time):
    """Did *victim* leave AUCTIONING carrying 'auction_preempted'? -> (status, note).

    Reads the first post-injection snapshot in which *victim* is no longer
    AUCTIONING and reports what carried it out. ``status_reason`` is a durable
    field on the queue entry, not an event, so the 2 Hz snapshot cannot miss it:
    it stands until the task is next auctioned, and the emergency task holds the
    single auction slot for a full ``auction_timeout_sec`` before that can
    happen.

    NEVER RETURNS A VALUE THAT PASSES A ROW. The two outcomes are "corroborated"
    and "not corroborated"; the caller turns the second into a problem and the
    first into a sentence.
    """
    post = [item for item in snapshots if item[0] > inject_time]
    if not post:
        return PREEMPT_NOT_CORROBORATED, (
            '%s was under auction at the injection but no %s snapshot arrived '
            'after it, so nothing was observed either way'
            % (victim, TASK_QUEUE_TOPIC))
    for arrived, tasks in post:
        entry = tasks.get(victim)
        if entry is None:
            return PREEMPT_NOT_CORROBORATED, (
                '%s vanished from the queue snapshot %.2fs after the '
                'injection without ever being seen leaving %s, so no '
                'status_reason was carried for it'
                % (victim, arrived - inject_time, QUEUE_STATUS_AUCTIONING))
        status, reason = entry
        if status == QUEUE_STATUS_AUCTIONING:
            continue
        if reason == AUCTION_PREEMPTED:
            return PREEMPT_CORROBORATED, (
                '%s left %s %.2fs after the injection, to %s with '
                'status_reason %r'
                % (victim, QUEUE_STATUS_AUCTIONING, arrived - inject_time,
                   status, reason))
        return PREEMPT_NOT_CORROBORATED, (
            '%s left %s %.2fs after the injection, but to %s with '
            'status_reason %r rather than %r — the emergency injection did not '
            'abort it'
            % (victim, QUEUE_STATUS_AUCTIONING, arrived - inject_time, status,
               reason or '(empty)', AUCTION_PREEMPTED))
    return PREEMPT_NOT_CORROBORATED, (
        '%s was still %s in every one of the %d snapshot(s) recorded after the '
        'injection, the newest %.2fs after it'
        % (victim, QUEUE_STATUS_AUCTIONING, len(post),
           post[-1][0] - inject_time))


def evaluate_preemption(snapshots, inject_time, injected_task_id,
                        auction_timeout, emergency_carried, queue_note):
    """The CONDITIONAL half of check 6. -> (status, note).

    CONDITIONAL, NOT A NEW UNCONDITIONAL ASSERTION. Check 6's row is PRD row 4,
    "Operator-injected task enters auction and gets assigned"; nothing in it
    concerns preemption. What the emergency stimulus adds is a consequence that
    is only observable WHEN AN AUCTION WAS IN FLIGHT, and on a fleet with no
    auction open at the injection there is nothing to observe. So there are
    three outcomes and only one of them can fail the row:

    * NOT APPLICABLE — the precondition did not hold, or the instrument that
      would have measured it was not available. Asserts nothing, and SAYS SO in
      the report rather than passing silently, which is the difference between
      a gate that declined to measure and a gate that measured and was happy.
    * CORROBORATED — the victim left AUCTIONING with ``auction_preempted``.
    * NOT CORROBORATED — the precondition held and the consequence did not
      arrive. The caller adds this to check 6's problem list, so the row FAILS.

    *queue_note*, when non-empty, is the reason the queue snapshot stream was
    unusable and is reported verbatim; the caller owns that string because only
    it knows whether the gap was the websocket or the message type.
    """
    if not emergency_carried:
        return PREEMPT_NOT_APPLICABLE, (
            'the injection did not carry emergency=True (this workspace\'s '
            'InjectTask.srv has no such field), so no preemption was requested '
            'and none is required')
    if queue_note:
        return PREEMPT_NOT_APPLICABLE, queue_note
    if not snapshots:
        return PREEMPT_NOT_APPLICABLE, (
            'no %s snapshot was decoded from the websocket recording at all, '
            'so the queue state around the injection was never observed'
            % (TASK_QUEUE_TOPIC,))
    victim, why = preemption_precondition(snapshots, inject_time,
                                          injected_task_id, auction_timeout)
    if victim is None:
        return PREEMPT_NOT_APPLICABLE, why
    status, note = preemption_outcome(snapshots, victim, inject_time)
    return status, '%s; %s' % (why, note)


def preemption_sentence(status, note):
    """The clause's one sentence for the report, in the probe's own voice."""
    if status == PREEMPT_CORROBORATED:
        return 'PREEMPTION CORROBORATED: %s' % (note,)
    if status == PREEMPT_NOT_APPLICABLE:
        return ('preemption corroboration NOT APPLICABLE and nothing about '
                'preemption is asserted by this row: %s' % (note,))
    return 'PREEMPTION NOT CORROBORATED: %s' % (note,)


def run_injection(results, probe, ws, target_xy):
    """Check 5 only. Returns ``(task_id, inject_time, emergency)``.

    ``task_id`` is '' on failure; ``emergency`` is whether the request really
    carried the flag, which check 6 needs in order to know whether it is allowed
    to require a preemption.

    EXPECTED WALL CLOCK: under a second, up to 15 s if the websocket call has to
    time out and fall back.

    THIS IS THE STIMULUS, AND IT RUNS BEFORE A ROBOT IS FREED — see the comment
    on the stimulus timeline in ``main``. Correlating the id is
    ``correlate_injection``; keeping the two apart is what lets the task be
    queued first.

    TRANSPORT. The injection goes over the rosbridge websocket when one is
    available, because that is the transport the dashboard uses and PRD row 4's
    method says "inject via dashboard". Without tornado it falls back to the ROS
    service, and the row names which transport was used — never silently.

    THE INJECTION IS AN EMERGENCY ONE, ON BOTH TRANSPORTS, FROM ONE DECISION.
    ``probe.injection_carries_emergency()`` is consulted once, off the generated
    type, and the same answer builds the websocket ``args`` dict and the rclpy
    ``Request``. Two independent spellings of the same flag is exactly how one
    transport would end up measuring emergency preemption and the other
    wait-your-turn, under one report sentence that could not be true of both.
    """
    target_x, target_y = target_xy
    transport = 'rosbridge websocket (call_service)'
    task_id = ''
    message = ''
    ok = False

    # Decided BEFORE either transport is chosen, so both carry the same thing.
    # A build whose InjectTask.srv predates the field gets False here and is
    # injected exactly as it was before this change — no crash, and check 6's
    # corroboration clause turns itself off rather than failing that build for
    # not doing something it was never asked to do.
    emergency = probe.injection_carries_emergency()

    if ws is not None and ws.available:
        args = {'task_type': 'prospect',
                'target_location': {'x': target_x, 'y': target_y, 'z': 0.0},
                'quantity': 0.0,
                'assigned_robot_id': ''}
        if emergency:
            # Omitted rather than sent as False on an older build: rosbridge's
            # populate_instance raises NonexistentFieldException on a field the
            # .srv does not have, which would fail check 5 on a workspace that
            # is merely older than this probe.
            args['emergency'] = True
        reply = ws.call_service(
            '/orchestrator/inject_task', 'selene_msgs/srv/InjectTask',
            args, timeout_sec=15.0)
        if reply is not None and reply.get('result', False):
            values = reply.get('values') or {}
            ok = bool(values.get('success'))
            task_id = str(values.get('task_id', ''))
            message = str(values.get('message', ''))
        else:
            transport = 'rosbridge websocket returned nothing; ROS service'
    if not ok and not task_id:
        # Only when the websocket produced no task id at all. A websocket call
        # that timed out after the orchestrator had already queued the task
        # would leave one extra PENDING prospect task behind; that is visible in
        # the queue and harmless to the fleet, and it is the price of not
        # reporting a false FAIL on a slow bridge.
        transport = 'ROS service client (rclpy)'
        response = probe.inject_task('prospect', target_x, target_y,
                                     emergency=emergency)
        if response is not None:
            ok = bool(response.success)
            task_id = str(response.task_id)
            message = str(response.message)

    inject_time = time.time()
    if emergency:
        emergency_note = (
            'THIS IS AN EMERGENCY INJECTION: emergency=True is set on the '
            'InjectTask request over BOTH transports — the rosbridge '
            'call_service args and the rclpy fallback — from one decision taken '
            'off the generated type, so the two cannot disagree about the '
            'semantics this row measures. %s. And %s'
            % (EMERGENCY_SEMANTICS, EMERGENCY_NOT_TESTED))
    else:
        emergency_note = (
            'NOT AN EMERGENCY INJECTION: this workspace\'s InjectTask.srv has '
            'no emergency field, so the request could not carry one and this '
            'row measured the pre-emergency wait-your-turn semantics. Check '
            '6\'s preemption corroboration reports itself NOT APPLICABLE on '
            'this run and asserts nothing')
    results.measured(5, transport=transport, task_id=task_id,
                     target=[target_x, target_y], emergency=emergency)
    if not ok:
        results.set(5, FAIL,
                    'inject_task via %s returned success=False (%s). %s'
                    % (transport, message or 'no message', emergency_note))
        return '', inject_time, emergency
    results.set(5, PASS, 'inject_task via %s returned task_id=%s (%s). %s'
                % (transport, task_id, message or 'no message', emergency_note))
    return task_id, inject_time, emergency


def correlate_injection(results, probe, task_id, inject_time, auction_timeout,
                        target_xy, note, chosen='', ws=None, emergency=False,
                        queue_topic_available=False):
    """Check 6 — the injected id, through announcement and assignment.

    *chosen* is the robot ``pick_prospect_robot`` returned. IT IS REPORTED AND
    NEVER ASSERTED. This function correlates a task_id; it does not compare the
    auction winner to *chosen* and never has, so a report that implied the two
    were the same would be claiming a correlation nobody measured. When they
    differ the row says so.

    WHAT THE EMERGENCY STIMULUS CHANGES HERE, AND WHAT IT DOES NOT. The primary
    assertion is unchanged and is still the whole of the PASS: the injected id
    has to appear on ``/orchestrator/task_announcement`` and on
    ``/orchestrator/task_assignment`` with its target matched to 1e-3, inside
    ``auction_timeout_sec`` + 10 s. What is added is a CONDITIONAL
    corroboration — see ``evaluate_preemption`` — which can turn a PASS into a
    FAIL and can never do the reverse. The row now measures the emergency path
    and only the emergency path, and says so.

    EXPECTED WALL CLOCK: ``auction_timeout_sec`` + 10 s (about 15 s at the
    shipped default of 5.0).

    THE FLAG IS ALSO READ OFF THE WIRE. ``TaskAnnouncement.emergency`` is
    recorded by ``_on_announcement`` and, when the injection really carried the
    field, this row requires the announcement for the injected task_id to carry
    it too. That is the whole reason the announcement hop is not another
    "declared and never read" field: without a reader, an edit dropping
    ``msg.emergency`` from ``_publish_announcement`` would turn one unit test
    red and nothing else in the system, live or measured, would notice.

    THE BUDGET STARTS HERE, NOT AT THE INJECTION. ``main`` queues the task
    before it frees a robot, so the injected task can sit correctly PENDING for
    as long as ``pick_prospect_robot`` waits: ``_auction_tick`` returns
    immediately when no robot is idle (``orchestrator_node.py:1566-1569``).
    Budgeting from the injection would charge that wait to the orchestrator and
    fail a healthy fleet. The latencies REPORTED are still measured from the
    injection, with the idle wait stated separately in the same sentence, so the
    two numbers cannot be read as one.
    """
    target_x, target_y = target_xy
    correlate_start = time.time()
    idle_wait = correlate_start - inject_time
    budget = float(auction_timeout) + 10.0
    deadline = correlate_start + budget
    announcement = None
    assignment = None
    while time.time() < deadline and assignment is None:
        with probe.lock:
            announcements = list(probe.announcements)
            assignments = list(probe.assignments)
        for record in announcements:
            if record[1] == task_id and announcement is None:
                announcement = record
        for record in assignments:
            if record[1] == task_id:
                assignment = record
        time.sleep(0.2)

    # ---- The emergency clause, computed ONCE and reported on every path. ----
    #
    # EVALUATED HERE, AFTER THE CORRELATION LOOP, because the loop has by now
    # been running for tens of seconds past the injection and the websocket
    # buffer is never cleared or windowed — the snapshots covering the injection
    # instant and the half-second after it are all still in it. Evaluating
    # earlier would ask the question before the answer could have arrived.
    #
    # IT IS COMPUTED ON THE FAILURE PATHS TOO. A row that fails its primary
    # assertion is exactly the row whose reader most wants to know whether the
    # emergency path was even exercised, and dropping the sentence there would
    # make "check 6 failed" mean two different things on two different runs.
    if ws is None or not ws.available:
        queue_note = ('this clause reads %s, and this probe subscribes to that '
                      'topic ONLY over the rosbridge websocket — none was '
                      'available on this run, so the queue state at the '
                      'injection was never observed'
                      % (TASK_QUEUE_TOPIC,))
    elif not queue_topic_available:
        queue_note = ('this build has no selene_msgs/msg/TaskQueueState, so %s '
                      'was never subscribed and the queue state at the '
                      'injection was never observed (that topic arrives with '
                      'D-03)' % (TASK_QUEUE_TOPIC,))
    else:
        queue_note = ''
    snapshots = (queue_snapshots(ws.frames(TASK_QUEUE_TOPIC))
                 if ws is not None and ws.available else [])
    preempt_status, preempt_note = evaluate_preemption(
        snapshots, inject_time, task_id, auction_timeout, emergency, queue_note)
    preempt_sentence = preemption_sentence(preempt_status, preempt_note)

    if emergency:
        emergency_sentence = (
            'THE STIMULUS FOR THIS ROW IS AN EMERGENCY INJECTION, so what is '
            'measured here is the emergency path and nothing else: %s. And %s'
            % (EMERGENCY_SEMANTICS, EMERGENCY_NOT_TESTED))
    else:
        emergency_sentence = (
            'THE STIMULUS FOR THIS ROW WAS NOT AN EMERGENCY INJECTION: this '
            'workspace\'s InjectTask.srv has no emergency field, so this run '
            'measured the pre-emergency wait-your-turn semantics and %s'
            % (EMERGENCY_NOT_TESTED,))

    # Recorded before any branch returns, so --json-out carries the clause on a
    # failed row as well as a passed one.
    results.measured(6, task_id=task_id, emergency=emergency,
                     preemption=preempt_status, preemption_note=preempt_note,
                     task_queue_snapshots=len(snapshots))

    if announcement is None:
        results.set(6, FAIL,
                    'no task_announcement carrying task_id=%s within %.0fs of '
                    'a prospect-capable robot being idle (%s). The old gate '
                    'accepted ANY announcement here, and ten HTN survey tasks '
                    'are queued at startup. %s. %s'
                    % (task_id, budget, note, emergency_sentence,
                       preempt_sentence))
        return
    announce_latency = announcement[0] - inject_time
    if assignment is None:
        # NAME WHICH FAILURE THIS IS. "Never assigned" covers two different
        # systems: an auction that never ran at all, and one that ran and gave
        # this task to nobody. The recorded assignment traffic separates them
        # and costs nothing to report.
        with probe.lock:
            others = [record for record in probe.assignments
                      if record[1] != task_id]
        results.set(6, FAIL,
                    'task %s was announced %.2fs after injection but was never '
                    'assigned within the following %.0fs. %d assignment(s) of '
                    'OTHER tasks were seen in that window%s (%s). %s. %s'
                    % (task_id, announce_latency, budget, len(others),
                       ' — the auction ran and this task did not win it'
                       if others else
                       ' — no auction resolved at all in that window',
                       note, emergency_sentence, preempt_sentence))
        return

    assign_latency = assignment[0] - inject_time
    winner = assignment[2]
    problems = []
    # Matching the target to 1e-3 is what proves this is the SAME task and not
    # an id coincidence with an HTN survey waypoint.
    if (abs(announcement[3] - target_x) > 1e-3
            or abs(announcement[4] - target_y) > 1e-3):
        problems.append('announced target (%.4f, %.4f) != injected (%.4f, %.4f)'
                        % (announcement[3], announcement[4],
                           target_x, target_y))
    if (abs(assignment[3] - target_x) > 1e-3
            or abs(assignment[4] - target_y) > 1e-3):
        problems.append('assigned target (%.4f, %.4f) != injected (%.4f, %.4f)'
                        % (assignment[3], assignment[4], target_x, target_y))
    winner_state = probe.latest_state(winner)
    if winner_state is None:
        problems.append('winner %s publishes no state' % (winner,))
    elif 'prospect' not in winner_state['capabilities']:
        problems.append('winner %s lacks the prospect capability (%s)'
                        % (winner, winner_state['capabilities']))

    # THE FLAG, END TO END ON THE WIRE. The injection set
    # InjectTask.emergency; this asserts TaskAnnouncement.emergency came back
    # out carrying it, through DDS, on the announcement for THIS task_id.
    #
    # Asserted only when the request really carried the field — on a workspace
    # whose InjectTask.srv predates it, `emergency` is False, the announcement
    # is False, and there is nothing to check. It is a one-directional test for
    # that reason: False == False would also hold on a build where
    # _publish_announcement never sets the field at all.
    announced_emergency = announcement[5] if len(announcement) > 5 else False
    if emergency and not announced_emergency:
        problems.append(
            'the injection carried emergency=True but the task_announcement '
            'for %s carried emergency=False — the flag did not survive '
            'inject_task_logic -> TaskEntry -> _publish_announcement, so the '
            'stimulus this row believes it applied is not the one that reached '
            'the wire' % (task_id,))

    winner_note = ''
    if chosen and winner != chosen:
        winner_note = ('. The auction was won by %s, not by %s, which is the '
                       'robot this gate observed idle — that is legal (row 4 '
                       'is indifferent to which robot wins) and is stated '
                       'because nothing here measured a link between them'
                       % (winner, chosen))

    # THE CLAUSE CAN FAIL THIS ROW AND CAN NEVER PASS IT. It is appended to
    # `problems`, so a run whose primary correlation succeeded but whose
    # provably-in-flight auction was not aborted is a FAIL; a CORROBORATED or
    # NOT APPLICABLE clause adds a sentence and no assertion, and the row is
    # still passed by the announcement/assignment correlation above or not at
    # all.
    if preempt_status == PREEMPT_NOT_CORROBORATED:
        problems.append(preempt_sentence)
        # Already inside the problem list; appending it again below would print
        # the same sentence twice in one cell.
        tail = emergency_sentence
    else:
        tail = '%s. %s' % (emergency_sentence, preempt_sentence)

    results.measured(6, task_id=task_id, winner=winner, witness=chosen,
                     announce_latency_sec=round(announce_latency, 3),
                     assign_latency_sec=round(assign_latency, 3),
                     idle_wait_sec=round(idle_wait, 3),
                     announced_emergency=announced_emergency)
    if problems:
        results.set(6, FAIL, '%s. %s' % ('; '.join(problems), tail))
    else:
        results.set(6, PASS,
                    'task %s announced %.2fs and assigned to %s %.2fs after '
                    'injection, target matched to 1e-3; %.1fs of that was the '
                    'gate waiting for an idle prospect-capable robot (%s)%s. %s'
                    % (task_id, announce_latency, winner, assign_latency,
                       idle_wait, note, winner_note, tail))


def evaluate_queue_latency(results, probe, ws, task_id, queue_topic_available):
    """Check 9 — PRD row 3, "task queue reflects orchestrator state within 1 s".

    EXPECTED WALL CLOCK: up to MAX_QUEUE_REACTION_SEC + QUEUE_POLL_MARGIN_SEC,
    and typically a fraction of that. No extra stimulus: both numbers come off
    the assignment event check 6 already caused.

    (a) TRANSPORT LATENCY: websocket arrival of a RobotState minus that
        message's own ``stamp``. Isolates DDS + rosbridge with no quantisation.
    (b) REACTION LATENCY: websocket arrival of the first ``TaskQueueState``
        whose ``tasks`` contains the injected task as ASSIGNED, minus the DDS
        observation of the ``TaskAssignment`` for it.

    WHAT THIS BOUNDS. The snapshot is published at 2 Hz, so (b) carries up to
    500 ms of sampling quantisation, and the React reducer and canvas draw are
    not measured at all. This row is therefore bounded FROM BELOW: it can prove
    a FAIL, and proves a PASS only up to the rendering step.
    """
    if ws is None or not ws.available:
        results.set(9, SKIP, 'no rosbridge websocket, so neither latency could '
                             'be measured on the transport the dashboard uses')
        return
    if not task_id:
        results.set(9, SKIP, 'no injected task to follow into the queue')
        return
    if not queue_topic_available:
        # Whether the message type exists is known in main() at import time
        # (``from selene_msgs.msg import TaskQueueState``), so it is stated here
        # as a fact rather than guessed at from an empty buffer. A build without
        # it was never subscribed to the topic and this row is genuinely
        # unmeasurable; a build WITH it that produces no snapshot is a failure,
        # not a gap, and is reported as one below.
        results.set(9, SKIP,
                    'this build has no selene_msgs/msg/TaskQueueState, so '
                    '/orchestrator/task_queue was never subscribed. That topic '
                    'arrives with D-03')
        return

    with probe.lock:
        assignments = [a for a in probe.assignments if a[1] == task_id]
    if not assignments:
        results.set(9, SKIP, 'task %s was never assigned, so there is no '
                             'orchestrator event to react to' % (task_id,))
        return
    # The LAST assignment for this id, not the first: a task that was
    # interrupted and re-auctioned is assigned more than once, and the snapshot
    # that shows it ASSIGNED reflects the most recent one. It also keeps the
    # poll deadline below from being computed off a stale event. Check 6 picks
    # the same record for the same reason (its scan overwrites as it goes).
    assigned_at = assignments[-1][0]

    problems = []
    latencies = []
    for arrived, topic, msg, _nbytes in ws.frames():
        if not topic.endswith('/state') or not isinstance(msg, dict):
            continue
        stamp = msg.get('stamp') or {}
        if stamp.get('sec') is None:
            continue
        stamped = float(stamp['sec']) + float(stamp.get('nanosec') or 0) * 1e-9
        if stamped > 0.0:
            latencies.append(arrived - stamped)
    transport_median = None
    if not latencies:
        problems.append('no RobotState frames arrived over the websocket')
    else:
        latencies.sort()
        transport_median = latencies[len(latencies) // 2]
        if transport_median > MAX_TRANSPORT_LATENCY_SEC:
            problems.append('median transport latency %.3fs > %.3fs'
                            % (transport_median, MAX_TRANSPORT_LATENCY_SEC))

    # POLL FOR THE SNAPSHOT; DO NOT SAMPLE THE BUFFER ONCE.
    # /orchestrator/task_queue is published only from a timer — the timer is
    # created at orchestrator_node.py:1212 and :1794 is the sole
    # ``self._task_queue_pub.publish(msg)`` call site, so there is no
    # publish-on-status-change anywhere. The snapshot that first carries T as
    # ASSIGNED is therefore due uniformly in [0, 1 / task_queue_publish_rate]
    # after the assignment (500 ms at the shipped 2.0 Hz), plus a rosbridge hop.
    # ``correlate_injection`` returns within ~0.2 s of the DDS TaskAssignment
    # callback, so reading the buffer once at this point found nothing in a
    # large fraction of HEALTHY runs: exit 2 on a working system, and a report
    # row blaming a missing message type for the probe's own timing.
    #
    # AND THE TIMEOUT IS A FAIL, NOT A SKIP. PRD row 3 is "task queue reflects
    # orchestrator state within 1 second"; a queue that has not reflected the
    # assignment by then is the row failing. The genuinely unmeasurable cases —
    # no websocket, no task, never assigned, no such message type in this build
    # — are all handled above and stay SKIP.
    reaction = None
    poll_deadline = (assigned_at + MAX_QUEUE_REACTION_SEC
                     + QUEUE_POLL_MARGIN_SEC)
    while True:
        for arrived, _topic, msg, _nbytes in ws.frames(TASK_QUEUE_TOPIC):
            if not isinstance(msg, dict):
                continue
            for task in msg.get('tasks') or []:
                if (task.get('task_id') == task_id
                        and task.get('status') == 'ASSIGNED'):
                    reaction = arrived - assigned_at
                    break
            if reaction is not None:
                break
        if reaction is not None or time.time() >= poll_deadline:
            break
        time.sleep(QUEUE_POLL_INTERVAL_SEC)
    if reaction is None:
        snapshots = len(ws.frames(TASK_QUEUE_TOPIC))
        # Record the half that WAS measured before returning: the transport
        # number is real whether or not the snapshot ever arrived, and losing it
        # from --json-out would make the two failures indistinguishable there.
        results.measured(9, transport_samples=len(latencies),
                         transport_latency_sec=(round(transport_median, 4)
                                                if transport_median is not None
                                                else None),
                         task_queue_frames=snapshots,
                         queue_reaction_sec=None)
        results.set(9, FAIL,
                    'no /orchestrator/task_queue snapshot carried %s as '
                    'ASSIGNED within %.1fs of the TaskAssignment for it '
                    '(%d snapshot(s) arrived over the websocket in total); '
                    'PRD row 3 allows %.1fs'
                    % (task_id, MAX_QUEUE_REACTION_SEC + QUEUE_POLL_MARGIN_SEC,
                       snapshots, MAX_QUEUE_REACTION_SEC))
        return
    if reaction > MAX_QUEUE_REACTION_SEC:
        problems.append('queue reaction %.3fs > %.3fs'
                        % (reaction, MAX_QUEUE_REACTION_SEC))

    results.measured(9, transport_samples=len(latencies),
                     transport_latency_sec=(round(transport_median, 4)
                                            if transport_median is not None
                                            else None),
                     queue_reaction_sec=round(reaction, 4))
    caveat = ('the 2 Hz snapshot carries up to 500 ms of quantisation and the '
              'React reducer and canvas draw are unmeasured, so this bounds '
              'the row from below')
    if problems:
        results.set(9, FAIL, '%s; %s' % ('; '.join(problems), caveat))
    else:
        results.set(9, PASS,
                    'transport %.0f ms (median of %d), queue reaction %.0f ms; '
                    '%s' % (transport_median * 1000.0, len(latencies),
                            reaction * 1000.0, caveat))


def run_force_recharge(results, probe, robot_id):
    """Checks 7 and 8. EXPECTED WALL CLOCK: up to about 8 s."""
    if robot_id is None:
        results.set(7, SKIP, 'no robot was eligible for an override')
        results.set(8, SKIP, 'no robot was eligible for an override')
        return
    response = probe.override(robot_id, 'force_recharge')
    if response is None:
        results.set(7, FAIL, 'override_robot did not answer within 15s')
        results.set(8, SKIP, 'the override was never accepted')
        return
    if not response.success:
        results.set(7, FAIL, '%s force_recharge rejected: %s'
                    % (robot_id, response.message))
        results.set(8, SKIP, 'the override was rejected')
        return
    results.set(7, PASS, '%s force_recharge accepted (%s)'
                % (robot_id, response.message or 'no message'))

    # OPERATOR_RECHARGE is mapped from every state except OFFLINE/ERROR
    # (fsm.py:101-105) and is fired before start_recharge(), so RECHARGING is
    # reached on the agent's next state publish, within 0.5 s. 6 s is a wide
    # margin for the service round trip on a loaded box.
    started = time.time()
    seen = ''
    while time.time() - started < 6.0:
        sample = probe.latest_state(robot_id)
        if sample is not None:
            seen = sample['fsm_state']
            if seen == 'RECHARGING':
                results.set(8, PASS, '%s fsm_state=RECHARGING %.1fs after the '
                                     'override' % (robot_id,
                                                   time.time() - started))
                return
        time.sleep(0.25)
    results.set(8, FAIL, '%s fsm_state=%r 6s after an accepted force_recharge'
                % (robot_id, seen or 'unknown'))


def goto_target(origin, bearing_deg, range_m=GOTO_RANGE_M):
    """Target GOTO_RANGE_M ahead of *origin* at *bearing_deg* off ITS HEADING.

    WHY THE BEARING IS HEADING-RELATIVE, WHICH IS D-35. The old code offered
    four WORLD-axis targets, (+6,0) first, and committed to the first that
    planned. The fleet spawns at x = -45 and drives south-west into the PSR, so
    "+6 m east" was systematically about 165 deg behind the robot under test and
    check 11 spent its window measuring how fast a differential drive can turn
    around. The register measured that manoeuvre: a 164.8 deg sweep, 3.745 m of
    excursion away from the target, and the old pass predicate first going true
    at t ~= 10.2 s inside a 12.0 s window. Two identical runs landed either side
    of it, 33 cm apart. ``pose.theta`` was on the wire the whole time.

    WHY +/-45 AND +/-90 AND NOT 0 OR 180. EXECUTED here, by integrating this
    repository's own steering law (heading-error P control at ang_kp = 1.5,
    yaw capped at the ACHIEVED GOTO_MEASURED_YAW_RATE_RAD_S, linear speed at the
    RCDL max_speed because ``navigator.py:542-549`` clamps it there for a 6 m
    goal whatever the heading error) -- time to close the first
    GOTO_CLOSURE_M = 1.0 m of range:

        bearing      scout    hauler   excavator
          0 deg       2.00 s   2.50 s    3.34 s
         45 deg       2.36 s   2.85 s    3.68 s
         90 deg       4.87 s   5.27 s    5.98 s
        135 deg      10.58 s  10.56 s   10.91 s
        180 deg      16.47 s  16.51 s   16.87 s

    0 deg is excluded because a target dead ahead lets residual coast alone
    supply the closure, and 180 deg is excluded because it is the manoeuvre this
    deviation exists to stop measuring. +/-45 costs 2.4-3.7 s against a derived
    window of 11.0-13.7 s; the sign alternates so a rock on one side does not
    exhaust the list on one side of the robot.

    A NOTE ON WHY EVERY BEARING IS ESSENTIALLY PLANNABLE, which is a currently
    helpful accident resting on an OPEN defect: A* refuses a goal only for
    occupancy or bounds, because ``navigation.max_traversable_slope_deg`` has no
    reader anywhere in production (register D-28). If D-28 is fixed, a
    heading-relative pick may start hitting slope refusals, and the retry loop
    over the remaining bearings is what absorbs that.
    """
    phi = float(origin['theta']) + math.radians(bearing_deg)
    return (float(origin['x']) + range_m * math.cos(phi),
            float(origin['y']) + range_m * math.sin(phi))


def goto_window_seconds(bearing_deg, max_speed_mps):
    """Seconds allowed to close GOTO_CLOSURE_M at *bearing_deg*, DERIVED.

    settle + derate x (time to swing the bearing off + time to cover one cell)

    The 12.0 s literal this replaces was not derived from anything, and the
    fix for a threshold that produced a coin flip is not a bigger threshold --
    that is choosing a number from n = 1. It is a threshold that is a function
    of the manoeuvre being asked for. Values: 11.0 s (scout) / 12.0 (hauler) /
    13.7 (excavator) at 45 deg and 17.1 / 18.1 / 19.8 at 90 deg, against the
    2.4-3.7 s and 4.9-6.0 s the table in ``goto_target`` measures. At the
    164.8 deg the register recorded it yields 27.1 s against that manoeuvre's
    measured ~10.2 s, i.e. the formula covers the very case that produced the
    coin flip -- which is what ``test_phase5_probe_send_to_location.py`` pins.
    """
    speed = float(max_speed_mps)
    if speed <= 0.0:
        speed = GOTO_DEFAULT_MAX_SPEED_MPS
    align_s = abs(math.radians(bearing_deg)) / GOTO_MEASURED_YAW_RATE_RAD_S
    close_s = GOTO_CLOSURE_M / speed
    return GOTO_SETTLE_S + GOTO_KINEMATIC_DERATE * (align_s + close_s)


def read_rcdl_max_speed(rcdl_dir, robot_type, yaml_module):
    """(max_speed, source) for *robot_type* from its RCDL. Degrades loudly.

    The RCDL is the single source of truth for what a robot can do -- the same
    rule D-06 established for ``capacity_kg`` -- so per-type speeds are never
    hardcoded here. When the file cannot be read the slowest shipped RCDL is
    used, which makes the derived window LONGER (more forgiving of the robot,
    less forgiving of nothing), and the source string says so in the report.
    """
    fallback = 'default %.2f m/s; RCDL not readable' % (
        GOTO_DEFAULT_MAX_SPEED_MPS,)
    if not rcdl_dir or not robot_type:
        return GOTO_DEFAULT_MAX_SPEED_MPS, '%s (no --rcdl-dir)' % (fallback,)
    path = os.path.join(rcdl_dir, '%s.yaml' % (robot_type,))
    try:
        with open(path, 'r') as handle:
            config = yaml_module.safe_load(handle) or {}
        speed = float(config['max_speed'])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log('rcdl %s: %s' % (path, exc))
        return GOTO_DEFAULT_MAX_SPEED_MPS, '%s at %s' % (fallback, path)
    if speed <= 0.0:
        return GOTO_DEFAULT_MAX_SPEED_MPS, '%s: %s declares %.2f' % (
            fallback, path, speed)
    return speed, path


def evaluate_goto_acceptance(robot_id, samples, answered):
    """Assertions (2) and (2b) over one scan of the state history.

    -> ``(baseline, verdict, detail)``. ``baseline`` is the sample the motion
    measurement must start from, or None while the answer is still undecided;
    ``verdict`` is None unless the scan has proved a FAIL. Pure, so every branch
    is reachable from the ROS-free lane.

    WHY THIS IS A FUNCTION AND NOT SIX LINES INSIDE THE POLLING LOOP, which is
    the only thing about it that changed on 2026-07-31. The
    ``startswith('override_goto_')`` predicate below is the mechanism this
    deviation's fix credits with killing the coin flip -- it is what makes the
    motion baseline a sample the agent published AFTER it accepted the override,
    instead of the up-to-0.5 s and ~0.25 m stale pre-call sample the old code
    used off a 2 Hz topic, which is the same order as the 33 cm that separated
    check 11's FAIL from its PASS. An adversarial review measured that the
    predicate was UNPINNED: mutating it to ``if True:`` left all 45 tests green,
    because it lived inside a loop no test could drive without a robot. The
    behaviour here is byte-for-byte the behaviour that was inline; what the
    extraction bought is that a test can now call it. That is the whole change.

    THE PREFIX IS A LITERAL AND DELIBERATELY NOT A MODULE CONSTANT. It is the id
    ``selene_agent/.../operator_command.py:143`` builds for this command and
    nothing else sets. A shared constant would let a rename stay green on both
    sides of a contract whose two halves live in different packages, and the
    gate lane cannot import the agent to check (D-36). The test spells the same
    literal out independently for that reason.

    WHAT IS STILL UNKNOWN: whether a real agent can ever publish a NAVIGATING
    sample with an EMPTY ``current_task_id``. Nothing observed one; the ``task
    and`` guard treats it as undecided rather than as a foreign task, which is
    the forgiving reading, and the test that pins it says it is characterising
    the code rather than a measured behaviour.
    """
    baseline = None
    verdict = None
    detail = ''
    for sample in samples:
        if sample['fsm_state'] != 'NAVIGATING':
            continue
        task = str(sample['current_task_id'])
        if task.startswith('override_goto_'):
            baseline = sample
            break
        if task and sample['recv'] - answered >= GOTO_TASK_ID_GRACE_S:
            # Navigating something that is not this override, a full grace
            # period after the agent said it accepted it. Not a retry: the
            # command was accepted and did not take effect.
            verdict = FAIL
            detail = ('%s: accepted send_to_location but %.1fs later was '
                      'still NAVIGATING task %r rather than an '
                      'override_goto_ pseudo-task'
                      % (robot_id, sample['recv'] - answered,
                         sample['current_task_id']))
    return baseline, verdict, detail


def evaluate_goto_progress(samples, baseline, target, window_s, elapsed_s):
    """Did the robot close range on *target*? -> (verdict, detail, measured).

    ``verdict`` is None while the answer is still undecided, so the caller can
    poll this and stop the moment it is not. Pure: every branch is unit-tested
    in the ROS-free lane.

    WHAT IT MEASURES, AND WHY IT IS STRICTLY MORE THAN THE OLD PREDICATE. The
    old rule was ``moved > 0.2 and dot > 0.0`` -- the SIGN of the displacement's
    dot product with the bearing offset. A sign test is a knife edge by
    construction: any favourable millimetre satisfies it, and 33 cm of wobble
    on a 3.6 m arc is what flipped check 11 between two identical runs. This
    asks for a metre of RANGE CLOSURE, one full nav cell, which no wobble
    supplies.

    THE MINIMUM RANGE OVER THE WINDOW IS USED, NOT THE FINAL RANGE. A robot
    that closes a cell and then drives away still passes here. That is
    deliberate and it is a NARROWING that must not be misread: assertion (3)
    owns "the wheels executed the plan" and assertion (4) -- the planned path
    ending at the commanded target -- owns "it went to the right place".
    Neither one alone means the robot arrived.

    SAMPLES CARRYING pose_valid = false ARE DROPPED, not counted and not
    measured (register D-31: before its first ``/odom_world`` message a robot
    publishes a confident (0, 0)). Dropping them can only push this toward the
    SKIP branch below; it can never manufacture a PASS.
    """
    tx, ty = target
    bx, by = float(baseline['x']), float(baseline['y'])
    base_range = math.hypot(tx - bx, ty - by)

    fresh = []
    seen = set()
    invalid = 0
    for sample in samples:
        if not sample.get('pose_valid', True):
            invalid += 1
            continue
        if sample['recv'] in seen:
            continue
        seen.add(sample['recv'])
        fresh.append(sample)

    measured = {
        'samples': len(fresh),
        'invalid_pose_samples': invalid,
        'baseline_range_m': round(base_range, 3),
        'window_s': round(window_s, 2),
        'elapsed_s': round(elapsed_s, 2),
    }

    if len(fresh) < GOTO_MIN_SAMPLES:
        if elapsed_s >= window_s:
            # D-34's rule. ``latest_state`` replays its cached sample forever,
            # so a dead state topic used to report "moved only 0.000 m" and
            # blame the robot for the gate's own blindness.
            return (SKIP,
                    'state stopped arriving: %d usable samples (%d with '
                    'pose_valid=false) in %.1fs, so no motion measurement is '
                    'possible' % (len(fresh), invalid, elapsed_s),
                    measured)
        return None, 'waiting for state samples', measured

    min_range = min(math.hypot(tx - s['x'], ty - s['y']) for s in fresh)
    moved = max(math.hypot(s['x'] - bx, s['y'] - by) for s in fresh)
    closure = base_range - min_range
    measured.update(closure_m=round(closure, 3),
                    min_range_m=round(min_range, 3),
                    moved_m=round(moved, 3))

    if closure >= GOTO_CLOSURE_M:
        return (PASS,
                'closed %.2f m of the %.2f m range to the target in %.1fs '
                '(needed %.2f m)'
                % (closure, base_range, elapsed_s, GOTO_CLOSURE_M),
                measured)
    if elapsed_s >= GOTO_STALL_S and moved <= GOTO_MOTION_EPS_M:
        return (FAIL,
                'did not move: %.3f m from the baseline in %.1fs, below the '
                '%.2f m floor, and PathFollower itself gives up at %.1fs'
                % (moved, elapsed_s, GOTO_MOTION_EPS_M, GOTO_STALL_S),
                measured)
    if elapsed_s >= window_s:
        return (FAIL,
                'closed only %.2f m of the %.2f m range in %.1fs (moved %.2f m '
                'from the baseline; the window is derived from the bearing and '
                'the robot max speed, not a constant)'
                % (closure, base_range, elapsed_s, moved),
                measured)
    return None, 'in progress', measured


def goto_detail(robot_id, parts, path_note, path_recorded):
    """Assemble check 11's report line. ``path_note`` rides on EVERY verdict.

    REPORTING DEFECT, D-35(1): ``path_note`` used to be interpolated only into
    the PASS branch, so the FAIL run withheld the one piece of evidence that
    showed the override had actually worked -- the planned path ending 0.50 m
    from the commanded target. A gate that reports less on the way down than on
    the way up is worse than useless during a failure.

    When no path was recorded the note is already inside *parts* as a problem,
    and appending it again would print it twice; *path_recorded* is what tells
    the two cases apart.
    """
    text = '; '.join(part for part in parts if part)
    if path_recorded and path_note:
        text = '%s; %s' % (text, path_note) if text else path_note
    return '%s: %s' % (robot_id, text)


# ---- Check 11's SUBJECT. Three pure functions, added 2026-08-01 (D-42). ----


def goto_subject_fitness(sample, critical_threshold):
    """Can this robot be asked to perform check 11's manoeuvre? -> (ok, reason).

    Pure, and every branch is reachable from the ROS-free lane. That is the
    whole reason it is a function: the selection it replaces lived inline in
    ``main`` where no test could drive it, and D-35's verifier established that
    a mechanism with no test that fails without it is not fixed, it is asserted.

    WHAT THIS IS NOT. It is not a health check on the fleet and it renders no
    verdict on any robot. It answers one question -- *would commanding this
    robot measure PRD row 5, or would it measure the rule that countermands the
    operator?* -- from data this probe was ALREADY recording and throwing away.
    On 2026-08-01 check 11 commanded a robot reporting 0.0% battery from
    RETURNING; the energy-critical rule fired six milliseconds after the FSM
    accepted the override, and the check reported that as a send_to_location
    failure. ``battery_level`` was in every sample ``_make_state_cb`` built and
    had exactly one reader in this file: a ``[0, 1]`` range assertion in check 4
    that ``0.0`` satisfies. See register D-42.

    THE THRESHOLD IS PASSED IN, NEVER HARDCODED. It is the agent's own
    ``energy_critical_threshold``, read off ``/agent_<rid>`` by the caller. A
    literal here would be this gate asserting its assumptions about a value the
    running system owns, which is D-12.
    """
    if sample is None:
        return False, GOTO_NO_STATE_REASON
    state = str(sample.get('fsm_state', ''))
    if state in GOTO_UNFIT_STATES:
        return False, ('fsm_state %s -- already under a rule that outranks the '
                       'operator command this check issues' % (state,))
    if not sample.get('pose_valid', True):
        return False, ('pose_valid=false, so assertion (3) could measure no '
                       'displacement from it (register D-31)')
    floor = float(critical_threshold) + GOTO_MIN_BATTERY_MARGIN
    charge = float(sample.get('battery_level', 0.0))
    if charge <= floor:
        return False, ('battery_level %.1f%% at or below the %.1f%% floor '
                       "(the agent's own energy_critical_threshold %.1f%% plus "
                       'a %.1f%% margin for the drain of the manoeuvre)'
                       % (charge * 100.0, floor * 100.0,
                          float(critical_threshold) * 100.0,
                          GOTO_MIN_BATTERY_MARGIN * 100.0))
    return True, ''


def select_goto_robot(fleet, samples, thresholds, exclude=()):
    """Check 11's subject. -> ``(robot_id or None, rejections)``. Pure.

    *samples* is ``{rid: latest_state_sample or None}``, *thresholds* is
    ``{rid: energy_critical_threshold}``, *exclude* holds robots another check
    has already claimed. ``rejections`` is ``[(rid, reason), ...]`` for every
    robot examined and passed over, in fleet order, so the report can say what
    was rejected and why on EVERY verdict -- including a PASS.

    FIRST FIT WINS AND THE SCAN STOPS THERE, deliberately: robots after the
    winner are not examined and get no entry. Ranking candidates by charge would
    make the subject depend on a quantity that moves between runs and would make
    two runs of the same commit incomparable, which is the property D-10 needs
    from this gate above all others.

    THIS IS A PRECONDITION, NOT A RETRY, and the distinction is the one D-35
    drew. Re-rolling a stimulus AFTER a failure until one passes is forbidden --
    that is adjusting the instrument until it stops reporting a problem, and
    ``run_send_to_location`` still refuses to retry a bearing that planned and
    then failed to move. Choosing a fit SUBJECT BEFORE issuing any stimulus is
    the opposite move: it is what makes the stimulus mean something. PRD row 5
    names no robot.
    """
    rejections = []
    for rid in fleet:
        if rid in exclude:
            rejections.append((rid, GOTO_RESERVED_REASON))
            continue
        ok, reason = goto_subject_fitness(
            samples.get(rid),
            thresholds.get(rid, GOTO_DEFAULT_CRITICAL_THRESHOLD))
        if ok:
            return rid, rejections
        rejections.append((rid, reason))
    return None, rejections


def goto_no_subject_verdict(rejections):
    """Verdict when no robot was fit. -> ``(result, detail)``. Pure.

    THE DEFAULT IS FAIL, AND THAT IS THE WHOLE DISPOSITION. A gate that SKIPped
    here would be saying "this measurement could not be taken", which is a
    statement about the instrument and sends the reader to this file. A fleet in
    which no robot can accept an operator override is a statement about the
    SYSTEM, and the reader needs to be sent there. Both block a green run
    (exit 1 versus exit 2); only one of them points at the right place.

    THE ONE EXCEPTION IS A BLIND INSTRUMENT. If every robot examined was
    rejected for publishing no state at all, this probe could not see the fleet
    and must say so rather than blame it -- the D-34 rule, that an instrument
    which cannot see says so instead of rendering a verdict. Check 4 renders the
    verdict on absent state topics; it is not this check's row.
    """
    examined = [(rid, why) for rid, why in rejections
                if why != GOTO_RESERVED_REASON]
    detail = '; '.join('%s: %s' % (rid, why) for rid, why in rejections)
    if not examined:
        return SKIP, ('no second robot was available; check 7 uses one and '
                      'this check must not reuse it (%s)' % (detail or 'none',))
    if all(why == GOTO_NO_STATE_REASON for _rid, why in examined):
        return SKIP, ('no candidate robot published any state, so this gate '
                      'could not see the fleet well enough to choose a '
                      'subject -- an instrument failure, not a fleet one; '
                      'check 4 is the row that renders a verdict on absent '
                      'state topics. %s' % (detail,))
    return FAIL, ('NO ROBOT WAS IN A STATE TO ACCEPT THE OVERRIDE, so PRD '
                  'row 5 (send-to-location) was NOT demonstrated on this run. '
                  'This gate will not command a robot it can already see '
                  'cannot obey: that measures the autonomy rule which '
                  'countermands the operator, not the override, and it is '
                  'exactly what happened on 2026-08-01 (register D-42). Per '
                  'robot: %s' % (detail,))


def run_send_to_location(results, probe, robot_id, rcdl_dir, yaml_module,
                         rejections=()):
    """Check 11 — PRD row 5, which names send-to-location.

    EXPECTED WALL CLOCK: about 20 s when the first bearing plans successfully;
    GOTO_BUDGET_S (120 s) is the hard ceiling across all four bearings, the
    same worst case the previous 4 x (15 + 3 + 12) s structure declared.

    Check 8 tests ``force_recharge``; PRD row 5 does not. This is the row's own
    command, on a DIFFERENT robot, so the two overrides cannot mask each other.

    FIVE ASSERTIONS:
      1. the service returns success;
      2. ``fsm_state`` reaches NAVIGATING within GOTO_NAVIGATING_S;
      2b. the sample that proves (2) carries a ``current_task_id`` beginning
          ``override_goto_`` — the id ``operator_command.py:143`` sets for this
          command and nothing else sets. This is what separates "the agent took
          MY command" from "the agent happens to be navigating". Both (2) and
          (2b) are decided by ``evaluate_goto_acceptance``, which is pure so
          that the ROS-free lane can drive every branch of it;
      3. the robot closes GOTO_CLOSURE_M of range on the commanded target
         inside a window DERIVED from the bearing and the robot's own RCDL
         max_speed (``goto_window_seconds``), measured from a baseline sampled
         AFTER the override, not before it;
      4. the last pose of ``/<rid>/planned_path`` is the commanded target.

    WHERE THE POSE COMES FROM, corrected 2026-07-31. Assertions (2b), (3) and
    (4) are read off ``/<rid>/odom_world``. Under the shipped default
    ``pose_source: localisation`` (``selene_sim/launch/simulation.launch.py``)
    that topic carries the SIMULATOR'S TRUE WORLD POSE
    (``world_odometry_node.py:368-373``), not dead reckoning, and the node falls
    back to dead reckoning only with an ERROR log and a CRITICAL FleetAlert
    (:374-376). This check now READS that parameter off the robot's own
    ``/world_odom_<rid>`` node and prints what it found rather than asserting
    either way. The previous docstring and the gate's row-5 coverage column both
    asserted the displacement came off a pose that was not world-truth, which
    has been false since D-24/D-33 and is exactly the kind of caveat that gets
    copied forward forever. What (2b) and (3) still do NOT prove is that the
    DASHBOARD issued the command; (4) is what proves the target was honoured.

    (4) IS A TOLERANCE, NOT AN EQUALITY, AND THAT IS NOT A WEAKENING.
    ``AStarPlanner.plan`` returns ``grid.grid_to_world(gx, gy)`` for the goal
    cell (``navigator.py:237``) and ``grid_to_world`` returns the CELL CENTRE
    (``navigator.py:61-65``). At the shipped 1.0 m grid resolution
    (``selene_agent/config/nav_params.yaml:2``) the last path pose is therefore
    up to 0.707 m from any commanded target that is not itself a cell centre;
    asserting exact equality would fail on correct behaviour.

    RETRY POLICY, deliberately narrow: a bearing that fails to PLAN is retried
    on the next bearing, because an unplannable pick is the probe's fault. A
    bearing that plans and then fails to move is NOT retried. Re-rolling
    stimuli until one passes is exactly "adjust the instrument until it stops
    reporting a problem", which is the failure this register exists to name.

    THE SUBJECT IS A PRECONDITION OF THIS CHECK, NOT PART OF IT.
    ``select_goto_robot`` chooses a robot whose own state says it can obey an
    operator goto, and *rejections* carries every robot passed over with the
    reason. When nothing is fit this check FAILS LOUDLY rather than commanding a
    robot it can see cannot comply -- register D-42, where it did exactly that
    and reported the energy-critical rule as a send_to_location failure. PRD
    row 5 names no robot, so choosing a fit subject asserts nothing less;
    commanding an unfit one asserts something else entirely.
    """
    if robot_id is None:
        results.measured(11, rejections=[list(pair) for pair in rejections])
        verdict, detail = goto_no_subject_verdict(list(rejections))
        results.set(11, verdict, detail)
        return
    start = probe.latest_state(robot_id)
    if start is None:
        results.set(11, SKIP, '%s publishes no state' % (robot_id,))
        return
    if start.get('theta') is None:
        results.set(11, SKIP,
                    '%s state samples carry no heading, so a heading-relative '
                    'bearing cannot be chosen and a world-axis one is what '
                    'D-35 exists to stop' % (robot_id,))
        return

    max_speed, speed_source = read_rcdl_max_speed(
        rcdl_dir, start.get('robot_type', ''), yaml_module)

    # MEASURED, not asserted, and never a verdict: get_remote_parameters
    # returns {} on a timeout, and a parameter read must not be able to fail a
    # working override.
    pose_source = 'unknown'
    live = probe.get_remote_parameters('/world_odom_%s' % (robot_id,),
                                       ['pose_source'], timeout_sec=5.0)
    if live.get('pose_source'):
        pose_source = str(live['pose_source'])

    attempts = []
    started = time.time()
    for bearing in GOTO_BEARINGS_DEG:
        if time.time() - started > GOTO_BUDGET_S:
            attempts.append('%.0fs budget spent before bearing %+.0f deg'
                            % (GOTO_BUDGET_S, bearing))
            break

        origin = probe.latest_state(robot_id) or start
        if origin.get('theta') is None:
            origin = start
        target_x, target_y = goto_target(origin, bearing)
        probe.forget_path(robot_id)
        cut = time.time()
        response = probe.override(robot_id, 'send_to_location',
                                  target_x, target_y)
        if response is None:
            attempts.append('bearing %+.0f deg: no answer in 15s' % (bearing,))
            continue
        if not response.success:
            attempts.append('bearing %+.0f deg: rejected: %s'
                            % (bearing, response.message))
            continue
        answered = time.time()

        # (2) and (2b), from the recorded HISTORY rather than by re-reading a
        # level: NAVIGATING can be crossed quickly and D-34 is what happens to
        # a gate that samples for a level it might miss.
        # The verdict is STICKY across scans, as it was when this was inline:
        # ``states_since`` returns a growing history and the grace comparison
        # is against a fixed ``recv``, so a later scan can only re-find the
        # same foreign sample -- but keeping it means an abandoned scan can
        # never quietly discard a proof.
        baseline = None
        foreign_verdict = None
        foreign_detail = ''
        navigating_by = time.time() + GOTO_NAVIGATING_S
        while baseline is None and time.time() < navigating_by:
            baseline, seen_verdict, seen_detail = evaluate_goto_acceptance(
                robot_id, probe.states_since(robot_id, cut), answered)
            if seen_verdict is not None:
                foreign_verdict, foreign_detail = seen_verdict, seen_detail
            if baseline is None:
                time.sleep(0.1)

        if baseline is None and foreign_verdict is not None:
            results.set(11, foreign_verdict, foreign_detail)
            probe.override(robot_id, 'cancel_task')
            return
        if baseline is None:
            # _start_operator_navigation fires OPERATOR_CANCEL and returns to
            # IDLE when plan_to fails (agent_node.py), so this is the
            # observable signature of an unplannable target.
            attempts.append('bearing %+.0f deg: target (%.1f, %.1f) never '
                            'reached NAVIGATING under an override_goto task '
                            'id, likely unplannable'
                            % (bearing, target_x, target_y))
            continue

        # (3). The baseline is the first post-override NAVIGATING sample, so
        # the measurement starts from a robot the operator handler has already
        # stopped (``operator_command.py:126-127`` zeroes the drive before
        # :148 starts the new plan). The old code took its origin from a
        # cached pre-call sample off a 2 Hz topic — up to 0.5 s and ~0.25 m
        # stale on a moving robot, the same order as the 33 cm that separated
        # this check's FAIL from its PASS.
        window_s = goto_window_seconds(bearing, max_speed)
        verdict = None
        detail = ''
        measured = {}
        while verdict is None:
            elapsed = time.time() - baseline['recv']
            verdict, detail, measured = evaluate_goto_progress(
                probe.states_since(robot_id, baseline['recv']), baseline,
                (target_x, target_y), window_s, elapsed)
            if verdict is None:
                time.sleep(GOTO_POLL_INTERVAL_SEC)

        # (4).
        #
        # THE PATH MUST BE NEWER THAN THE OVERRIDE, and that test was missing.
        # `probe.paths[rid]` is `(recv_time, points)` and the recv_time was
        # recorded and never read -- so a path left over from the robot's
        # PREVIOUS task satisfied this assertion, and the check reported the
        # distance from the commanded target to the end of a route that had
        # nothing to do with the command.
        #
        # MEASURED 2026-08-01. The gate commanded scout_02 to (-81.5, -94.5) and
        # the agent refused to plan, correctly:
        #     Operator goto plan failed: goal (-81.5, -94.5) is on 26.1 deg
        #     ground, over the 20.0 deg traversable limit; a robot could not
        #     stop, work or set off again there
        #     NAVIGATING --(OPERATOR_CANCEL)--> IDLE
        # The system did exactly the right thing. Check 11 then measured the
        # stale path from the previous survey task, found it ended 32.35 m away,
        # and FAILed the override.
        #
        # THIS WAS PREDICTED. `goto_target`'s own docstring carried the note that
        # A* refuses a goal only for occupancy or bounds "because
        # navigation.max_traversable_slope_deg has no reader anywhere in
        # production (register D-28)" and that "if D-28 is fixed, a
        # heading-relative pick may start hitting slope refusals". D-28 was fixed
        # at 9c1a4d7 and the refusals started.
        #
        # An unplannable pick is THE PROBE'S FAULT, and the documented retry
        # policy already covers it: a bearing that fails to PLAN is retried on
        # the next bearing. What was missing was the detection -- the service
        # returns accepted BEFORE the plan is attempted, so acceptance is not
        # evidence that a route exists. A path that is not newer than `cut` now
        # means exactly that, and the check retries instead of blaming the
        # override.
        with probe.lock:
            recorded = probe.paths.get(robot_id)
        problems = []
        path_is_fresh = bool(recorded is not None and recorded[0] >= cut)
        if recorded is not None and not path_is_fresh:
            attempts.append(
                'bearing %+.0f deg: accepted, but no planned_path was published '
                'after the command (the newest is %.1fs older than it) -- the '
                'agent refused the goal, which for a slope refusal is correct '
                'behaviour and an unplannable pick by this probe'
                % (bearing, cut - recorded[0]))
            probe.override(robot_id, 'cancel_task')
            continue
        path_recorded = bool(path_is_fresh and recorded[1])
        if path_recorded:
            last_x, last_y = recorded[1][-1]
            offset = math.hypot(last_x - target_x, last_y - target_y)
            path_note = ('planned_path ends (%.2f, %.2f), %.2f m from the '
                         'commanded target' % (last_x, last_y, offset))
            if offset > NAV_GRID_RESOLUTION_M:
                problems.append('planned_path ends %.2f m from the commanded '
                                'target, more than one %.1f m nav grid cell'
                                % (offset, NAV_GRID_RESOLUTION_M))
        else:
            path_note = 'no planned_path was published after the override'
            problems.append(path_note)

        context = ('bearing %+.0f deg off heading %.3f rad, target (%.2f, '
                   '%.2f), window %.1fs derived at %.2f m/s from %s, '
                   'pose_source %s'
                   % (bearing, float(origin['theta']), target_x, target_y,
                      window_s, max_speed, speed_source, pose_source))
        if attempts:
            # Say which bearings were tried first and why they were abandoned.
            # A verdict measured on the third bearing is not the same evidence
            # as one measured on the first, and only the row can say so.
            context = '%s; earlier attempts: %s' % (context,
                                                    '; '.join(attempts))
        results.measured(11, robot=robot_id, bearing_deg=bearing,
                         target=[target_x, target_y],
                         heading_rad=round(float(origin['theta']), 4),
                         max_speed_mps=max_speed,
                         max_speed_source=speed_source,
                         pose_source=pose_source,
                         baseline_speed_mps=round(
                             float(baseline.get('speed', 0.0)), 3),
                         attempts=attempts, **measured)

        if verdict == FAIL:
            problems.append(detail)
        if problems:
            results.set(11, FAIL,
                        goto_detail(robot_id, problems + [context], path_note,
                                    path_recorded))
        elif verdict == SKIP:
            results.set(11, SKIP,
                        goto_detail(robot_id, [detail, context], path_note,
                                    path_recorded))
        else:
            results.set(11, PASS,
                        goto_detail(robot_id,
                                    ['accepted send_to_location, reached '
                                     'NAVIGATING under its own override_goto '
                                     'task id, ' + detail, context],
                                    path_note, path_recorded))
        # Leave the fleet as we found it. The pseudo-task has no orchestrator
        # queue entry, so only the agent needs telling.
        probe.override(robot_id, 'cancel_task')
        return

    results.set(11, FAIL, '%s: no bearing produced navigation (%s)'
                % (robot_id, '; '.join(attempts)))


def evaluate_rosbridge(results, ws, max_message_size, size_source):
    """Check 3 — rosbridge speaks the protocol, not merely "TCP 9090 is open".

    EXPECTED WALL CLOCK: none of its own; it reads frames the client has been
    collecting since the connection opened.

    The size assertion is a live regression guard for D-09: the sparse
    ResourceMap encoding was chosen specifically to stay under rosbridge's
    ``max_message_size``, above which roslibjs cannot reassemble the fragments
    rosbridge emits and drops them client-side in silence.
    """
    if ws is None or not ws.available:
        results.set(3, FAIL, 'no rosbridge websocket: %s'
                    % (ws.error if ws is not None else 'client not started'))
        return
    progress = ws.frames('/orchestrator/mission_progress')
    if not progress:
        results.set(3, FAIL,
                    'connected and subscribed, but no publish frame arrived on '
                    '/orchestrator/mission_progress, which publishes at 1 Hz')
        return
    map_bytes = ws.max_frame_bytes('/orchestrator/resource_map')
    results.measured(3, mission_progress_frames=len(progress),
                     resource_map_max_bytes=map_bytes,
                     max_message_size=max_message_size,
                     max_message_size_source=size_source)
    if map_bytes and max_message_size and map_bytes >= max_message_size:
        results.set(3, FAIL,
                    '/orchestrator/resource_map frame %d B >= rosbridge '
                    'max_message_size %d B (%s); roslibjs drops fragments '
                    'above this silently'
                    % (map_bytes, max_message_size, size_source))
    elif not map_bytes:
        results.set(3, PASS,
                    '%d mission_progress publish frames; no resource_map frame '
                    'arrived in the window (it publishes at 0.5 Hz), so the '
                    'D-09 size guard was not exercised' % (len(progress),))
    else:
        results.set(3, PASS,
                    '%d mission_progress publish frames; largest resource_map '
                    'frame %d B, under max_message_size %d B (%s)'
                    % (len(progress), map_bytes, max_message_size, size_source))


# ==========================================================================
# Supporting readers.
# ==========================================================================

def read_rviz_fixed_frame(path):
    """The ``Fixed Frame`` string from an .rviz config, or '' if unreadable."""
    if not path:
        return ''
    try:
        with open(path, 'r') as handle:
            for line in handle:
                match = re.match(r'^\s*Fixed Frame:\s*(\S+)\s*$', line)
                if match:
                    return match.group(1)
    except OSError as exc:
        log('rviz config %s: %s' % (path, exc))
    return ''


def read_ice_config(path, yaml_module):
    """The ground-truth deposit field from ice_deposits.yaml.

    Returns ``{'path', 'deposits', 'centres', 'strongest', 'max_range'}``, with
    ``deposits`` empty when the file could not be read. This used to return only
    the centres; the seed added for check 10 needs the sigmas and peaks as well,
    because "readings shaped like the real deposit field" means evaluating the
    field, not scattering a constant.

    ``strongest`` is the deposit with the largest ``peak_concentration``. It is
    the one the seed is laid over, and picking it by peak rather than by name
    means editing ice_deposits.yaml moves the seed instead of silently
    invalidating it.
    """
    empty = {'path': path, 'deposits': [], 'centres': [], 'strongest': None,
             'max_range': 0.0}
    if not path:
        return empty
    try:
        with open(path, 'r') as handle:
            config = yaml_module.safe_load(handle) or {}
    except (OSError, ValueError) as exc:
        log('ice config %s: %s' % (path, exc))
        return empty

    deposits = []
    centres = []
    for deposit in config.get('deposits') or []:
        centre = deposit.get('center')
        if not centre or len(centre) < 2:
            continue
        deposits.append({
            'id': str(deposit.get('id', '?')),
            'centre': (float(centre[0]), float(centre[1])),
            'sigma': float(deposit.get('sigma', 10.0)),
            'peak': float(deposit.get('peak_concentration', 5.0)),
            'radius': float(deposit.get('radius', 20.0)),
        })
        centres.append((float(centre[0]), float(centre[1])))
    if not deposits:
        return empty

    sensor = ((config.get('sensor_parameters') or {})
              .get('neutron_spectrometer') or {})
    return {
        'path': path,
        'deposits': deposits,
        'centres': centres,
        'strongest': max(deposits, key=lambda d: d['peak']),
        'max_range': float(sensor.get('max_detection_range', 10.0)),
    }


def deposit_field_concentration(x, y, ice):
    """Ground-truth ice concentration at (x, y), wt%.

    A VERBATIM PORT of ``NeutronSpectrometerNode._compute_concentration``
    (``selene_sim/selene_sim/neutron_spectrometer_node.py:72-92``), including
    its per-deposit range gate — a deposit contributes nothing beyond
    ``radius + max_detection_range``, which is a discontinuity in the field and
    not an approximation to smooth over. Ported rather than approximated so the
    seed check 10 fuses is the field a scout standing at the same point would
    have reported, minus the noise: a fixture that flakes is worse than none, so
    ``rng.gauss`` is deliberately NOT ported.
    """
    total = 0.0
    for deposit in ice['deposits']:
        cx, cy = deposit['centre']
        dist = math.hypot(x - cx, y - cy)
        if dist <= deposit['radius'] + ice['max_range']:
            total += deposit['peak'] * math.exp(
                -(dist ** 2) / (2 * deposit['sigma'] ** 2))
    return total


def find_node(probe, candidates):
    """First of *candidates* present in the graph, fully qualified, or None."""
    names = probe.node_names()
    for candidate in candidates:
        if candidate in names:
            return candidate
    return None


# ==========================================================================
# main
# ==========================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        description='Phase 5 exit-gate probe (see scripts/validate_phase5.sh).')
    parser.add_argument('--fleet', required=True,
                        help='comma-separated robot ids, e.g. '
                             'scout_01,scout_02,excavator_01,hauler_01')
    parser.add_argument('--dashboard-url', default='http://localhost:3000')
    parser.add_argument('--rosbridge-url', default='ws://localhost:9090')
    parser.add_argument('--window', type=float, default=32.0,
                        help='minimum continuous recording window, seconds')
    parser.add_argument('--settle', type=float, default=6.0,
                        help='DDS discovery settling time before stimulating')
    parser.add_argument('--idle-wait', type=float, default=60.0,
                        help='how long to wait for an idle prospect robot')
    parser.add_argument('--dashboard-timeout', type=float, default=150.0,
                        help='budget for check 2, which runs concurrently')
    parser.add_argument('--no-free-robot', action='store_true',
                        help='do not cancel a task to free a scout for the '
                             'injection; SKIP checks 6 and 9 instead. Check 5 '
                             'still runs -- the task is injected before a robot '
                             'is freed, so acceptance is measured either way')
    parser.add_argument('--no-seed-map', action='store_true',
                        help='do not publish synthetic readings to '
                             '/orchestrator/map_update before check 10. The '
                             'check then measures whatever the fleet has '
                             'surveyed, and SKIPs (never passes) below '
                             '%d observations -- which a gate-length run '
                             'cannot reach. Use it only on a long soak run'
                             % (MIN_MAP_OBSERVATIONS,))
    parser.add_argument('--inject-x', type=float, default=-50.0)
    parser.add_argument('--inject-y', type=float, default=-100.0)
    parser.add_argument('--ice-config', default='')
    parser.add_argument('--rviz-config', default='')
    parser.add_argument('--rcdl-dir', default='',
                        help='directory holding the RCDL descriptors '
                             '(<robot_type>.yaml). Check 11 reads max_speed '
                             'from it to derive its motion window; without it '
                             'the window uses the slowest shipped RCDL and the '
                             'row says which')
    parser.add_argument('--json-out', default='/tmp/selene_phase5_probe.json')
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    fleet = [rid.strip() for rid in args.fleet.split(',') if rid.strip()]
    results = Results()
    status = 0

    # Check 2 is HTTP-only and can take two minutes against the react-scripts
    # dev server, so it runs concurrently with everything below rather than
    # adding its compile time to the total.
    dashboard_thread = threading.Thread(
        target=check_dashboard_bundle,
        args=(results, args.dashboard_url, args.dashboard_timeout),
        name='dashboard-check', daemon=True)
    dashboard_thread.start()

    probe = None
    rclpy = None
    websocket = None
    try:
        import numpy
        import rclpy
        import yaml as yaml_module

        from nav_msgs.msg import Path
        from selene_msgs.msg import (ResourceMap, ResourceMapUpdate, RobotState,
                                     TaskAnnouncement, TaskAssignment)
        from selene_msgs.srv import InjectTask, OverrideRobot
        from visualization_msgs.msg import MarkerArray

        from selene_agent.fsm import AgentState
        from selene_orchestrator import resource_map_viz as rmviz
        # Pure numpy, no ROS. Used for ONE number — how many observations the
        # seed pattern must add — and never for the answer; see
        # seed_resource_map.
        from selene_orchestrator.resource_map import ResourceMap as ResourceMapGrid

        # New with D-03. An older build has neither the message nor the topic,
        # and their absence must be a SKIP with a reason rather than an import
        # crash that voids every other check in this file.
        try:
            from selene_msgs.msg import TaskQueueState
            task_queue_type = TaskQueueState
        except ImportError:
            task_queue_type = None

        rclpy.init(args=None)
        probe = ProbeNode(fleet, {
            'RobotState': RobotState,
            'TaskAnnouncement': TaskAnnouncement,
            'TaskAssignment': TaskAssignment,
            'ResourceMap': ResourceMap,
            'ResourceMapUpdate': ResourceMapUpdate,
            'MarkerArray': MarkerArray,
            'Path': Path,
            'InjectTask': InjectTask,
            'OverrideRobot': OverrideRobot,
        })
        probe.spin_in_background()
        window_start = time.time()
        log('rclpy node up; settling %.1fs for DDS discovery' % (args.settle,))
        time.sleep(args.settle)

        # ---- Live parameters, never hardcoded. ----
        # /orchestrator_node is what every entry point produces since D-12 was
        # fixed; /orchestrator is kept as a fallback so this probe still works
        # against an older workspace that has not been rebuilt.
        orchestrator = find_node(probe, ['/orchestrator_node', '/orchestrator'])
        params = {}
        if orchestrator:
            params = probe.get_remote_parameters(
                orchestrator,
                ['auction_timeout_sec', 'resource_map_max_marker_cells',
                 'resource_map_frame_id'])
        auction_timeout = params.get('auction_timeout_sec') or 5.0
        log('orchestrator node %r, parameters %r' % (orchestrator, params))

        # ---- rosbridge websocket. ----
        websocket = RosbridgeClient(args.rosbridge_url)
        if websocket.start(timeout_sec=20.0):
            websocket.subscribe('/orchestrator/mission_progress',
                                'selene_msgs/msg/MissionProgress')
            websocket.subscribe('/orchestrator/resource_map',
                                'selene_msgs/msg/ResourceMap')
            if task_queue_type is not None:
                websocket.subscribe(TASK_QUEUE_TOPIC,
                                    'selene_msgs/msg/TaskQueueState')
            for rid in fleet:
                websocket.subscribe('/%s/state' % (rid,),
                                    'selene_msgs/msg/RobotState')
        else:
            log('rosbridge websocket unavailable: %s' % (websocket.error,))

        rosbridge_node = find_node(probe, ['/rosbridge_websocket'])
        max_message_size = DEFAULT_ROSBRIDGE_MAX_MESSAGE_SIZE
        size_source = 'rosbridge_suite documented default'
        if rosbridge_node:
            live = probe.get_remote_parameters(rosbridge_node,
                                               ['max_message_size'])
            if isinstance(live.get('max_message_size'), int):
                max_message_size = live['max_message_size']
                size_source = '%s parameter' % (rosbridge_node,)

        # mission_progress is 1 Hz, so 6 s comfortably contains the 5 s the
        # check asks for, and the ROS half has nothing else to do meanwhile.
        time.sleep(6.0)
        evaluate_rosbridge(results, websocket, max_message_size, size_source)

        # ---- Check 10's stimulus, AFTER check 3 and before everything else.
        #
        # AFTER CHECK 3 on purpose. Seeding takes /orchestrator/resource_map
        # from an 88-byte empty snapshot to about 25 kB, and check 3's
        # `resource_map_max_bytes` is a live regression guard on D-09's sparse
        # encoding. Measuring it after the probe has stuffed the map would make
        # that number a statement about the stimulus rather than about the
        # system, and the generated footer quotes it as evidence.
        #
        # BEFORE THE STIMULUS TIMELINE because check 10 is evaluated from the
        # last matched map/marker pair in the recording, and everything below
        # keeps the window open for another 30-60 s — so seeding here leaves
        # many post-seed frames to choose from instead of exactly one.
        ice = read_ice_config(args.ice_config, yaml_module)
        if args.no_seed_map:
            seed = {'seeded': False, 'peak': None, 'deposit': None,
                    'readings': 0, 'expected_delta': 0, 'observed_delta': 0,
                    'baseline_observations': 0, 'settled_key': None,
                    'elapsed': 0.0}
            log('--no-seed-map: check 10 will measure the fleet\'s own survey')
        else:
            seed = seed_resource_map(results, probe, ice, ResourceMapGrid)

        # ---- Fleet discovery over the path the dashboard really uses. ----
        ws_topics = None
        if websocket.available:
            reply = websocket.call_service(
                '/rosapi/topics_for_type', 'rosapi_msgs/srv/TopicsForType',
                {'type': 'selene_msgs/msg/RobotState'}, timeout_sec=10.0)
            if reply is not None and reply.get('result', False):
                ws_topics = list((reply.get('values') or {}).get('topics', []))

        # ---- The stimulus timeline. ----
        #
        # THE INJECTION IS AN EMERGENCY ONE. ``run_injection`` sets
        # ``emergency=True`` on the InjectTask request over whichever transport
        # carries it, so checks 5 and 6 measure the emergency path — the path on
        # which the orchestrator may abort an auction already in flight — and
        # neither row says anything about a non-emergency priority-10
        # injection. Both rows state that in their own detail line.
        #
        # INJECT FIRST, FREE A ROBOT SECOND. The other order races the
        # orchestrator's own 0.5 s auction tick and loses about as often as it
        # wins. ``pick_prospect_robot`` returns the moment a robot reports IDLE;
        # ``_auction_tick`` (``create_timer(0.5, ...)``,
        # ``orchestrator_node.py:1191``) is watching the same 2 Hz RobotState
        # stream and can see that idle robot first. When it does, it opens an
        # auction for whatever ``get_next_ready()`` returns AT THAT INSTANT — a
        # priority-5.0 HTN survey task, because the priority-10.0 injected task
        # is not queued yet — then refuses to start another auction until that
        # one resolves (``:1561-1564``), and ``assign_to_robot`` consumes the
        # very robot the gate just freed. Check 6 would then report "never
        # assigned within 15s" on a completely healthy fleet, and with the
        # default 2 scouts there is no second chance inside the budget: the
        # other scout is busy and neither the excavator nor the hauler can bid
        # on a prospect task.
        #
        # THAT ARGUMENT USED TO END "and a priority-10 task cannot preempt an
        # auction in flight". IT NO LONGER DOES, and the ordering is kept
        # anyway, for two reasons that survive the semantics change. First,
        # preemption is permission, not a guarantee: the orchestrator falls
        # through into the ordinary start-auction path, which still returns
        # early when ``get_idle_robots()`` is empty, so a task queued after the
        # robot was freed can still lose the slot it was freed for. Second, and
        # this is new, check 6's corroboration clause compares the queue
        # snapshot taken BEFORE the injection with the snapshots after it; an
        # injection issued after the fleet was perturbed would leave the clause
        # nothing clean to compare against. Queueing the task first removes the
        # race rather than widening a timeout around it: ``get_next_ready``
        # returns ``max(ready, key=priority)`` (``task_queue.py:269``) and an
        # injected task is priority 10.0 (``orchestrator_node.py:468``) against
        # 5.0 for a survey.
        #
        # SIDE EFFECT, STATED: the task is now injected even on runs where no
        # robot can be freed, so one extra PENDING prospect task at (inject_x,
        # inject_y) may outlive the gate. It is a real survey task at priority
        # 10.0 and the fleet will run it like any other; the previous order left
        # the same task behind whenever the injection succeeded.
        task_id, inject_time, emergency = run_injection(
            results, probe, websocket, (args.inject_x, args.inject_y))
        chosen, note = pick_prospect_robot(
            probe, fleet, args.idle_wait,
            allow_freeing=not args.no_free_robot, task_id=task_id)
        if not task_id:
            results.set(6, SKIP, 'no task was injected to correlate against')
            results.set(9, SKIP, 'no injected task to follow into the queue')
        elif chosen is None:
            results.set(6, SKIP, note)
            results.set(9, SKIP, 'no robot ran the injected task: %s' % (note,))
        else:
            correlate_injection(results, probe, task_id, inject_time,
                                auction_timeout,
                                (args.inject_x, args.inject_y), note,
                                chosen=chosen, ws=websocket,
                                emergency=emergency,
                                queue_topic_available=(
                                    task_queue_type is not None))
            evaluate_queue_latency(results, probe, websocket, task_id,
                                   task_queue_type is not None)

        # ---- Two overrides, on two different robots. ----
        #
        # CHECK 7's SUBJECT IS STILL CHOSEN ON LIVENESS ALONE, and that is
        # correct: OPERATOR_RECHARGE is mapped from every state except
        # OFFLINE/ERROR, so any live robot can obey it and a fitness test there
        # would assert something its row does not.
        #
        # CHECK 11's SUBJECT IS NOW CHOSEN ON FITNESS. This block used to take
        # `eligible[1]` -- positionally, which at the default 2/1/1 fleet is
        # always scout_02. On 2026-08-01 that robot was reporting 0.0% battery
        # and was already in RETURNING under the energy-critical rule; the gate
        # commanded it anyway, the FSM accepted OPERATOR_GOTO and the rule
        # countermanded it six milliseconds later, and check 11 FAILed having
        # measured the rule rather than the override. BOTH FACTS WERE IN THIS
        # PROBE'S OWN RECORDING AT THE MOMENT IT CHOSE. See register D-42, and
        # `select_goto_robot` for why a precondition is not a retry.
        #
        # THE THRESHOLD IS THE AGENT'S OWN, READ LIVE. A literal here would be
        # the gate measuring its own assumptions -- D-12, and the same reason
        # `auction_timeout_sec` and `max_message_size` are read off their nodes
        # rather than spelled out here.
        critical_thresholds = {}
        for rid in fleet:
            live = probe.get_remote_parameters(
                '/agent_%s' % (rid,), ['energy_critical_threshold'],
                timeout_sec=5.0)
            value = live.get('energy_critical_threshold')
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                critical_thresholds[rid] = GOTO_DEFAULT_CRITICAL_THRESHOLD
                log('agent_%s did not answer for energy_critical_threshold; '
                    'using the declared default %.2f'
                    % (rid, GOTO_DEFAULT_CRITICAL_THRESHOLD))
            else:
                critical_thresholds[rid] = float(value)

        states = {rid: probe.latest_state(rid) for rid in fleet}
        eligible = [rid for rid in fleet
                    if states[rid] is not None
                    and states[rid]['fsm_state'] not in ('OFFLINE', 'ERROR')]
        recharge_robot = eligible[0] if eligible else None
        run_force_recharge(results, probe, recharge_robot)

        # RE-READ AFTER CHECK 7, NOT BEFORE IT. force_recharge moves its own
        # subject into RECHARGING and starts it driving, so a fitness decision
        # taken from a pre-check-7 snapshot would be reasoning about a fleet
        # this gate has since perturbed.
        states = {rid: probe.latest_state(rid) for rid in fleet}
        goto_robot, goto_rejections = select_goto_robot(
            fleet, states, critical_thresholds,
            exclude=(recharge_robot,) if recharge_robot else ())
        run_send_to_location(results, probe, goto_robot, args.rcdl_dir,
                             yaml_module, goto_rejections)

        # ---- Close the window, then evaluate the recording. ----
        remaining = args.window - (time.time() - window_start)
        if remaining > 0:
            log('holding the recording window open %.1fs longer' % (remaining,))
            time.sleep(remaining)

        evaluate_state_checks(results, probe, fleet, probe.snapshot_states(),
                              [state.value for state in AgentState], ws_topics)
        evaluate_map_parity(results, probe, params,
                            read_rviz_fixed_frame(args.rviz_config),
                            ice, seed, rmviz, numpy)
    except Exception as exc:
        status = 3
        log('PROBE ERROR: %r' % (exc,))
        import traceback
        traceback.print_exc(file=sys.stderr)
    finally:
        # Check 2 is independent of everything above and is joined even when the
        # ROS half failed: a broken workspace must not also hide a broken
        # dashboard.
        dashboard_thread.join(timeout=max(5.0, args.dashboard_timeout))
        if websocket is not None:
            websocket.stop()
        if probe is not None:
            probe.shutdown()
        if rclpy is not None:
            try:
                rclpy.shutdown()
            except Exception as exc:             # teardown only
                log('rclpy.shutdown: %s' % (exc,))
        try:
            with open(args.json_out, 'w') as handle:
                json.dump({'generated': time.time(), 'fleet': fleet,
                           'checks': results.as_dict()}, handle, indent=2)
        except OSError as exc:
            log('could not write %s: %s' % (args.json_out, exc))
        results.emit()
    return status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
