"""Tests for the HTN task planner."""

import ast
import math
import os
import xml.etree.ElementTree as ET

import pytest

from selene_orchestrator import htn_planner as htn_planner_module
from selene_orchestrator.task_queue import TaskQueue, TaskStatus
from selene_orchestrator.resource_map import ResourceMap
from selene_orchestrator.htn_planner import (
    FOOTPRINT_CLEARANCE_M,
    HAUL_PICKUP_OFFSET_M,
    HOPPER_CAPACITY_KG,
    MAX_CYCLE_OVERPLAN_FACTOR,
    HTNPlanner,
)


def _pose_xy(element):
    """XY of an SDF ``<pose>``, or (0, 0) when the element is absent.

    Every wheel link in these models declares ``relative_to="base_link"`` and
    every base_link sits at XY (0, 0) of its own model, so a relative pose and
    an absolute one are the same two numbers here.
    """
    if element is None:
        return 0.0, 0.0
    values = [float(token) for token in element.text.split()]
    return values[0], values[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def queue():
    return TaskQueue()


@pytest.fixture
def resource_map():
    """Small ResourceMap suitable for testing (100x100, origin at -50,-50)."""
    return ResourceMap(
        width=100, height=100, resolution=1.0,
        origin_x=-50.0, origin_y=-50.0,
        prior_mean=0.0, prior_variance=100.0,
    )


@pytest.fixture
def planner(queue, resource_map):
    return HTNPlanner(queue, resource_map)


# ---------------------------------------------------------------------------
# WP1 Tests
# ---------------------------------------------------------------------------

class TestDecompose:

    def test_decompose_produces_survey_tasks(self, planner, queue):
        """Survey subtasks should have type='prospect' and capability=['prospect']."""
        planner.decompose_collect_ice(
            zone_center=(0.0, 0.0), zone_radius=40.0, quantity_kg=20.0,
        )

        surveys = [t for t in queue.get_all_tasks() if t.task_type == "prospect"]
        assert len(surveys) > 0
        # Capped at ~10 waypoints
        assert len(surveys) <= 10

        for s in surveys:
            assert s.required_capabilities == ["prospect"]
            assert s.status == TaskStatus.PENDING

    def test_decompose_creates_select_site(self, planner, queue):
        """Virtual select_site task must depend on ALL survey task_ids."""
        planner.decompose_collect_ice(
            zone_center=(0.0, 0.0), zone_radius=40.0, quantity_kg=20.0,
        )

        survey_ids = {t.task_id for t in queue.get_all_tasks() if t.task_type == "prospect"}
        site_tasks = [t for t in queue.get_all_tasks() if t.task_type == "select_site"]
        assert len(site_tasks) == 1

        site = site_tasks[0]
        assert set(site.depends_on) == survey_ids
        assert site.status == TaskStatus.PENDING

    def test_temporal_ordering(self, planner, queue, resource_map):
        """Excavate depends on select_site; haul depends on excavate."""
        planner.decompose_collect_ice(
            zone_center=(0.0, 0.0), zone_radius=40.0, quantity_kg=20.0,
        )

        # Seed the resource map so the planner can pick a site
        resource_map.update(0.0, 0.0, 5.0, 1.0)

        # Complete all surveys to trigger SelectSite resolution
        for t in queue.get_all_tasks():
            if t.task_type == "prospect":
                queue.mark_complete(t.task_id)

        planner.check_and_advance()

        excavates = [t for t in queue.get_all_tasks() if t.task_type == "excavate"]
        hauls = [t for t in queue.get_all_tasks() if t.task_type == "haul"]

        assert len(excavates) >= 1
        assert len(hauls) >= 1

        # First excavate depends on select_site
        select_site_id = [
            t.task_id for t in queue.get_all_tasks() if t.task_type == "select_site"
        ][0]
        assert select_site_id in excavates[0].depends_on

        # Each haul depends on its corresponding excavate
        for haul in hauls:
            assert len(haul.depends_on) == 1
            dep_task = queue.get_task(haul.depends_on[0])
            assert dep_task is not None
            assert dep_task.task_type == "excavate"


class TestCheckAndAdvance:

    def test_check_and_advance_resolves_site(self, planner, queue, resource_map):
        """When all surveys complete, planner should pick best ResourceMap cell."""
        planner.decompose_collect_ice(
            zone_center=(0.0, 0.0), zone_radius=40.0, quantity_kg=20.0,
        )

        # Inject a high-value reading at (10, 10) with low uncertainty
        resource_map.update(10.0, 10.0, 8.0, 0.5)
        # Inject a lower-value reading elsewhere
        resource_map.update(-20.0, -20.0, 2.0, 0.5)

        # Complete all surveys
        for t in queue.get_all_tasks():
            if t.task_type == "prospect":
                queue.mark_complete(t.task_id)

        planner.check_and_advance()

        site_task = [t for t in queue.get_all_tasks() if t.task_type == "select_site"][0]
        assert site_task.status == TaskStatus.COMPLETED

        # Planner should have picked a site near (10, 10)
        site_x = site_task.progress_metadata["site_x"]
        site_y = site_task.progress_metadata["site_y"]
        dist_to_hotspot = math.sqrt((site_x - 10.0) ** 2 + (site_y - 10.0) ** 2)
        # Within sensor footprint radius (generous tolerance)
        assert dist_to_hotspot < 15.0

        # Excavate tasks should now exist
        excavates = [t for t in queue.get_all_tasks() if t.task_type == "excavate"]
        assert len(excavates) >= 1


class TestMultipleCycles:

    def test_multiple_haul_cycles(self, planner, queue, resource_map):
        """60 kg with 20 kg hopper = 3 excavate+haul pairs."""
        planner.decompose_collect_ice(
            zone_center=(0.0, 0.0), zone_radius=40.0, quantity_kg=60.0,
        )

        resource_map.update(0.0, 0.0, 5.0, 1.0)

        # Complete all surveys
        for t in queue.get_all_tasks():
            if t.task_type == "prospect":
                queue.mark_complete(t.task_id)

        planner.check_and_advance()

        excavates = [t for t in queue.get_all_tasks() if t.task_type == "excavate"]
        hauls = [t for t in queue.get_all_tasks() if t.task_type == "haul"]

        expected_cycles = math.ceil(60.0 / HOPPER_CAPACITY_KG)
        assert len(excavates) == expected_cycles
        assert len(hauls) == expected_cycles

        # Verify sequential chaining: each excavate (after the first) depends
        # on the previous haul
        for i in range(1, len(excavates)):
            dep_id = excavates[i].depends_on[0]
            dep_task = queue.get_task(dep_id)
            assert dep_task.task_type == "haul"


class TestMissionStatus:

    def test_mission_status_tracking(self, planner, queue, resource_map):
        """get_mission_status reflects progress as hauls complete."""
        planner.decompose_collect_ice(
            zone_center=(0.0, 0.0), zone_radius=40.0, quantity_kg=40.0,
        )

        resource_map.update(0.0, 0.0, 5.0, 1.0)

        # Complete surveys
        for t in queue.get_all_tasks():
            if t.task_type == "prospect":
                queue.mark_complete(t.task_id)

        planner.check_and_advance()

        status = planner.get_mission_status()
        assert status["target_kg"] == 40.0
        assert status["deposited_kg"] == 0.0
        assert status["complete"] is False

        # Complete first excavate+haul cycle
        excavates = [t for t in queue.get_all_tasks() if t.task_type == "excavate"]
        hauls = [t for t in queue.get_all_tasks() if t.task_type == "haul"]
        queue.mark_complete(excavates[0].task_id)
        queue.mark_complete(hauls[0].task_id)

        planner.check_and_advance()
        status = planner.get_mission_status()
        assert status["deposited_kg"] == HOPPER_CAPACITY_KG
        assert status["complete"] is False

        # Complete second cycle
        queue.mark_complete(excavates[1].task_id)
        queue.mark_complete(hauls[1].task_id)

        planner.check_and_advance()
        status = planner.get_mission_status()
        assert status["deposited_kg"] == 2 * HOPPER_CAPACITY_KG
        assert status["complete"] is True
        # And it says out loud that the number above is an ESTIMATE: a
        # completed-haul count times a nominal capacity, not a measured mass.
        assert status["deposited_is_measured"] is False


class TestMeasuredDeposit:
    """D-06: the planner must not fabricate a mass once a ledger exists."""

    def _resolve_site(self, planner, queue, resource_map):
        planner.decompose_collect_ice(
            zone_center=(0.0, 0.0), zone_radius=40.0, quantity_kg=40.0,
        )
        resource_map.update(0.0, 0.0, 5.0, 1.0)
        for t in queue.get_all_tasks():
            if t.task_type == "prospect":
                queue.mark_complete(t.task_id)
        planner.check_and_advance()

    def test_a_supplied_source_wins_over_the_completed_haul_estimate(
            self, queue, resource_map):
        measured = {"kg": 0.0}
        planner = HTNPlanner(queue, resource_map,
                             deposited_source=lambda: measured["kg"])
        self._resolve_site(planner, queue, resource_map)

        hauls = [t for t in queue.get_all_tasks() if t.task_type == "haul"]
        excavates = [t for t in queue.get_all_tasks()
                     if t.task_type == "excavate"]
        queue.mark_complete(excavates[0].task_id)
        queue.mark_complete(hauls[0].task_id)

        # One haul is complete, so the ESTIMATE would say HOPPER_CAPACITY_KG.
        # The ledger says 18.6 kg, and the ledger wins.
        measured["kg"] = 18.6
        planner.check_and_advance()
        status = planner.get_mission_status()
        assert status["deposited_kg"] == pytest.approx(18.6)
        assert status["deposited_kg"] != HOPPER_CAPACITY_KG
        assert status["deposited_is_measured"] is True

    def test_site_id_is_stamped_on_every_excavate_and_haul(
            self, queue, resource_map):
        planner = HTNPlanner(queue, resource_map)
        assert planner.get_site_id() == ""
        self._resolve_site(planner, queue, resource_map)

        site_id = planner.get_site_id()
        assert site_id.startswith("site_")
        cycle_tasks = [t for t in queue.get_all_tasks()
                       if t.task_type in ("excavate", "haul")]
        assert cycle_tasks
        assert all(t.site_id == site_id for t in cycle_tasks)
        # A survey task has no site: the orchestrator drops any MaterialEvent
        # whose task carries no site_id rather than inventing one.
        assert all(t.site_id == "" for t in queue.get_all_tasks()
                   if t.task_type == "prospect")

    def test_the_haul_target_is_the_site_not_the_depot(
            self, queue, resource_map):
        """Before this, a haul drove to the depot, loaded a bin full of
        nothing, drove to its charger and dumped it there -- never visiting the
        extraction site. The depot now travels on
        TaskAssignment.depot_location.

        AMENDED FOR D-22. This test used to assert that a haul's target was
        the site EXACTLY, and that it equalled its excavate's target. That is
        the defect D-22 was opened for -- one coordinate for two robots -- so
        the assertions now bound the haul to the site's NEIGHBOURHOOD instead:
        near enough that it is unmistakably the site and not the depot, offset
        by exactly HAUL_PICKUP_OFFSET_M. The separation itself is pinned in
        TestRendezvousSeparation below.
        """
        planner = HTNPlanner(queue, resource_map)
        planner.decompose_collect_ice(
            zone_center=(0.0, 0.0), zone_radius=40.0, quantity_kg=20.0,
            depot=(50.0, 50.0),
        )
        resource_map.update(10.0, 10.0, 8.0, 0.5)
        for t in queue.get_all_tasks():
            if t.task_type == "prospect":
                queue.mark_complete(t.task_id)
        planner.check_and_advance()

        site = planner.get_site_position()
        assert site is not None
        hauls = [t for t in queue.get_all_tasks() if t.task_type == "haul"]
        excavates = [t for t in queue.get_all_tasks()
                     if t.task_type == "excavate"]
        assert hauls
        for haul, excavate in zip(hauls, excavates):
            # The excavate still carries the site itself: extraction is
            # evaluated at the excavator's own position, so this coordinate is
            # a physical input and not just a destination.
            assert (excavate.target_x, excavate.target_y) == \
                pytest.approx(site)
            assert math.hypot(haul.target_x - site[0],
                              haul.target_y - site[1]) == \
                pytest.approx(HAUL_PICKUP_OFFSET_M)
            assert (haul.target_x, haul.target_y) != (50.0, 50.0)
        assert planner.get_depot() == (50.0, 50.0)


class TestCycleTopUp:
    """D1: the cycle top-up branch was UNREACHABLE, so an under-delivering
    mission could never finish.

    ``if needed_cycles > self._cycles_generated`` compared an OUTSTANDING count
    against a CUMULATIVE one. ``_cycles_generated`` was
    ``ceil(target / HOPPER_CAPACITY_KG)`` after the initial ``_generate_cycles``
    and never decreased, while ``needed_cycles`` is
    ``ceil((target - deposited) / HOPPER_CAPACITY_KG) <= ceil(target /
    HOPPER_CAPACITY_KG)`` for every ``deposited >= 0`` -- and ``deposited`` can
    only be non-negative. The strict ``>`` was therefore unsatisfiable in every
    reachable state.

    It only MATTERED because per-cycle yield is not the nominal 20.0 kg: the
    2026-07-31 ten-robot run measured 19.0 kg per delivery (register :947), so
    five cycles delivered 94.85 kg against a 100 kg objective and no sixth could
    ever exist. With a perfect 20.0 kg cycle the dead branch would never have
    been needed, which is why the defect survived to a live run.

    NOTHING HERE IS DEMONSTRATED ON A RUNNING SYSTEM. These are unit tests
    against the real ``HTNPlanner`` and the real ``TaskQueue``; no live mission
    has ever generated a sixth cycle.
    """

    TARGET_KG = 100.0
    """The configured objective. NOMINAL_CYCLES below is derived from it."""

    NOMINAL_CYCLES = 5
    """ceil(100.0 / 20.0). Asserted rather than assumed in the tests below."""

    @staticmethod
    def _resolve(planner, queue, resource_map, quantity_kg):
        """Run the mission up to (and including) SelectSite resolution."""
        planner.decompose_collect_ice(
            zone_center=(0.0, 0.0), zone_radius=40.0, quantity_kg=quantity_kg,
        )
        resource_map.update(0.0, 0.0, 5.0, 1.0)
        for t in queue.get_all_tasks():
            if t.task_type == "prospect":
                queue.mark_complete(t.task_id)
        planner.check_and_advance()

    @staticmethod
    def _hauls(queue):
        return [t for t in queue.get_all_tasks() if t.task_type == "haul"]

    @staticmethod
    def _excavates(queue):
        return [t for t in queue.get_all_tasks() if t.task_type == "excavate"]

    @classmethod
    def _next_undelivered_haul(cls, queue):
        for haul in cls._hauls(queue):
            if haul.status != TaskStatus.COMPLETED:
                return haul
        return None

    @classmethod
    def _deliver_one_cycle(cls, planner, queue, ledger, per_delivery):
        """Complete the next excavate+haul pair, credit the ledger, step twice.

        Two ``check_and_advance`` calls because the top-up debounce requires a
        shortfall to survive two CONSECUTIVE passes. At 1 Hz that is one second
        against a ~174 s cycle time.

        Returns False when there was no undelivered cycle left to complete.
        """
        haul = cls._next_undelivered_haul(queue)
        if haul is None:
            return False
        queue.mark_complete(haul.depends_on[0])
        queue.mark_complete(haul.task_id)
        ledger["kg"] += per_delivery
        planner.check_and_advance()
        planner.check_and_advance()
        return True

    # -- Mutation witnesses -------------------------------------------------

    def test_a_below_nominal_yield_generates_another_cycle(
            self, queue, resource_map):
        """THE HEADLINE. 18.97 kg per delivery against a 100 kg objective.

        Without the fix this ends at 5 cycles, 94.85 kg deposited and
        ``complete`` False forever -- the exact state reproduced against the
        unmodified classes.
        """
        ledger = {"kg": 0.0}
        planner = HTNPlanner(queue, resource_map,
                             deposited_source=lambda: ledger["kg"])
        self._resolve(planner, queue, resource_map, self.TARGET_KG)
        assert len(self._hauls(queue)) == self.NOMINAL_CYCLES

        for _ in range(50):  # bounded so a regression stalls loudly, not forever
            if planner.get_mission_status()["complete"]:
                break
            if not self._deliver_one_cycle(planner, queue, ledger, 18.97):
                break

        assert len(self._excavates(queue)) == 6
        assert len(self._hauls(queue)) == 6
        status = planner.get_mission_status()
        assert status["deposited_kg"] == pytest.approx(6 * 18.97)
        assert status["complete"] is True

    def test_undelivered_cycles_that_cannot_cover_the_gap_add_one(
            self, queue, resource_map):
        """Surgical: pins the comparison itself.

        Every one of the five nominal cycles is COMPLETED and the ledger reads
        the run's measured 94.85 kg, so ZERO cycles are undelivered against a
        5.15 kg shortfall that needs one. Without the fix, no new task appears.
        """
        ledger = {"kg": 0.0}
        planner = HTNPlanner(queue, resource_map,
                             deposited_source=lambda: ledger["kg"])
        self._resolve(planner, queue, resource_map, self.TARGET_KG)
        for task in self._excavates(queue) + self._hauls(queue):
            queue.mark_complete(task.task_id)
        ledger["kg"] = 94.85
        assert len(self._hauls(queue)) == self.NOMINAL_CYCLES

        planner.check_and_advance()   # observes the shortfall
        planner.check_and_advance()   # confirms it and acts

        assert len(self._excavates(queue)) == self.NOMINAL_CYCLES + 1
        assert len(self._hauls(queue)) == self.NOMINAL_CYCLES + 1

    def test_the_top_up_cycle_chains_onto_the_last_haul_and_carries_the_site(
            self, queue, resource_map):
        """A top-up cycle must be sequenced and attributed like any other.

        ``_generate_cycles`` chains onto ``existing_hauls[-1]``; this is the
        only caller that ever reaches that path with a non-empty list, so
        without a sixth cycle it is never exercised at all. The ``site_id``
        matters because the ledger resolves a MaterialEvent through it and
        never through a coordinate.
        """
        ledger = {"kg": 0.0}
        planner = HTNPlanner(queue, resource_map,
                             deposited_source=lambda: ledger["kg"])
        self._resolve(planner, queue, resource_map, self.TARGET_KG)
        for task in self._excavates(queue) + self._hauls(queue):
            queue.mark_complete(task.task_id)
        ledger["kg"] = 94.85
        before_hauls = self._hauls(queue)
        before_ids = {t.task_id for t in before_hauls + self._excavates(queue)}

        planner.check_and_advance()
        planner.check_and_advance()

        new_excavates = [t for t in self._excavates(queue)
                         if t.task_id not in before_ids]
        new_hauls = [t for t in self._hauls(queue)
                     if t.task_id not in before_ids]
        assert len(new_excavates) == 1 and len(new_hauls) == 1
        assert new_excavates[0].depends_on == [before_hauls[-1].task_id]
        assert new_hauls[0].depends_on == [new_excavates[0].task_id]
        site_id = planner.get_site_id()
        assert site_id.startswith("site_")
        assert new_excavates[0].site_id == site_id
        assert new_hauls[0].site_id == site_id

    def test_a_ledger_that_never_moves_is_bounded_by_the_cycle_ceiling(
            self, queue, resource_map):
        """MAX_CYCLE_OVERPLAN_FACTOR. The top-up is a feedback loop whose only
        feedback is the ledger, so a haul that COMPLETES without its mass ever
        reaching MaterialInventory is indistinguishable from one that delivered
        nothing -- and that path is real (a skill that cannot read its fill
        sensor publishes NOTHING rather than a zero). Unbounded, the planner
        appends a cycle per completed haul forever, into a TaskQueueState
        republished in full at 2 Hz.

        Mutation-checked by deleting the ceiling clause: the count then grows
        without bound.
        """
        planner = HTNPlanner(queue, resource_map, deposited_source=lambda: 0.0)
        self._resolve(planner, queue, resource_map, self.TARGET_KG)
        ceiling = MAX_CYCLE_OVERPLAN_FACTOR * self.NOMINAL_CYCLES

        for _ in range(200):
            for haul in self._hauls(queue):
                if haul.status != TaskStatus.COMPLETED:
                    queue.mark_complete(haul.task_id)
            planner.check_and_advance()
            assert len(self._hauls(queue)) <= ceiling

        assert len(self._hauls(queue)) == ceiling
        # When the ceiling binds the mission simply stops topping up. It is not
        # a delivery guarantee, and it says so no louder than a stalled bar.
        assert planner.get_mission_status()["complete"] is False

    def test_a_ledger_lag_does_not_manufacture_a_spurious_cycle(
            self, queue, resource_map):
        """The one-pass debounce, against the race it was written for.

        The agent publishes the 'unloaded' MaterialEvent (agent_node.py:787)
        BEFORE the TaskResult (:792); they travel on different topics and
        ``_htn_advance`` runs on a ReentrantCallbackGroup under a 4-thread
        executor, so a pass can see a haul COMPLETED whose mass has not yet
        landed. Here each cycle is stepped once with the ledger stale and once
        after it updates. A PERFECT 20.0 kg mission must still plan exactly
        five cycles.

        Mutation-checked by deleting ``and self._shortfall_confirmed``: this
        then fails with 6 cycles, i.e. a 19 kg over-delivery traded for D1's
        5 kg under-delivery.
        """
        ledger = {"kg": 0.0}
        planner = HTNPlanner(queue, resource_map,
                             deposited_source=lambda: ledger["kg"])
        self._resolve(planner, queue, resource_map, self.TARGET_KG)

        for _ in range(self.NOMINAL_CYCLES):
            haul = self._next_undelivered_haul(queue)
            assert haul is not None
            queue.mark_complete(haul.depends_on[0])
            queue.mark_complete(haul.task_id)
            planner.check_and_advance()   # COMPLETED seen, mass not yet in ledger
            ledger["kg"] += 20.0
            planner.check_and_advance()   # mass lands

        assert len(self._hauls(queue)) == self.NOMINAL_CYCLES
        status = planner.get_mission_status()
        assert status["deposited_kg"] == pytest.approx(100.0)
        assert status["complete"] is True

    # -- Guards (these PASS both with and without the fix) ------------------

    def test_a_perfect_nominal_mission_still_plans_exactly_five_cycles(
            self, queue, resource_map):
        """REGRESSION GUARD, NOT A MUTATION WITNESS -- it passes both ways, and
        that is the point: the fix must not change behaviour when every cycle
        delivers a full hopper."""
        ledger = {"kg": 0.0}
        planner = HTNPlanner(queue, resource_map,
                             deposited_source=lambda: ledger["kg"])
        self._resolve(planner, queue, resource_map, self.TARGET_KG)

        for _ in range(50):
            if planner.get_mission_status()["complete"]:
                break
            if not self._deliver_one_cycle(planner, queue, ledger, 20.0):
                break

        assert len(self._hauls(queue)) == self.NOMINAL_CYCLES
        status = planner.get_mission_status()
        assert status["deposited_kg"] == pytest.approx(100.0)
        assert status["complete"] is True

    @pytest.mark.parametrize("target_kg", [40.0, 50.0])
    def test_the_estimate_fallback_never_triggers_a_top_up(
            self, queue, resource_map, target_kg):
        """REGRESSION GUARD, NOT A MUTATION WITNESS -- passes both ways.

        With no ``deposited_source`` the deposited figure is
        ``completed_hauls * HOPPER_CAPACITY_KG``, which is self-consistent with
        the nominal cycle size by construction, so no shortfall can ever be
        observed. 50.0 is included because it is not a multiple of the hopper:
        the last cycle over-delivers on the estimate and must not be confused
        for a shortfall.
        """
        planner = HTNPlanner(queue, resource_map)
        self._resolve(planner, queue, resource_map, target_kg)
        nominal = math.ceil(target_kg / HOPPER_CAPACITY_KG)
        assert len(self._hauls(queue)) == nominal
        assert planner.get_mission_status()["deposited_is_measured"] is False

        ledger = {"kg": 0.0}  # unread: this planner has no source
        for _ in range(nominal):
            assert self._deliver_one_cycle(planner, queue, ledger, 0.0)

        assert len(self._hauls(queue)) == nominal
        assert planner.get_mission_status()["complete"] is True

    def test_a_fired_top_up_does_not_fire_again_on_an_unchanged_ledger(
            self, queue, resource_map):
        """Idempotence: the loop converges, it does not oscillate."""
        ledger = {"kg": 0.0}
        planner = HTNPlanner(queue, resource_map,
                             deposited_source=lambda: ledger["kg"])
        self._resolve(planner, queue, resource_map, self.TARGET_KG)
        for task in self._excavates(queue) + self._hauls(queue):
            queue.mark_complete(task.task_id)
        ledger["kg"] = 94.85
        planner.check_and_advance()
        planner.check_and_advance()
        after_top_up = len(self._hauls(queue))

        for _ in range(10):
            planner.check_and_advance()

        assert len(self._hauls(queue)) == after_top_up

    def test_the_cumulative_counter_is_gone_rather_than_merely_unused(
            self, planner):
        """No-orphan guard. Leaving ``_cycles_generated`` in place as a
        write-only mirror would be an eighth instance of the 'wired but never
        called' pattern CLAUDE.md tracks -- and it is the mirror itself that was
        the defect, so it is deleted rather than left incrementing.

        Checked over the AST rather than the source text, so the docstrings and
        comments that record WHY it is gone do not themselves trip the guard.
        """
        assert not hasattr(planner, "_cycles_generated")
        with open(htn_planner_module.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        referenced = {
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        } | {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        assert "_cycles_generated" not in referenced


class TestRendezvousSeparation:
    """D-22: no plan may name one coordinate for two robots.

    The planner used to give a haul the same target as the excavate it
    depends on. Since the D-19 recharge fix the excavator stays parked on that
    coordinate, so the hauler drove into it and gz-sim's ODE collision space
    aborted the whole simulator -- measured live twice on 2026-07-31.

    These are PLAN-level assertions. They do not claim two robots will end up
    this far apart: PathFollower declares arrival anywhere inside 1.0 m, which
    is wider than the offset. The control-side guarantee is
    HaulSkill.PICKUP_STANDOFF_M, pinned in
    selene_agent/test/test_haul_pickup_standoff.py.
    """

    @staticmethod
    def _resolve(planner, queue, resource_map, quantity_kg=60.0,
                 depot=(50.0, 50.0), hotspot=(10.0, 10.0)):
        planner.decompose_collect_ice(
            zone_center=(0.0, 0.0), zone_radius=40.0,
            quantity_kg=quantity_kg, depot=depot,
        )
        resource_map.update(hotspot[0], hotspot[1], 8.0, 0.5)
        for t in queue.get_all_tasks():
            if t.task_type == "prospect":
                queue.mark_complete(t.task_id)
        planner.check_and_advance()

    @staticmethod
    def _pairs(queue):
        """Every (excavate, haul) pair joined by the haul's depends_on."""
        hauls = [t for t in queue.get_all_tasks() if t.task_type == "haul"]
        assert hauls
        out = []
        for haul in hauls:
            assert len(haul.depends_on) == 1
            excavate = queue.get_task(haul.depends_on[0])
            assert excavate is not None and excavate.task_type == "excavate"
            out.append((excavate, haul))
        return out

    def test_no_haul_shares_a_coordinate_with_the_excavate_it_depends_on(
            self, queue, resource_map):
        planner = HTNPlanner(queue, resource_map)
        self._resolve(planner, queue, resource_map)
        pairs = self._pairs(queue)
        assert len(pairs) == 3
        for excavate, haul in pairs:
            assert (haul.target_x, haul.target_y) != \
                (excavate.target_x, excavate.target_y)

    def test_the_separation_clears_two_robot_footprints(
            self, queue, resource_map):
        """At least FOOTPRINT_CLEARANCE_M, the sum of the two circumscribed
        collision radii -- below it the two bodies are interpenetrating at some
        relative yaw whatever else is true."""
        planner = HTNPlanner(queue, resource_map)
        self._resolve(planner, queue, resource_map)
        for excavate, haul in self._pairs(queue):
            separation = math.hypot(haul.target_x - excavate.target_x,
                                    haul.target_y - excavate.target_y)
            assert separation >= FOOTPRINT_CLEARANCE_M

    def test_the_clearance_constant_is_the_shipped_collision_geometry(self):
        """Re-derive FOOTPRINT_CLEARANCE_M from selene_sim/models/*/model.sdf.

        Editing a robot model must fail this build rather than silently
        invalidating a separation derived from the old geometry. The bound used
        per link -- |link origin| + half-diagonal (box) or hypot(r, l/2)
        (cylinder) -- holds under ANY link rotation, so nothing here depends on
        the wheels' -pi/2 roll.
        """
        radii = {}
        for model in ("excavator", "hauler"):
            path = os.path.join(
                os.path.dirname(__file__), "..", "..",
                "selene_sim", "models", model, "model.sdf")
            root = ET.parse(path).getroot()
            best = 0.0
            for link in root.iter("link"):
                lx, ly = _pose_xy(link.find("pose"))
                for collision in link.findall("collision"):
                    cx, cy = _pose_xy(collision.find("pose"))
                    geometry = collision.find("geometry")
                    box = geometry.find("box")
                    cylinder = geometry.find("cylinder")
                    if box is not None:
                        sx, sy, _sz = [float(v)
                                       for v in box.find("size").text.split()]
                        half = math.hypot(sx / 2.0, sy / 2.0)
                    elif cylinder is not None:
                        half = math.hypot(
                            float(cylinder.find("radius").text),
                            float(cylinder.find("length").text) / 2.0)
                    else:  # pragma: no cover - no other shapes in these models
                        raise AssertionError(
                            f"{model}: unhandled collision shape; extend this "
                            f"derivation instead of deriving a separation from "
                            f"part of the model")
                    best = max(best,
                               math.hypot(lx + cx, ly + cy) + half)
            radii[model] = best

        derived = radii["excavator"] + radii["hauler"]
        assert radii["excavator"] == pytest.approx(0.5847, abs=5e-5)
        assert radii["hauler"] == pytest.approx(0.5847, abs=5e-5)
        assert FOOTPRINT_CLEARANCE_M >= derived
        assert FOOTPRINT_CLEARANCE_M - derived < 0.01, (
            "FOOTPRINT_CLEARANCE_M has drifted above the geometry; re-derive "
            "it rather than padding it")
        assert HAUL_PICKUP_OFFSET_M >= FOOTPRINT_CLEARANCE_M

    def test_the_pickup_is_offset_toward_the_depot(
            self, queue, resource_map):
        """Direction is not arbitrary: it is the bearing the hauler is on
        anyway, so the offset shortens the round trip rather than adding to
        it."""
        depot = (50.0, 50.0)
        planner = HTNPlanner(queue, resource_map)
        self._resolve(planner, queue, resource_map, depot=depot)
        site = planner.get_site_position()
        for _excavate, haul in self._pairs(queue):
            to_depot = math.hypot(depot[0] - site[0], depot[1] - site[1])
            from_pickup = math.hypot(depot[0] - haul.target_x,
                                     depot[1] - haul.target_y)
            assert from_pickup == pytest.approx(
                to_depot - HAUL_PICKUP_OFFSET_M)

    def test_a_depot_on_top_of_the_site_still_separates_the_two_tasks(
            self, queue, resource_map):
        """Degenerate, not impossible: the bearing is undefined when the depot
        IS the site, and returning the site unchanged would put the defect
        back."""
        planner = HTNPlanner(queue, resource_map)
        self._resolve(planner, queue, resource_map)
        site = planner.get_site_position()
        planner_at_site = HTNPlanner(TaskQueue(), resource_map)
        # _haul_pickup reads self._depot, so drive it explicitly rather than
        # relying on the constructor default happening to differ from the site.
        planner_at_site._depot = (site[0], site[1])
        pickup = planner_at_site._haul_pickup(site[0], site[1])
        assert pickup != (site[0], site[1])
        assert math.hypot(pickup[0] - site[0],
                          pickup[1] - site[1]) == \
            pytest.approx(HAUL_PICKUP_OFFSET_M)

    def test_the_offset_moves_no_kilogram_between_ledger_buckets(
            self, queue, resource_map):
        """The ledger keys on site_id, never on a coordinate.

        orchestrator_node.material_event_logic step 4 resolves a MaterialEvent
        through TaskEntry.site_id (orchestrator_node.py:747-761), and
        MaterialEvent carries no position field at all -- which is why the haul
        target could be moved without touching attribution. Pinned here because
        that is the assumption the whole change rests on.
        """
        planner = HTNPlanner(queue, resource_map)
        self._resolve(planner, queue, resource_map)
        site_id = planner.get_site_id()
        assert site_id.startswith("site_")
        for excavate, haul in self._pairs(queue):
            assert excavate.site_id == site_id
            assert haul.site_id == site_id
        # And the SITE the ledger registers is still the extraction point, not
        # the pickup: orchestrator_node._htn_advance feeds get_site_position()
        # straight to MaterialInventory.register_site.
        excavate = self._pairs(queue)[0][0]
        assert planner.get_site_position() == \
            pytest.approx((excavate.target_x, excavate.target_y))
