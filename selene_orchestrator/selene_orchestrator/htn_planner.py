"""Hierarchical Task Network planner for ISRU mission decomposition.

Decomposes high-level objectives like CollectIce(zone, quantity) into
temporally-ordered primitive tasks that can be auctioned to the fleet.
Pure Python -- no ROS dependencies.
"""

from __future__ import annotations

import math
import uuid
from typing import TYPE_CHECKING, Callable

import numpy as np

from selene_orchestrator.task_feed import (
    SITE_SELECTED,
    SITE_SELECTED_PARTIAL,
    TASK_MAX_ATTEMPTS,
)
from selene_orchestrator.task_queue import TaskQueue, TaskStatus

if TYPE_CHECKING:
    from selene_orchestrator.resource_map import ResourceMap


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HOPPER_CAPACITY_KG: float = 20.0
"""Nominal excavator payload per trip, kg -- a PLANNING HEURISTIC only.

It duplicates ``selene_hal/config/excavator.yaml``'s ``hopper_fill.capacity_kg:
20``, and that duplication is deliberate rather than an oversight: this module
is pure Python with no HAL and no RCDL parser, and it needs a cycle size at
decomposition time, before any robot has reported anything. It is used for
exactly one thing -- deciding how many excavate+haul pairs a quantity implies.

It is NO LONGER used to fabricate a delivered mass. ``_update_deposited`` takes
a ``deposited_source`` callable (the orchestrator passes
``MaterialInventory.get_total_deposited``), and only falls back to
``completed_hauls * HOPPER_CAPACITY_KG`` when no source was supplied --
see ``get_mission_status()['deposited_is_measured']``, which tells a consumer
which of the two it got.
"""

MAX_CYCLE_OVERPLAN_FACTOR: int = 4
"""Hard cap on how many cycles a mission may plan, as a multiple of nominal.

The ceiling is ``MAX_CYCLE_OVERPLAN_FACTOR * ceil(target / HOPPER_CAPACITY_KG)``
haul tasks. It exists because ``check_and_advance``'s top-up is a FEEDBACK LOOP
whose only feedback signal is the ledger: a haul that COMPLETES without its mass
ever reaching ``MaterialInventory`` looks exactly like a haul that delivered
nothing, and the loop would then append one cycle per completed haul forever.
That path is real rather than hypothetical -- a skill that cannot read its fill
sensor publishes NOTHING rather than a zero
(``selene_agent/selene_agent/skills/excavate.py``), and D-42 is a worked example
of a sensor channel becoming unreadable. Unbounded growth here is unbounded
growth of ``selene_msgs/msg/TaskQueueState``, republished in full at 2 Hz over
rosbridge.

WHY 4, AND NOT LARGER. It is a bound on per-cycle YIELD, not on mass: a factor
of ``k`` tolerates an average delivery down to ``1/k`` of ``HOPPER_CAPACITY_KG``.
The only shortfall ever measured is the 19.0 kg per delivery of the 2026-07-31
ten-robot run (register :947), i.e. 1.06x nominal -- so 4 has ~4x headroom over
the only evidence there is. 2 was rejected because it puts a 10 kg/cycle mission
EXACTLY at the bound, and a bound that binds in a plausible case is a silent
under-delivery. 4 bounds a nominal 100 kg mission's queue at
10 prospect + 1 select_site + 2*20 cycle tasks = 51 tasks.

WHAT IT DOES NOT GUARANTEE. It is not a delivery guarantee and not a safety
limit. When it binds the planner simply stops topping up and
``get_mission_status()['complete']`` stays False -- which surfaces as a stalled
MissionProgress bar and nothing louder. ``HTNPlanner`` is pure Python with no
logger by construction (module docstring), so it cannot say so itself.
"""

SURVEY_WAYPOINT_COUNT: int = 10
"""Default number of survey waypoints generated for a PSR zone."""

SURVEY_SPACING: float = 20.0
"""Hex-grid spacing (meters) for survey waypoint generation."""

