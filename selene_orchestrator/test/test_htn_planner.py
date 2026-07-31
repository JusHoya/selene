"""Tests for the HTN task planner."""

import math
import os
import xml.etree.ElementTree as ET

import pytest

from selene_orchestrator.task_queue import TaskQueue, TaskStatus
from selene_orchestrator.resource_map import ResourceMap
from selene_orchestrator.htn_planner import (
    FOOTPRINT_CLEARANCE_M,
    HAUL_PICKUP_OFFSET_M,
    HOPPER_CAPACITY_KG,
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
