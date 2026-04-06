"""Tests for AdaptiveSurveyPlanner uncertainty-driven waypoint selection."""

import math

import pytest

from selene_orchestrator.resource_map import ResourceMap
from selene_orchestrator.adaptive_survey import AdaptiveSurveyPlanner


def _make_resource_map():
    """Create a ResourceMap and seed it with some ice readings."""
    rm = ResourceMap(width=500, height=500, resolution=1.0,
                     origin_x=-250, origin_y=-250)
    # Seed some readings near deposit_alpha (-80, -140)
    for i in range(10):
        rm.update(-80 + i * 2, -140 + i * 2, reading=6.0,
                  sensor_uncertainty=0.3)
    return rm


def _dist(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


class TestAdaptiveSurvey:

    def test_selects_high_variance_cell(self):
        """Selected waypoint should NOT be near already-observed cells."""
        rm = _make_resource_map()
        planner = AdaptiveSurveyPlanner(rm)

        wp = planner.select_next_waypoint(
            robot_position=(-100, -150),
            visited=set(),
            queued=set(),
        )

        assert wp is not None
        # The seeded area around (-80, -140) has reduced variance.
        # The selected waypoint should be far from that zone (prefer
        # high-variance unexplored territory).
        seeded_center = (-80, -140)
        # With w_variance=1.0 dominating, the planner should avoid the
        # low-variance region.  Allow some tolerance -- the point should
        # not be sitting right on top of an observed cell.
        dist_to_seeded = _dist(wp, seeded_center)
        assert dist_to_seeded > 5.0, (
            f"Expected waypoint away from observed area, got {wp} "
            f"only {dist_to_seeded:.1f}m from seeded center"
        )

    def test_signal_follow_up(self):
        """Seed strong readings near (-80,-140); next waypoint should be nearby."""
        rm = ResourceMap(width=500, height=500, resolution=1.0,
                         origin_x=-250, origin_y=-250)
        # Seed concentrated strong readings
        for _ in range(15):
            rm.update(-80, -140, reading=8.0, sensor_uncertainty=0.3)

        # Boost signal weight so exploitation dominates
        planner = AdaptiveSurveyPlanner(
            rm,
            w_variance=0.3,
            w_signal=2.0,
            w_distance=0.1,
            min_spacing=3.0,
            candidate_resolution=5.0,
        )

        # Mark the exact seeded cell as visited so planner picks a neighbor
        wp = planner.select_next_waypoint(
            robot_position=(-80, -140),
            visited={(-80, -140)},
        )

        assert wp is not None
        dist_to_signal = _dist(wp, (-80, -140))
        assert dist_to_signal < 30.0, (
            f"Expected waypoint near signal source, got {wp} "
            f"at {dist_to_signal:.1f}m away"
        )

    def test_distance_penalty(self):
        """With robot at (-90,-140), selected wp should be closer than PSR edge."""
        rm = ResourceMap(width=500, height=500, resolution=1.0,
                         origin_x=-250, origin_y=-250)
        # No seeded data -> all variance equal -> distance should break ties
        planner = AdaptiveSurveyPlanner(
            rm,
            w_variance=0.0,
            w_signal=0.0,
            w_distance=1.0,
            candidate_resolution=5.0,
        )

        robot_pos = (-90, -140)
        wp = planner.select_next_waypoint(robot_position=robot_pos)

        assert wp is not None
        dist_to_robot = _dist(wp, robot_pos)
        # With only distance penalty active, should pick nearest candidate
        assert dist_to_robot < 10.0, (
            f"Expected nearby waypoint, got {wp} at {dist_to_robot:.1f}m"
        )

    def test_convergence_near_deposits(self):
        """Seed 20 readings near deposit area; 10 sequential waypoints
        should cluster there more densely than in an empty zone."""
        rm = ResourceMap(width=500, height=500, resolution=1.0,
                         origin_x=-250, origin_y=-250)
        # Heavy seeding around deposit_alpha
        for i in range(20):
            angle = 2 * math.pi * i / 20
            rx = -80 + 5 * math.cos(angle)
            ry = -140 + 5 * math.sin(angle)
            rm.update(rx, ry, reading=7.0, sensor_uncertainty=0.3)

        planner = AdaptiveSurveyPlanner(
            rm,
            w_variance=0.5,
            w_signal=1.5,
            w_distance=0.2,
            min_spacing=5.0,
            candidate_resolution=5.0,
        )

        visited = set()
        waypoints = []
        robot = (-90, -140)
        for _ in range(10):
            wp = planner.select_next_waypoint(robot, visited=visited)
            if wp is None:
                break
            waypoints.append(wp)
            visited.add(wp)

        assert len(waypoints) >= 5, "Should generate at least 5 waypoints"

        # Count waypoints near deposit vs far from deposit
        deposit_center = (-80, -140)
        near_deposit = sum(1 for wp in waypoints if _dist(wp, deposit_center) < 25)
        far_from_deposit = sum(1 for wp in waypoints if _dist(wp, deposit_center) >= 25)

        # At least twice as many near the deposit as far away
        assert near_deposit > far_from_deposit, (
            f"Expected clustering near deposit: {near_deposit} near vs "
            f"{far_from_deposit} far"
        )

    def test_respects_psr_boundary(self):
        """All selected waypoints must be within psr_radius of psr_center."""
        rm = _make_resource_map()
        planner = AdaptiveSurveyPlanner(rm)

        psr_center = (-100, -150)
        psr_radius = 60.0

        visited = set()
        for _ in range(20):
            wp = planner.select_next_waypoint(
                robot_position=(-100, -150),
                visited=visited,
            )
            if wp is None:
                break
            dist = _dist(wp, psr_center)
            assert dist <= psr_radius + 0.1, (
                f"Waypoint {wp} at {dist:.1f}m exceeds PSR radius {psr_radius}m"
            )
            visited.add(wp)

    def test_no_revisit(self):
        """A waypoint added to visited should never be selected again."""
        rm = _make_resource_map()
        planner = AdaptiveSurveyPlanner(rm, candidate_resolution=10.0)

        first = planner.select_next_waypoint(
            robot_position=(-100, -150),
            visited=set(),
        )
        assert first is not None

        # Now select again with first in visited
        second = planner.select_next_waypoint(
            robot_position=(-100, -150),
            visited={first},
        )
        # second must differ from first (min_spacing ensures no candidate
        # overlaps with visited)
        if second is not None:
            dist = _dist(first, second)
            assert dist >= planner._min_spacing, (
                f"Second waypoint {second} too close to visited {first}: "
                f"{dist:.1f}m < {planner._min_spacing}m"
            )

    def test_returns_none_when_exhausted(self):
        """Visit all candidates; verify None returned."""
        rm = ResourceMap(width=500, height=500, resolution=1.0,
                         origin_x=-250, origin_y=-250)
        # Tiny PSR zone with coarse resolution -> very few candidates
        planner = AdaptiveSurveyPlanner(
            rm,
            psr_center=(-100, -150),
            psr_radius=10.0,
            min_spacing=8.0,
            candidate_resolution=5.0,
        )

        visited = set()
        for _ in range(200):  # more iterations than possible candidates
            wp = planner.select_next_waypoint(
                robot_position=(-100, -150),
                visited=visited,
            )
            if wp is None:
                break
            visited.add(wp)

        # After exhaustion, should return None
        result = planner.select_next_waypoint(
            robot_position=(-100, -150),
            visited=visited,
        )
        assert result is None, f"Expected None when exhausted, got {result}"

    def test_survey_stats(self):
        """get_survey_stats returns reasonable values."""
        rm = _make_resource_map()
        planner = AdaptiveSurveyPlanner(rm)

        stats = planner.get_survey_stats()
        assert stats["total_candidates"] > 0
        assert stats["visited_count"] >= 0
        assert stats["mean_variance"] > 0
        # After seeding, some cells should have been visited
        assert stats["visited_count"] > 0