SELECT_SITE_SURVEY_QUORUM: int = 1
"""How many surveys must actually COMPLETE before an extraction site is chosen.

The quorum on the ONE soft dependency edge in this mission, carried on the
select_site task as ``TaskEntry.depends_on_quorum``. It does NOT stand alone:
``TaskQueue.dependencies_met`` still requires every survey to be RESOLVED first,
so the mission never chooses a site while a scout is driving to a waypoint.

NOT ZERO, AND THAT IS THE WHOLE POINT OF THE NUMBER. ``_pick_best_site`` has an
explicit fallback for having no readings at all -- ``if not np.any(mean_grid >
0.0): return zone_center`` -- so a quorum of 0 would let this planner choose an
extraction site having surveyed NOTHING, generate every excavate and haul
against it, and report success. That is the exact shape of deviation D-29, where
an exit-gate check passed vacuously on a map with total_observations = 0. This
repository treats vacuous success as a defect, so at least one survey must
really have returned readings before the posterior is scored. With ten surveys
dead the mission still STOPS -- loudly, on ten CRITICAL exhaustion alerts --
and that is the design, not an oversight.

NOT TEN EITHER, which is what the queue enforced until D2 and is what made ONE
failed survey permanently kill the whole ISRU chain: survey -> select_site is
EVIDENTIAL, not causal. ``_pick_best_site`` scores the fused ResourceMap
posterior and never reads the survey task list, so a lost survey costs
CONFIDENCE, not correctness.

1 IS A FLOOR ON EVIDENCE, NOT A TARGET, and it is a weak one: one completed
survey is one waypoint's disc of observations, and the site will be the best cell
of that disc. This guarantees NOT-VACUOUS; it does not guarantee GOOD. The
nominal plan is still ten waypoints and the ordinary path still completes all
ten. WHAT IT COSTS WHEN IT BINDS is reported rather than inferred -- see the
'site_selected_partial' status_reason and the WARNING FleetAlert in
``orchestrator_node._htn_advance``.

IT IS NOT A ROS PARAMETER. ``test_no_orphan_parameters.py``'s allow-list is the
single name ``fleet_state_publish_rate`` and stays there; and a quorum over an
evidential edge is a property of the decomposition, like ``TASK_MAX_ATTEMPTS``
and ``navigator.MAX_REPLAN_ATTEMPTS``, not a per-deployment dial.
"""


# ---------------------------------------------------------------------------
# Rendezvous geometry (deviation D-22)
# ---------------------------------------------------------------------------
# This planner used to give a haul the SAME target coordinate as the excavate
# it depends on. An excavator now stays in the field after excavating (the
# D-19 recharge fix), so the plan was literally "two robots, one point": the
# hauler drove to the coordinate the excavator was parked on, the two bodies
# interpenetrated, and gz-sim's ODE collision space aborted the whole
# simulator (SIGABRT, exit 134) on the assertion
# `aabbBound >= dMinIntExact && aabbBound < dMaxIntExact`. MEASURED LIVE
# TWICE on 2026-07-31 on ROS 2 Jazzy / Gazebo Harmonic; the abort was the
# next Gazebo line after the hauler logged `phase=loading`. D-21 (the
# frozen-odometry detector in fleet_monitor) makes that abort VISIBLE; this
# removes one of its causes.
#
# WHAT IS NOT FIXED HERE, and it is the same defect shape:
#   * The next cycle's excavate is auctioned while the previous cycle's
#     excavator is still parked ON the site, so a SECOND excavator can be sent
#     onto it. Not offset, because extraction is sampled at the excavator's own
#     position (extraction_node.py:65-74) and moving the target would change
#     the mass produced. Partially self-limiting: the bid's distance term
#     (agent_node.py:721) favours the robot already standing there.
#   * Every haul unloads at ONE depot coordinate and goes idle there, and every
#     robot recharges at ONE station (agent_node.py:122-123). Convergence on
#     both is unguarded.
# A general guard -- the navigator treating fleet members as obstacles -- needs
# fleet poses in a common frame, and there is none: /tf has zero publishers and
# every pose is dead-reckoned per robot (register D-08). That is a subsystem,
# not this change.

