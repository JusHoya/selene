"""Adaptive survey planner -- uncertainty-driven waypoint selection.

Replaces the static hexagonal grid with an information-theoretic approach
that directs scouts toward high-value areas (high uncertainty near known signals).

Scoring function per candidate cell:
    score = w_var * normalized_variance
          + w_sig * normalized_neighbor_signal
          - w_dist * normalized_distance

Candidates: grid cells within the PSR zone, filtered to min_spacing from
already-visited or queued waypoints.
"""

import math

import numpy as np

from selene_orchestrator.task_queue import REQUEUEABLE_STATUSES, TaskStatus


class AdaptiveSurveyPlanner:
    """Information-gain waypoint planner for ice prospecting surveys.

    Selects the next best waypoint by scoring candidate cells on three
    criteria: posterior variance (explore the unknown), neighbor signal
    strength (exploit near finds), and distance cost (prefer nearby).
    """

    def __init__(self, resource_map,
                 psr_center: tuple[float, float] = (-100.0, -150.0),
                 psr_radius: float = 60.0,
                 w_variance: float = 1.0,
                 w_signal: float = 0.5,
                 w_distance: float = 0.3,
                 min_spacing: float = 8.0,
                 candidate_resolution: float = 5.0,
                 signal_probe_radius: float | None = None):
        """
        Parameters:
            resource_map: ResourceMap instance to query for mean/variance.
            psr_center: Center of the PSR survey zone (x, y) in meters.
            psr_radius: Radius of the PSR survey zone in meters.
            w_variance: Weight for uncertainty term (explore unknown).
            w_signal: Weight for neighbor signal term (exploit near finds).
            w_distance: Weight for distance penalty (prefer nearby).
            min_spacing: Minimum distance between selected waypoints in meters.
            candidate_resolution: Spacing between candidate grid points in meters.
        """
        self._resource_map = resource_map
        self._psr_center = psr_center
        self._psr_radius = psr_radius
        self._w_variance = w_variance
        self._w_signal = w_signal
        self._w_distance = w_distance
        self._min_spacing = min_spacing
        self._candidate_resolution = candidate_resolution
        # Defaults to min_spacing. MUST NOT be below
        # (min_spacing - ResourceMap._footprint_radius) or the signal term is
        # identically zero -- see _get_neighbor_signal.
        self._signal_probe_radius = (
            float(signal_probe_radius) if signal_probe_radius is not None
            else float(min_spacing))

    def select_next_waypoint(self,
                             robot_position: tuple[float, float],
                             visited: set[tuple[float, float]] | None = None,
                             queued: set[tuple[float, float]] | None = None
                             ) -> tuple[float, float] | None:
        """Select the highest-scoring candidate cell for the given robot.

        Returns (x, y) world coordinates of the best unvisited cell, or None
        if all candidates are exhausted.
        """
        visited = visited or set()
        queued = queued or set()

        candidates = self._generate_candidates(visited, queued)
        if not candidates:
            return None

        robot_x, robot_y = robot_position

        # Pre-compute raw values for normalization
        variances = np.array([
            self._resource_map.get_variance(wx, wy)
            for wx, wy in candidates
        ])
        signals = np.array([
            self._get_neighbor_signal(wx, wy)
            for wx, wy in candidates
        ])
        distances = np.array([
            math.sqrt((wx - robot_x) ** 2 + (wy - robot_y) ** 2)
            for wx, wy in candidates
        ])

        # Normalize each component to [0, 1]
        max_var = variances.max()
        norm_var = variances / max_var if max_var > 0 else np.zeros_like(variances)

        max_sig = signals.max()
        norm_sig = signals / max_sig if max_sig > 0 else np.zeros_like(signals)

        max_dist = distances.max()
        norm_dist = distances / max_dist if max_dist > 0 else np.zeros_like(distances)

        # Score: high variance + high signal - distance cost
        scores = (self._w_variance * norm_var
                  + self._w_signal * norm_sig
                  - self._w_distance * norm_dist)

        best_idx = int(np.argmax(scores))
        return candidates[best_idx]

    def _generate_candidates(self, visited, queued) -> list[tuple[float, float]]:
        """Generate candidate waypoints within PSR zone, filtered by spacing."""
        cx, cy = self._psr_center
        r = self._psr_radius
        res = self._candidate_resolution

        # Occupied positions: union of visited and queued
        occupied = list(visited | queued)

        # Build grid covering the bounding box of the PSR circle
        x_min = cx - r
        x_max = cx + r
        y_min = cy - r
        y_max = cy + r

        num_x = int((x_max - x_min) / res) + 1
        num_y = int((y_max - y_min) / res) + 1

        candidates = []
        for ix in range(num_x):
            wx = x_min + ix * res
            for iy in range(num_y):
                wy = y_min + iy * res

                # PSR boundary check
                dist_to_center = math.sqrt((wx - cx) ** 2 + (wy - cy) ** 2)
                if dist_to_center > r:
                    continue

                # Grid bounds check
                gx, gy = self._resource_map.world_to_grid(wx, wy)
                if not self._resource_map.is_in_bounds(gx, gy):
                    continue

                # Min spacing from occupied waypoints
                too_close = False
                for ox, oy in occupied:
                    if math.sqrt((wx - ox) ** 2 + (wy - oy) ** 2) < self._min_spacing:
                        too_close = True
                        break
                if too_close:
                    continue

                candidates.append((wx, wy))

        return candidates

    def _score_candidate(self, wx: float, wy: float,
                         robot_x: float, robot_y: float) -> float:
        """Compute information-gain score for a candidate position.

        Components:
        1. Variance: higher variance = more to learn = higher score
        2. Neighbor signal: neighboring cells with high mean ice concentration
           indicate this cell is worth investigating (follow the gradient)
        3. Distance: closer to robot = cheaper to reach = bonus

        All components normalized to [0, 1] before weighting.

        Note: this standalone method normalizes against single-point reference
        values. For batch selection, select_next_waypoint() uses cross-candidate
        normalization which produces better results.
        """
        variance = self._resource_map.get_variance(wx, wy)
        signal = self._get_neighbor_signal(wx, wy)
        distance = math.sqrt((wx - robot_x) ** 2 + (wy - robot_y) ** 2)

        # Use PSR diameter as normalization reference for distance
        max_dist = 2 * self._psr_radius
        norm_dist = min(distance / max_dist, 1.0) if max_dist > 0 else 0.0

        # Variance normalized by prior (100.0 is typical prior_variance)
        norm_var = min(variance / 100.0, 1.0)

        # Signal normalized by a reasonable peak concentration
        norm_sig = min(signal / 10.0, 1.0)

        return (self._w_variance * norm_var
                + self._w_signal * norm_sig
                - self._w_distance * norm_dist)

    def _get_neighbor_signal(self, wx: float, wy: float) -> float:
        """Average posterior mean of 8 samples at ``signal_probe_radius``.

        MEASURED DEFECT THIS FIXES. This probed at the map RESOLUTION -- one
        cell, 1.0 m. But candidates are filtered to at least ``min_spacing``
        (8.0 m) from every visited or queued waypoint, and ResourceMap.update()
        only touches cells within ``footprint_radius`` (5.0 m) of a reading. An
        admissible candidate is therefore never closer than 8.0 m to a reading,
        and its 1.0 m neighbours never closer than 7.0 m -- always outside every
        footprint, always still at prior_mean 0.0.

        Instrumented over a full 10-waypoint survey of the PSR:
        ``max(signals) == 0.0`` on every one of the 10 selections, across all
        ~360-434 candidates each time. The variance term is identically
        ``prior_variance`` for exactly the same reason. With both terms
        constant the score collapsed to ``w_variance - w_distance * norm_dist``:
        pure nearest-neighbour. The planner could not see ice at all, so wiring
        it up without this fix would have produced a "working" adaptive planner
        that still ignored the deposits.

        The 8 pre-existing unit tests passed only because they construct the
        planner with min_spacing 3.0 or 5.0 -- at or below the footprint radius,
        where the old probe could reach observed cells.
        """
        res = self._signal_probe_radius
        offsets = [(-res, -res), (0, -res), (res, -res),
                   (-res, 0), (res, 0),
                   (-res, res), (0, res), (res, res)]

        total = 0.0
        count = 0
        for dx, dy in offsets:
            nx, ny = wx + dx, wy + dy
            gx, gy = self._resource_map.world_to_grid(nx, ny)
            if self._resource_map.is_in_bounds(gx, gy):
                total += self._resource_map.get_mean(nx, ny)
                count += 1

        return total / count if count > 0 else 0.0

    def get_survey_stats(self) -> dict:
        """Return stats: total_candidates, visited_count, mean_variance.

        Computes statistics over all candidate cells in the PSR zone
        (without any spacing filter applied).
        """
        cx, cy = self._psr_center
        r = self._psr_radius
        res = self._candidate_resolution

        x_min = cx - r
        x_max = cx + r
        y_min = cy - r
        y_max = cy + r

        num_x = int((x_max - x_min) / res) + 1
        num_y = int((y_max - y_min) / res) + 1

        total_candidates = 0
        visited_count = 0
        variance_sum = 0.0

        for ix in range(num_x):
            wx = x_min + ix * res
            for iy in range(num_y):
                wy = y_min + iy * res

                dist_to_center = math.sqrt((wx - cx) ** 2 + (wy - cy) ** 2)
                if dist_to_center > r:
                    continue

                gx, gy = self._resource_map.world_to_grid(wx, wy)
                if not self._resource_map.is_in_bounds(gx, gy):
                    continue

                total_candidates += 1
                var = self._resource_map.get_variance(wx, wy)
                variance_sum += var

                count = self._resource_map.get_count(wx, wy)
                if count > 0:
                    visited_count += 1

        mean_variance = variance_sum / total_candidates if total_candidates > 0 else 0.0

        return {
            "total_candidates": total_candidates,
            "visited_count": visited_count,
            "mean_variance": mean_variance,
        }


