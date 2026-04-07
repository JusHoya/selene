"""Tests for ResourceMap Bayesian grid."""

from selene_orchestrator.resource_map import ResourceMap


class TestResourceMap:

    def _make_map(self, **kwargs):
        defaults = dict(width=100, height=100, resolution=1.0,
                        origin_x=-50.0, origin_y=-50.0,
                        prior_mean=0.0, prior_variance=100.0,
                        footprint_radius=5.0, footprint_sigma=3.0)
        defaults.update(kwargs)
        return ResourceMap(**defaults)

    def test_initial_state(self):
        rm = self._make_map()
        assert rm.get_mean(0.0, 0.0) == 0.0
        assert rm.get_variance(0.0, 0.0) == 100.0
        assert rm.get_count(0.0, 0.0) == 0

    def test_single_update_reduces_variance(self):
        rm = self._make_map()
        v_before = rm.get_variance(0.0, 0.0)
        rm.update(0.0, 0.0, reading=5.0, sensor_uncertainty=0.5)
        v_after = rm.get_variance(0.0, 0.0)
        assert v_after < v_before

    def test_single_update_shifts_mean(self):
        rm = self._make_map()
        rm.update(0.0, 0.0, reading=5.0, sensor_uncertainty=0.5)
        mean = rm.get_mean(0.0, 0.0)
        assert mean > 0.0  # shifted toward reading of 5.0
        assert mean < 5.0  # but not all the way (prior pulls toward 0)

    def test_multiple_updates_converge(self):
        rm = self._make_map()
        for _ in range(20):
            rm.update(0.0, 0.0, reading=8.0, sensor_uncertainty=0.5)
        mean = rm.get_mean(0.0, 0.0)
        assert abs(mean - 8.0) < 0.5  # should converge close to 8.0

    def test_footprint_neighbors_affected(self):
        rm = self._make_map(footprint_radius=3.0)
        rm.update(0.0, 0.0, reading=5.0, sensor_uncertainty=0.5)
        # Center cell should be updated
        assert rm.get_count(0.0, 0.0) > 0
        # Neighbor 2m away should also be updated
        assert rm.get_count(2.0, 0.0) > 0
        # Neighbor should have less shift than center (distance decay)
        assert rm.get_mean(2.0, 0.0) < rm.get_mean(0.0, 0.0)

    def test_far_cells_unaffected(self):
        rm = self._make_map(footprint_radius=3.0)
        rm.update(0.0, 0.0, reading=5.0, sensor_uncertainty=0.5)
        assert rm.get_count(10.0, 10.0) == 0
        assert rm.get_variance(10.0, 10.0) == 100.0

    def test_out_of_bounds_ignored(self):
        rm = self._make_map()
        # Should not crash
        rm.update(999.0, 999.0, reading=5.0, sensor_uncertainty=0.5)
        rm.update(-999.0, -999.0, reading=5.0, sensor_uncertainty=0.5)

    def test_coordinate_roundtrip(self):
        rm = self._make_map()
        gx, gy = rm.world_to_grid(10.5, -20.3)
        wx, wy = rm.grid_to_world(gx, gy)
        assert abs(wx - 10.5) < 1.0
        assert abs(wy - (-20.3)) < 1.0

    def test_total_readings(self):
        rm = self._make_map()
        rm.update(0.0, 0.0, reading=5.0, sensor_uncertainty=0.5)
        assert rm.get_total_readings() > 0

    def test_variance_decreases_with_more_observations(self):
        rm = self._make_map()
        rm.update(0.0, 0.0, reading=5.0, sensor_uncertainty=0.5)
        v1 = rm.get_variance(0.0, 0.0)
        rm.update(0.0, 0.0, reading=5.0, sensor_uncertainty=0.5)
        v2 = rm.get_variance(0.0, 0.0)
        assert v2 < v1

    def test_two_scouts_fuse_consistently(self):
        rm = self._make_map()
        rm.update(0.0, 0.0, reading=6.0, sensor_uncertainty=0.5)
        rm.update(0.0, 0.0, reading=4.0, sensor_uncertainty=0.5)
        mean = rm.get_mean(0.0, 0.0)
        # Average of 6 and 4 is 5, mean should be close
        assert abs(mean - 5.0) < 1.0