FOOTPRINT_CLEARANCE_M: float = 1.17
"""Centre-to-centre distance at which an excavator and a hauler cannot overlap.

DERIVED FROM THE COLLISION GEOMETRY, not chosen. For each model, take the
circumscribed XY radius about the model origin -- for every collision link,
``|link origin| + (half-diagonal of a box | hypot(r, l/2) of a cylinder)``,
which is an upper bound under ANY link rotation, so no assumption about the
wheels' -pi/2 roll is baked in:

    excavator (``selene_sim/models/excavator/model.sdf``)
        base_link     box 0.8x0.6 at (0, 0)        -> 0.0000 + 0.5000 = 0.5000
        wheel x6      cyl r=.12 l=.06 at (.3, .35) -> 0.4610 + 0.1237 = 0.5847
        drill_arm     box .08x.08 at (0.40, 0)     -> 0.4000 + 0.0566 = 0.4566
        hopper        box .30x.30 at (-0.30, 0)    -> 0.3000 + 0.2121 = 0.5121
                                                              max R = 0.5847
    hauler (``selene_sim/models/hauler/model.sdf``)
        base_link     box 0.9x0.6                  -> 0.0000 + 0.5408 = 0.5408
        wheel x6      identical to the excavator's           = 0.5847
        transport_bin box .50x.40 at (-0.10, 0)    -> 0.1000 + 0.3202 = 0.4202
                                                              max R = 0.5847

0.5847 + 0.5847 = 1.1694, rounded UP to 10 mm. ``test_htn_planner.py``
re-derives both radii straight out of those two ``.sdf`` files, so editing a
model fails the build rather than silently invalidating this number.

It is a GEOMETRIC floor and nothing more: it says two bodies whose centres are
this far apart are not interpenetrating, not that two robots commanded this
far apart will end up that far apart. The control-side guarantee is
``HaulSkill.PICKUP_STANDOFF_M`` (``selene_agent/selene_agent/skills/haul.py``).
"""

HAUL_PICKUP_OFFSET_M: float = 1.2
"""How far the haul pickup sits from the excavation site, toward the depot.

``FOOTPRINT_CLEARANCE_M`` rounded up to 100 mm. **The plan-level invariant
only**: no plan this planner emits names one coordinate for two robots, which
is the defect as it was measured. It is deliberately NOT sized to survive
navigation error -- ``PathFollower`` declares arrival anywhere inside a 1.0 m
tolerance (``selene_agent/selene_agent/navigator.py:385,436``), which is
larger than this offset, so two robots sent to points 1.2 m apart can still
end up touching. That is what the skill-side standoff is for, and why this
number is kept small rather than inflated into a false guarantee.

DIRECTION: toward the depot. Any direction separates the coordinates; the
depot bearing is the one a hauler is on anyway (it arrives from the depot and
leaves for it), so the offset shortens the round trip instead of lengthening
it, and it keeps the pickup on the side of the site the hauler is least
likely to have to drive around.

**Kept small for a second reason.** The offset point is a navigation goal like
any other: ``AStarPlanner.plan`` refuses a goal on an OCCUPIED cell
(``navigator.py:207``), and the rocks in ``selene_agent/config/nav_params.yaml``
are inflated by 0.5 m. Moving the pickup 1.2 m can in principle put it inside
an inflation disc the site itself was clear of, which would fail the haul
loudly (``HaulSkill.start`` -> FAILED -> ``TaskResult(success=False)``). Not
observed; the exposure grows with the offset, which is a reason not to grow it.
"""


def _generate_survey_waypoints(
    center: tuple[float, float],
    radius: float,
    max_points: int = SURVEY_WAYPOINT_COUNT,
    spacing: float = SURVEY_SPACING,
    margin: float = 5.0,
) -> list[tuple[float, float]]:
    """Generate hexagonal survey waypoints inside a circular zone.

    Mirrors the logic of ``generate_psr_survey_waypoints`` but accepts an
    arbitrary center/radius and caps the output at *max_points* waypoints
    (closest to center first).
    """
    cx, cy = center
    effective_radius = radius - margin
    if effective_radius <= 0:
        return []

    waypoints: list[tuple[float, float]] = []
    row_spacing = spacing * math.sin(math.radians(60))
    rows = int(2 * effective_radius / row_spacing) + 1

    for row in range(rows):
        y_offset = -effective_radius + row * row_spacing
        x_shift = spacing / 2 if row % 2 == 1 else 0
        cols = int(2 * effective_radius / spacing) + 1

        for col in range(cols):
            x_offset = -effective_radius + col * spacing + x_shift
            wx = cx + x_offset
            wy = cy + y_offset
            dist = math.sqrt((wx - cx) ** 2 + (wy - cy) ** 2)
            if dist <= effective_radius:
                waypoints.append((wx, wy))

    waypoints.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    return waypoints[:max_points]


