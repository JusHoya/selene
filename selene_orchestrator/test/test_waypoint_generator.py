"""Tests for PSR waypoint generator."""

import math

import pytest

from selene_orchestrator.waypoint_generator import generate_psr_survey_waypoints


class TestWaypointGenerator:

    def test_generates_inside_psr(self):
        wps = generate_psr_survey_waypoints((-100, -150), 60.0, spacing=20.0)
        cx, cy = -100, -150
        for x, y in wps:
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            assert dist <= 60.0, f"({x},{y}) outside PSR circle"

    def test_approximate_count(self):
        wps = generate_psr_survey_waypoints((-100, -150), 60.0, spacing=20.0)
        assert 20 <= len(wps) <= 40

    def test_covers_center(self):
        wps = generate_psr_survey_waypoints((-100, -150), 60.0, spacing=20.0)
        cx, cy = -100, -150
        min_dist = min(math.sqrt((x - cx) ** 2 + (y - cy) ** 2) for x, y in wps)
        assert min_dist < 15.0

    def test_sorted_by_distance(self):
        wps = generate_psr_survey_waypoints((-100, -150), 60.0, spacing=20.0)
        cx, cy = -100, -150
        dists = [math.sqrt((x - cx) ** 2 + (y - cy) ** 2) for x, y in wps]
        for i in range(len(dists) - 1):
            assert dists[i] <= dists[i + 1] + 0.01

    def test_spacing_reasonable(self):
        wps = generate_psr_survey_waypoints((-100, -150), 60.0, spacing=20.0)
        for i in range(len(wps)):
            for j in range(i + 1, len(wps)):
                d = math.sqrt(
                    (wps[i][0] - wps[j][0]) ** 2
                    + (wps[i][1] - wps[j][1]) ** 2
                )
                assert d > 10.0, "waypoints too close together"

    def test_zero_radius(self):
        wps = generate_psr_survey_waypoints((-100, -150), 0.0, spacing=20.0)
        assert len(wps) == 0

    def test_custom_center(self):
        wps = generate_psr_survey_waypoints((0, 0), 30.0, spacing=10.0)
        for x, y in wps:
            assert math.sqrt(x ** 2 + y ** 2) <= 30.0

    def test_margin_reduces_area(self):
        wps_small_margin = generate_psr_survey_waypoints(
            (-100, -150), 60.0, spacing=20.0, margin=1.0,
        )
        wps_large_margin = generate_psr_survey_waypoints(
            (-100, -150), 60.0, spacing=20.0, margin=20.0,
        )
        assert len(wps_small_margin) >= len(wps_large_margin)

    def test_small_radius_with_large_margin(self):
        wps = generate_psr_survey_waypoints((-100, -150), 5.0, spacing=20.0, margin=10.0)
        assert len(wps) == 0