# ---------------------------------------------------------------------------
# Wiring helpers -- FR-MAP-3
#
# These are what the orchestrator's replan timer calls. They live here, ROS-free,
# because selene_orchestrator/test/conftest.py's _FakeNode returns
# SimpleNamespace(value=None) from every get_parameter, so an OrchestratorNode
# cannot be constructed in the no-ROS CI lane. Anything testable sits outside
# the node.
# ---------------------------------------------------------------------------

#: Statuses in which a task's target has ALREADY been broadcast and must never
#: be rewritten.
#:
#: AUCTIONING: _publish_announcement() has put target_x/target_y on the wire in
#:   a TaskAnnouncement and every agent has scored its bid against that point.
#:   Moving it now means the auction picks a winner by distance to A and sends
#:   them to B.
#: ASSIGNED / IN_PROGRESS: _publish_assignment() has sent a TaskAssignment and
#:   the agent copied the coordinates into its own state. Nothing re-reads the
#:   queue, so a rewrite changes only the orchestrator's bookkeeping and
#:   silently desynchronises it from where the robot is actually driving.
#: COMPLETED is excluded separately: it is a place a scout has BEEN. Evidence,
#: not a plan.
COMMITTED_STATUSES = (
    TaskStatus.AUCTIONING,
    TaskStatus.ASSIGNED,
    TaskStatus.IN_PROGRESS,
)