def _uid(prefix: str) -> str:
    """Return a short unique id with the given prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class HTNPlanner:
    """Hierarchical Task Network planner for ISRU mission decomposition.

    Decomposes high-level objectives like CollectIce(zone, quantity) into
    temporally-ordered primitive tasks that can be auctioned to the fleet.
    """

    def __init__(self, task_queue: TaskQueue, resource_map: ResourceMap,
                 deposited_source: Callable[[], float] | None = None):
        """
        Args:
            task_queue: the queue this planner writes tasks into.
            resource_map: fused posterior used to pick the extraction site.
            deposited_source: callable returning MEASURED deposited kg. When
                supplied it replaces the ``completed_hauls * HOPPER_CAPACITY_KG``
                estimate entirely. Optional, and defaulted to None, so the
                planner keeps working (and its existing tests keep passing)
                with no ledger behind it -- but the orchestrator always supplies
                one, so no fabricated mass reaches a published field.
        """
        self._queue = task_queue
        self._resource_map = resource_map
        self._deposited_source = deposited_source

        # Mission-level bookkeeping
        self._mission_id: str = ""
        self._target_kg: float = 0.0
        self._deposited_kg: float = 0.0
        self._depot: tuple[float, float] = (50.0, 50.0)
        self._select_site_id: str = ""
        # One-pass debounce on the cycle top-up. A shortfall must be observed
        # on two CONSECUTIVE check_and_advance passes before a cycle is added.
        # It exists for a measured race, not a hypothetical one: the agent
        # publishes the 'unloaded' MaterialEvent (agent_node.py:787) BEFORE the
        # TaskResult (:792), the two travel on different topics, and
        # _htn_advance runs on a ReentrantCallbackGroup under a 4-thread
        # executor -- so a pass can observe a haul already COMPLETED whose mass
        # has not yet reached MaterialInventory. Undebounced, that window
        # appends a spurious sixth cycle to an otherwise PERFECT 100 kg / 20 kg
        # mission. One second of latency against a ~174 s cycle time.
        self._shortfall_confirmed: bool = False
        self._zone_center: tuple[float, float] = (0.0, 0.0)
        self._zone_radius: float = 0.0
        # Allocated when SelectSite resolves. Every excavate and haul task the
        # planner then creates carries it, and it is how the orchestrator
        # resolves a MaterialEvent's task_id to a ledger site. A site is
        # DELIBERATELY not keyed by position, and that survives the 2026-07-31
        # frame fix: poses are world-referenced now
        # (selene_sim/selene_sim/world_odometry_node.py, register D-08), so two
        # robots at one place no longer report wildly different coordinates --
        # but the pose is still DEAD-RECKONED, so they agree only up to
        # accumulated wheel slip, and a position key would split one deposit
        # into several the moment that slip exceeded its tolerance.
        self._site_id: str = ""
        self._site_position: tuple[float, float] | None = None
        # (COMPLETED surveys, planned surveys) at the moment SelectSite
        # resolved. (0, 0) until then. The REPORT that goes with the site, not
        # an input to choosing it -- see ``check_and_advance``.
        self._site_evidence: tuple[int, int] = (0, 0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decompose_collect_ice(
        self,
        zone_center: tuple[float, float],
        zone_radius: float,
        quantity_kg: float,
        depot: tuple[float, float] = (50.0, 50.0),
    ) -> str:
        """Decompose a CollectIce objective into subtasks.

        Creates task chain:
            Survey(zone) -> SelectSite -> [Excavate -> Haul] x N

        Returns the root mission task_id.

        SelectSite is a 'virtual' task (task_type='select_site') -- not
        auctioned. It resolves when every survey dep is RESOLVED (COMPLETED, or
        FAILED with every attempt spent) and at least
        ``SELECT_SITE_SURVEY_QUORUM`` of them COMPLETED -- the ONE soft
        dependency edge in this mission, D2. The planner then picks the best
        site from ResourceMap and generates Excavate+Haul tasks.

        Multiple Excavate+Haul cycles are created when
        ``quantity > HOPPER_CAPACITY_KG``: ``ceil(quantity /
        HOPPER_CAPACITY_KG)`` of them. That INITIAL count assumes every cycle
        delivers a full hopper, which no measured cycle ever has (19.0 kg on
        the 2026-07-31 run). It is a first guess, not a plan: ``check_and_advance``
        tops the mission up against the LEDGER as deliveries land, so the
        nominal count is the step size of a feedback loop rather than a yield
        model. Nothing has been measured at decomposition time -- n=0 samples --
        which is why the nominal is used here and only here.
        """
        self._mission_id = _uid("mission")
        self._target_kg = quantity_kg
        self._deposited_kg = 0.0
        self._depot = depot
        self._zone_center = zone_center
        self._zone_radius = zone_radius
        self._shortfall_confirmed = False
        self._site_evidence = (0, 0)

        # --- 1. Survey waypoints ---
        waypoints = _generate_survey_waypoints(zone_center, zone_radius)
        survey_ids: list[str] = []
        for wx, wy in waypoints:
            sid = _uid("survey")
            self._queue.add_task(
                task_id=sid,
                task_type="prospect",
                target_x=wx,
                target_y=wy,
                priority=5.0,
                required_capabilities=["prospect"],
                parent_task_id=self._mission_id,
            )
            survey_ids.append(sid)

        # --- 2. SelectSite virtual task ---
        self._select_site_id = _uid("select_site")
        self._queue.add_task(
            task_id=self._select_site_id,
            task_type="select_site",
            target_x=zone_center[0],
            target_y=zone_center[1],
            priority=4.0,
            parent_task_id=self._mission_id,
            depends_on=survey_ids,
            # THE ONLY SOFT EDGE IN THIS MISSION. survey -> select_site is
            # EVIDENTIAL: losing a waypoint degrades the posterior, it does not
            # invalidate the decision, and enforcing it as if it were causal is
            # what made ONE failed survey kill the whole ISRU chain (D2). The
            # excavate/haul chain in ``_generate_cycles`` is CAUSAL and keeps
            # the default quorum of 0. It is 1 and NOT 0 because
            # ``_pick_best_site`` falls back to the zone centre with no readings
            # at all, so k=0 would choose a site having surveyed nothing -- the
            # shape of D-29. See ``SELECT_SITE_SURVEY_QUORUM``.
            depends_on_quorum=SELECT_SITE_SURVEY_QUORUM,
        )

        # Excavate+Haul cycles will be generated when SelectSite resolves
        # (see check_and_advance).

        return self._mission_id

    def check_and_advance(self) -> None:
        """Called periodically (1 Hz). Advance virtual tasks and manage cycles.

        For SelectSite tasks: if ``TaskQueue.dependencies_met`` says the survey
        evidence allows it (every dependency RESOLVED and at least
        ``SELECT_SITE_SURVEY_QUORUM`` COMPLETED), query ResourceMap for the best
        extraction site (highest mean, lowest variance) within the survey zone,
        then generate Excavate and Haul tasks with concrete coordinates. The
        ``status_reason`` records which of the two happened:
        ``SITE_SELECTED`` on full evidence, ``SITE_SELECTED_PARTIAL`` otherwise.

        For mission tracking: check if total deposited >= target quantity. If
        not, and the cycles still UNDELIVERED cannot cover the shortfall at
        ``HOPPER_CAPACITY_KG`` apiece, append ONE more Excavate+Haul cycle --
        subject to a one-pass debounce (``_shortfall_confirmed``) and to
        ``_cycle_ceiling()``.

        THREE THINGS ABOUT THAT RULE ARE DELIBERATE.

        * It compares against ``_count_undelivered_cycles()``, not against a
          cumulative count of every cycle ever created. The cumulative form is
          the D1 defect: the counter never decreases as work is delivered, so
          ``needed_cycles > cycles_ever_created`` is UNSATISFIABLE for every
          reachable state (``needed <= ceil(target/HOPPER) == created``
          whenever ``deposited >= 0``). Exactly five cycles were ever created,
          they delivered 94.85 kg against 100 kg, and no sixth could exist.
        * A FAILED haul counts as still undelivered, so it SUPPRESSES a
          replacement rather than provoking one. Appending a cycle here would
          chain its excavate onto the failed haul (``_generate_cycles`` sequences
          onto ``existing_hauls[-1]``), an excavate carries no dependency
          quorum, and ``TaskQueue`` therefore requires that haul to be COMPLETED
          for the replacement to become ready -- so it could never run. D2's
          soft quorum does not change this: it is on select_site alone, and the
          excavate/haul chain is deliberately still a HARD edge. Recovering a FAILED haul is a queue
          concern, not a planner one; this branch deliberately does not
          manufacture dead tasks to paper over it.
        * ONE cycle per pass, never a batch. The loop runs at 1 Hz and is
          idempotent, so a batch buys nothing, and a cap of one bounds the
          damage of any stale ledger read to a single cycle.
        """
        if not self._select_site_id:
            return

        site_task = self._queue.get_task(self._select_site_id)
        if site_task is None:
            return

        # --- Resolve SelectSite when the survey evidence allows it ---
        if site_task.status == TaskStatus.PENDING:
            # THE SAME PREDICATE THE AUCTION USES, not a second copy of it.
            # What stood here was ``all(dep is COMPLETED)``, written out again
            # -- so the queue and the planner each had their own idea of when a
            # dependency was satisfied, and D2's deadlock lived in THIS one:
            # select_site is virtual, ``_auction_tick`` skips it by task_type
            # and never announces it, so nothing but this line ever resolves it.
            # ``TaskQueue.dependencies_met`` is now the only expression of the
            # rule and this is its 1 Hz caller.
            if self._queue.dependencies_met(site_task, TASK_MAX_ATTEMPTS):
                # Counted for the REPORT, never for the decision -- the decision
                # is the line above. It is how much evidence the site was chosen
                # on, and ``orchestrator_node._htn_advance`` turns a shortfall
                # into a WARNING FleetAlert.
                completed = self._queue.completed_dependencies(site_task)
                total = len(site_task.depends_on)
                self._site_evidence = (completed, total)

                site_x, site_y = self._pick_best_site()
                site_task.progress_metadata["site_x"] = site_x
                site_task.progress_metadata["site_y"] = site_y
                self._site_id = _uid("site")
                self._site_position = (float(site_x), float(site_y))
                self._queue.set_status(
                    self._select_site_id, TaskStatus.COMPLETED,
                    SITE_SELECTED if completed >= total
                    else SITE_SELECTED_PARTIAL)

                # Generate initial excavate+haul cycles
                self._generate_cycles(site_x, site_y)

        # --- Track haul completions to update deposited_kg ---
        self._update_deposited()

        # --- If deposited < target, generate more cycles if needed ---
        shortfall = False
        if not self._is_mission_complete():
            site_x = site_task.progress_metadata.get("site_x")
            site_y = site_task.progress_metadata.get("site_y")
            if site_x is not None and site_y is not None:
                remaining = self._target_kg - self._deposited_kg
                needed_cycles = math.ceil(remaining / HOPPER_CAPACITY_KG)
                shortfall = needed_cycles > self._count_undelivered_cycles()
                if (shortfall and self._shortfall_confirmed
                        and self._count_cycles() < self._cycle_ceiling()):
                    self._generate_cycles(site_x, site_y, count=1)
                    shortfall = False
        self._shortfall_confirmed = shortfall

    def get_mission_status(self) -> dict:
        """Return mission progress summary.

        Returns:
            dict with keys: target_kg, deposited_kg, active_cycles, complete,
            deposited_is_measured.

        ``deposited_is_measured`` is False when ``deposited_kg`` is the
        completed-haul-count estimate rather than a ledger reading. A consumer
        that publishes the number as a mass must check it -- that is the whole
        reason it is on the dict rather than left implicit.
        """
        active_cycles = self._count_active_cycles()
        return {
            "target_kg": self._target_kg,
            "deposited_kg": self._deposited_kg,
            "active_cycles": active_cycles,
            "complete": self._is_mission_complete(),
            "deposited_is_measured": self._deposited_source is not None,
        }

    def get_site_id(self) -> str:
        """Ledger site id allocated when SelectSite resolved, or ""."""
        return self._site_id

    def get_site_evidence(self) -> tuple[int, int]:
        """(COMPLETED surveys, planned surveys) behind the selected site.

        ``(0, 0)`` before SelectSite resolves. When the two differ the site was
        chosen on PARTIAL evidence -- every survey RESOLVED, but some of them
        having exhausted every attempt and stayed FAILED -- so the fused
        posterior it was picked from is missing those waypoints' cells.

        A REPORT AND NOT A GATE. Nothing here re-selects the site or blocks the
        mission; the decision was ``TaskQueue.dependencies_met``'s and is
        already taken by the time this can be read. One production caller,
        ``orchestrator_node._htn_advance``, which raises the WARNING FleetAlert.
        """
        return self._site_evidence

    def get_site_position(self) -> tuple[float, float] | None:
        """World (x, y) of the selected extraction site, or None.

        FRAME: the same dead-reckoned odom-derived frame as everything else in
        this system (register D-08).
        """
        return self._site_position

    def get_depot(self) -> tuple[float, float]:
        """World (x, y) of the ISRU depot this mission delivers to."""
        return self._depot

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pick_best_site(self) -> tuple[float, float]:
        """Select the best extraction site from the ResourceMap.

        Scores each surveyed cell as ``mean / (1 + variance)`` and returns
        the world coordinates of the highest-scoring cell within the zone.
        Falls back to the zone center if no readings are available.
        """
        mean_grid = self._resource_map.get_mean_grid()
        var_grid = self._resource_map.get_variance_grid()

        # Safety: if no readings have been collected, fall back to zone center
        # so we don't pick the world origin (0,0) by default.
        if not np.any(mean_grid > 0.0):
            return (float(self._zone_center[0]), float(self._zone_center[1]))

        # Score: higher mean and lower variance is better
        score_grid = mean_grid / (1.0 + var_grid)

        best_score = -np.inf
        best_gx, best_gy = 0, 0

        cx, cy = self._zone_center
        r = self._zone_radius

        # Search cells within the zone bounding box
        gx_min, gy_min = self._resource_map.world_to_grid(cx - r, cy - r)
        gx_max, gy_max = self._resource_map.world_to_grid(cx + r, cy + r)

        for gy in range(max(0, gy_min), min(score_grid.shape[0], gy_max + 1)):
            for gx in range(max(0, gx_min), min(score_grid.shape[1], gx_max + 1)):
                wx, wy = self._resource_map.grid_to_world(gx, gy)
                dist = math.sqrt((wx - cx) ** 2 + (wy - cy) ** 2)
                if dist <= r and score_grid[gy, gx] > best_score:
                    best_score = score_grid[gy, gx]
                    best_gx, best_gy = gx, gy

        return self._resource_map.grid_to_world(best_gx, best_gy)

    def _haul_pickup(self, site_x: float, site_y: float) -> tuple[float, float]:
        """Where a hauler is sent to collect from the site at *(site_x, site_y)*.

        ``HAUL_PICKUP_OFFSET_M`` from the site along the unit vector toward the
        depot, so no excavate and its dependent haul ever carry the same
        coordinate. See the constant for the derivation and for what this does
        and does not guarantee.

        A depot AT the site is degenerate rather than impossible (a mission can
        be given ``depot=`` anywhere, and ``_pick_best_site`` falls back to the
        zone centre when no readings exist). There the bearing is undefined, so
        the offset goes along +x: an arbitrary direction is still a separation,
        and returning the site unchanged would put the defect back.
        """
        dx = self._depot[0] - site_x
        dy = self._depot[1] - site_y
        norm = math.hypot(dx, dy)
        if norm < 1e-9:
            ux, uy = 1.0, 0.0
        else:
            ux, uy = dx / norm, dy / norm
        return (float(site_x) + HAUL_PICKUP_OFFSET_M * ux,
                float(site_y) + HAUL_PICKUP_OFFSET_M * uy)

    def _generate_cycles(
        self,
        site_x: float,
        site_y: float,
        count: int | None = None,
    ) -> None:
        """Generate Excavate -> Haul cycle pairs.

        Each cycle's excavate depends on the previous haul (sequential
        extraction). The first excavate depends on the SelectSite task.

        THE HAUL'S TARGET IS THE SITE, not the depot. It used to be
        ``self._depot``, and combined with ``agent_node`` reading
        ``target_location`` as the PICKUP and using the robot's own recharge
        station as the drop-off, a haul drove to the depot, "loaded" a bin full
        of nothing, drove to its charger and dumped it there -- never visiting
        the extraction site. The depot now travels separately on
        ``TaskAssignment.depot_location``.

        THE HAUL'S TARGET IS NOT *EXACTLY* THE SITE, though: it is
        ``_haul_pickup()``, ``HAUL_PICKUP_OFFSET_M`` toward the depot. The
        excavate keeps the site itself, because extraction is evaluated at the
        excavator's own odom position -- ``hopper_node``/``extraction_node``
        sample the deposit field there
        (``selene_sim/selene_sim/extraction_node.py:65-74``) -- so moving an
        excavate off the peak would change the mass it produces. Loading is
        under no such constraint: ``bin_load_node`` subscribes to
        ``actuators/load_cmd`` and to nothing else, has no odometry
        subscription at all, and fills the bin on command wherever the hauler
        is standing. Offsetting the pickup is therefore free.
        """
        if count is None:
            count = math.ceil(self._target_kg / HOPPER_CAPACITY_KG)

        # Find the last haul task in the chain (for sequencing)
        prev_dep = self._select_site_id
        existing_hauls = [
            t for t in self._queue.get_all_tasks()
            if t.task_type == "haul" and t.parent_task_id == self._mission_id
        ]
        if existing_hauls:
            # Pick the last one generated (highest cycle index based on creation order)
            prev_dep = existing_hauls[-1].task_id

        pickup_x, pickup_y = self._haul_pickup(site_x, site_y)

        for _ in range(count):
            exc_id = _uid("excavate")
            haul_id = _uid("haul")

            self._queue.add_task(
                task_id=exc_id,
                task_type="excavate",
                target_x=site_x,
                target_y=site_y,
                priority=3.0,
                required_capabilities=["excavate"],
                parent_task_id=self._mission_id,
                depends_on=[prev_dep],
                site_id=self._site_id,
            )
            self._queue.add_task(
                task_id=haul_id,
                task_type="haul",
                target_x=pickup_x,
                target_y=pickup_y,
                priority=3.0,
                required_capabilities=["haul"],
                parent_task_id=self._mission_id,
                depends_on=[exc_id],
                # UNCHANGED, and it is what makes the offset above safe: the
                # ledger resolves a MaterialEvent to a site through
                # ``TaskEntry.site_id`` and never through a coordinate
                # (orchestrator_node.material_event_logic step 4,
                # orchestrator_node.py:747-761). Moving the haul's target_x/y
                # cannot move a kilogram between ledger buckets.
                site_id=self._site_id,
            )

            prev_dep = haul_id

    def _update_deposited(self) -> None:
        """Refresh deposited_kg from the ledger, or estimate it.

        With a ``deposited_source`` this is a MEASURED mass: the sum of every
        unload a hauler's load cell reported. Without one it falls back to
        ``completed_hauls * HOPPER_CAPACITY_KG``, which is an ASSUMPTION -- a
        task count multiplied by a nominal capacity, not a measurement -- and
        ``get_mission_status()['deposited_is_measured']`` is False so a caller
        cannot mistake the two.
        """
        if self._deposited_source is not None:
            self._deposited_kg = float(self._deposited_source())
            return
        completed_hauls = sum(
            1 for t in self._queue.get_all_tasks()
            if t.task_type == "haul"
            and t.parent_task_id == self._mission_id
            and t.status == TaskStatus.COMPLETED
        )
        self._deposited_kg = completed_hauls * HOPPER_CAPACITY_KG

    def _count_active_cycles(self) -> int:
        """Count excavate+haul cycles that are neither COMPLETED nor FAILED."""
        active = 0
        for t in self._queue.get_all_tasks():
            if (
                t.task_type == "excavate"
                and t.parent_task_id == self._mission_id
                and t.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED)
            ):
                active += 1
        return active

    def _count_undelivered_cycles(self) -> int:
        """Count this mission's cycles whose haul has NOT COMPLETED.

        A cycle is DELIVERED when its haul completes -- ``_update_deposited``
        already keys the mission's progress on exactly that -- so the haul is
        the task this counts, not the excavate.

        DELIBERATELY UNLIKE ``_count_active_cycles``, which filters excavates
        and excludes both COMPLETED and FAILED: here a FAILED haul is still
        UNDELIVERED, so it suppresses a replacement cycle. See
        ``check_and_advance``'s docstring for why manufacturing a replacement
        chained onto a failed haul would produce a task that can never run.

        Derived by scanning the queue rather than mirrored in a counter, for
        the reason ``_cycles_generated`` no longer exists: a mirror counter that
        only ever increments stops tracking the quantity its comparison needs
        the instant the first haul is delivered.
        """
        return sum(
            1 for t in self._queue.get_all_tasks()
            if t.task_type == "haul"
            and t.parent_task_id == self._mission_id
            and t.status != TaskStatus.COMPLETED
        )

    def _count_cycles(self) -> int:
        """Count every cycle this mission has ever planned, delivered or not."""
        return sum(
            1 for t in self._queue.get_all_tasks()
            if t.task_type == "haul" and t.parent_task_id == self._mission_id
        )

    def _cycle_ceiling(self) -> int:
        """Most cycles this mission may ever plan. See MAX_CYCLE_OVERPLAN_FACTOR."""
        return MAX_CYCLE_OVERPLAN_FACTOR * math.ceil(
            self._target_kg / HOPPER_CAPACITY_KG)

    def _is_mission_complete(self) -> bool:
        """Return True when deposited quantity meets or exceeds target."""
        return self._deposited_kg >= self._target_kg
