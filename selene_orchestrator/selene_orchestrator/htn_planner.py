"""Hierarchical Task Network planner for ISRU mission decomposition.

Decomposes high-level objectives like CollectIce(zone, quantity) into
temporally-ordered primitive tasks that can be auctioned to the fleet.
Pure Python -- no ROS dependencies.
"""

from __future__ import annotations

import math
import uuid
from typing import TYPE_CHECKING

import numpy as np

from selene_orchestrator.task_queue import TaskQueue, TaskStatus

if TYPE_CHECKING:
    from selene_orchestrator.resource_map import ResourceMap


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HOPPER_CAPACITY_KG: float = 20.0
"""Maximum payload an excavator can carry per trip."""

SURVEY_WAYPOINT_COUNT: int = 10
"""Default number of survey waypoints generated for a PSR zone."""

SURVEY_SPACING: float = 20.0
"""Hex-grid spacing (meters) for survey waypoint generation."""


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

    def __init__(self, task_queue: TaskQueue, resource_map: ResourceMap):
        self._queue = task_queue
        self._resource_map = resource_map

        # Mission-level bookkeeping
        self._mission_id: str = ""
        self._target_kg: float = 0.0
        self._deposited_kg: float = 0.0
        self._depot: tuple[float, float] = (50.0, 50.0)
        self._select_site_id: str = ""
        self._cycles_generated: int = 0
        self._zone_center: tuple[float, float] = (0.0, 0.0)
        self._zone_radius: float = 0.0

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
        auctioned. It resolves when all survey deps complete. The planner
        picks the best site from ResourceMap and generates Excavate+Haul
        tasks.

        Multiple Excavate+Haul cycles are created when
        ``quantity > HOPPER_CAPACITY_KG``.
        """
        self._mission_id = _uid("mission")
        self._target_kg = quantity_kg
        self._deposited_kg = 0.0
        self._depot = depot
        self._zone_center = zone_center
        self._zone_radius = zone_radius
        self._cycles_generated = 0

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
        )

        # Excavate+Haul cycles will be generated when SelectSite resolves
        # (see check_and_advance).

        return self._mission_id

    def check_and_advance(self) -> None:
        """Called periodically (1 Hz). Advance virtual tasks and manage cycles.

        For SelectSite tasks: if all ``depends_on`` are COMPLETED, query
        ResourceMap for the best extraction site (highest mean, lowest
        variance) within the survey zone, then generate Excavate and Haul
        tasks with concrete coordinates.

        For mission tracking: check if total deposited >= target quantity.
        If not enough, generate additional Excavate+Haul cycles.
        """
        if not self._select_site_id:
            return

        site_task = self._queue.get_task(self._select_site_id)
        if site_task is None:
            return

        # --- Resolve SelectSite when all survey deps are done ---
        if site_task.status == TaskStatus.PENDING:
            all_done = all(
                self._queue.get_task(dep) is not None
                and self._queue.get_task(dep).status == TaskStatus.COMPLETED
                for dep in site_task.depends_on
            )
            if all_done:
                site_x, site_y = self._pick_best_site()
                site_task.progress_metadata["site_x"] = site_x
                site_task.progress_metadata["site_y"] = site_y
                self._queue.set_status(self._select_site_id, TaskStatus.COMPLETED)

                # Generate initial excavate+haul cycles
                self._generate_cycles(site_x, site_y)

        # --- Track haul completions to update deposited_kg ---
        self._update_deposited()

        # --- If deposited < target, generate more cycles if needed ---
        if not self._is_mission_complete():
            site_x = site_task.progress_metadata.get("site_x")
            site_y = site_task.progress_metadata.get("site_y")
            if site_x is not None and site_y is not None:
                remaining = self._target_kg - self._deposited_kg
                needed_cycles = math.ceil(remaining / HOPPER_CAPACITY_KG)
                if needed_cycles > self._cycles_generated:
                    self._generate_cycles(
                        site_x, site_y,
                        count=needed_cycles - self._cycles_generated,
                    )

    def get_mission_status(self) -> dict:
        """Return mission progress summary.

        Returns:
            dict with keys: target_kg, deposited_kg, active_cycles, complete.
        """
        active_cycles = self._count_active_cycles()
        return {
            "target_kg": self._target_kg,
            "deposited_kg": self._deposited_kg,
            "active_cycles": active_cycles,
            "complete": self._is_mission_complete(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pick_best_site(self) -> tuple[float, float]:
        """Select the best extraction site from the ResourceMap.

        Scores each surveyed cell as ``mean / (1 + variance)`` and returns
        the world coordinates of the highest-scoring cell within the zone.
        """
        mean_grid = self._resource_map.get_mean_grid()
        var_grid = self._resource_map.get_variance_grid()

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

    def _generate_cycles(
        self,
        site_x: float,
        site_y: float,
        count: int | None = None,
    ) -> None:
        """Generate Excavate -> Haul cycle pairs.

        Each cycle's excavate depends on the previous haul (sequential
        extraction). The first excavate depends on the SelectSite task.
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
            )
            self._queue.add_task(
                task_id=haul_id,
                task_type="haul",
                target_x=self._depot[0],
                target_y=self._depot[1],
                priority=3.0,
                required_capabilities=["haul"],
                parent_task_id=self._mission_id,
                depends_on=[exc_id],
            )

            prev_dep = haul_id
            self._cycles_generated += 1

    def _update_deposited(self) -> None:
        """Count completed haul tasks and compute total deposited kg."""
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

    def _is_mission_complete(self) -> bool:
        """Return True when deposited quantity meets or exceeds target."""
        return self._deposited_kg >= self._target_kg