def zone_peak_mean(resource_map, center, radius) -> float:
    """Highest posterior mean inside the survey zone's bounding box, in wt%.

    The evidence gate for replanning. One numpy max over a bbox slice rather
    than ResourceMap.get_best_extraction_sites(), which is a 250,000-iteration
    Python loop and cannot run on a timer.
    """
    cx, cy = center
    gx0, gy0 = resource_map.world_to_grid(cx - radius, cy - radius)
    gx1, gy1 = resource_map.world_to_grid(cx + radius, cy + radius)
    grid = resource_map.get_mean_grid()
    sub = grid[max(0, gy0):gy1 + 1, max(0, gx0):gx1 + 1]
    return float(sub.max()) if sub.size else 0.0


def should_replan(completed_surveys: int,
                  total_readings: int,
                  last_replan_readings: int,
                  peak_mean: float,
                  seed_waypoints: int,
                  min_signal_wt: float) -> bool:
    """Whether the adaptive planner should re-target pending waypoints.

    Three conditions, each a measured failure mode:

    1. The deterministic lattice must land ``seed_waypoints`` readings first.
       MEASURED over 20 seeded runs against the real ice field: replanning after
       ONE reading puts 0.29 of second-half waypoints on >=4 wt% ground truth --
       WORSE than not adapting at all (0.60), because a single blob gives the
       planner one gradient and it walks off in a chain. After two: 0.66.
    2. There must be new evidence since the last replan, or the timer recomputes
       an identical answer forever.
    3. There must be something to converge ON. With no ice detected the signal
       term is zero and the score degenerates to nearest-neighbour, clustering
       the remaining budget beside the last scout -- strictly worse coverage
       than the lattice it would replace.
    """
    if completed_surveys < seed_waypoints:
        return False
    if total_readings <= last_replan_readings:
        return False
    return peak_mean >= min_signal_wt


