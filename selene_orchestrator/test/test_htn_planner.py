"""Tests for the HTN task planner."""

import math

import pytest

from selene_orchestrator.task_queue import TaskQueue, TaskStatus
from selene_orchestrator.resource_map import ResourceMap
from selene_orchestrator.htn_planner import HTNPlanner, HOPPER_CAPACITY_KG


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