def replan_pending_survey_targets(planner, task_queue, reference_position,
                                  task_type: str = 'prospect') -> list:
    """Re-target every PENDING survey task using *planner*. FR-MAP-3.

    Rewrites coordinates in place; never creates or deletes a task. That is the
    termination argument: the waypoint budget is fixed by
    HTNPlanner.decompose_collect_ice() at decomposition, this cannot raise it,
    and the HTN dependency graph (``select_site.depends_on`` lists exactly those
    task_ids) is untouched. Once every survey task has left PENDING there is
    nothing to rewrite and the call is a no-op forever after.

    Returns ``[(task_id, (old_x, old_y), (new_x, new_y)), ...]`` for the tasks
    that actually moved, so the caller can log the convergence.

    "PENDING" here means REQUEUEABLE_STATUSES -- PENDING *or* INTERRUPTED.
    Since D-03 made INTERRUPTED a resting status, a cancelled survey waypoint
    stays there until an auction picks it up again; leaving it out would make
    it invisible to this function in BOTH directions, so it would neither be
    re-targeted nor reserved, and the next pending waypoint could be placed on
    top of it inside min_spacing.
    """
    pending = []
    visited: set = set()
    queued: set = set()
    for task in task_queue.get_all_tasks():
        if task.task_type != task_type:
            continue
        if task.status in REQUEUEABLE_STATUSES and not task.assigned_robot:
            pending.append(task)
        elif task.status == TaskStatus.COMPLETED:
            visited.add((task.target_x, task.target_y))
        elif task.status in COMMITTED_STATUSES:
            queued.add((task.target_x, task.target_y))

    moves = []
    for task in pending:
        waypoint = planner.select_next_waypoint(
            reference_position, visited=visited, queued=queued)
        if waypoint is None:
            break          # candidates exhausted; leave the rest as they are
        old = (task.target_x, task.target_y)
        new = (float(waypoint[0]), float(waypoint[1]))
        task.target_x, task.target_y = new
        # Reserve it, or the next iteration's min_spacing filter would hand
        # every pending task the same argmax.
        queued.add(new)
        if old != new:
            moves.append((task.task_id, old, new))
    return moves
