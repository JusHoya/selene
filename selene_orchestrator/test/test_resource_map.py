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


class TestNonFiniteReadingsAreRejected:
    """D-18 — one bad reading used to poison the grid for the process lifetime.

    ``update`` writes the posterior straight back into ``self._mean``, and the
    conjugate update multiplies the stored mean by the prior precision, so a
    single NaN reading makes every cell in its ~81-cell footprint NaN and no
    later reading can ever clear it. That NaN then reached both renderers:
    ``resource_map_viz`` raised ``ValueError`` out of ``math.floor`` inside the
    orchestrator's publish timer (so the RViz2 overlay stopped entirely) while
    ``colors.js`` drew the ramp floor (so the dashboard showed a plausible
    dark-blue patch). The colour halves are now made to agree, but agreeing
    about a corrupt cell is the second line of defence; this is the first.

    Mirrors the guard the agent already applies to sigma one hop upstream —
    ``selene_agent/selene_agent/agent_node.py:997-1005`` — which is why the
    sigma path was never reachable and the ``ice_concentration`` path was.
    """

    def _make_map(self):
        return ResourceMap(width=100, height=100, resolution=1.0,
                           origin_x=-50.0, origin_y=-50.0,
                           prior_mean=0.0, prior_variance=100.0,
                           footprint_radius=5.0, footprint_sigma=3.0)

    def _assert_pristine(self, rm):
        assert rm.get_total_readings() == 0
        grid = rm.get_mean_grid()
        var = rm.get_variance_grid()
        assert (grid == 0.0).all(), 'a rejected reading touched the mean grid'
        assert (var == 100.0).all(), 'a rejected reading touched the variance'

    def test_nan_reading_is_rejected_and_leaves_no_trace(self):
        rm = self._make_map()
        assert rm.update(0.0, 0.0, reading=float('nan'),
                         sensor_uncertainty=0.5) is False
        self._assert_pristine(rm)

    def test_infinite_reading_is_rejected(self):
        rm = self._make_map()
        for reading in (float('inf'), float('-inf')):
            assert rm.update(0.0, 0.0, reading=reading,
                             sensor_uncertainty=0.5) is False
        self._assert_pristine(rm)

    def test_non_finite_sigma_is_rejected(self):
        """ProspectSkill's "no usable sigma" sentinel is ``inf``."""
        rm = self._make_map()
        for sigma in (float('nan'), float('inf'), float('-inf')):
            assert rm.update(0.0, 0.0, reading=5.0,
                             sensor_uncertainty=sigma) is False
        self._assert_pristine(rm)

    def test_non_positive_sigma_is_rejected_not_floored(self):
        """``max(sigma**2, 1e-6)`` would turn sigma 0 into near-certainty.

        A sensor claiming zero noise collapses the posterior variance to ~1e-6,
        which both renderers draw at full ALPHA_MAX confidence — a fabricated
        confidence off an instrument that told us nothing.
        """
        rm = self._make_map()
        for sigma in (0.0, -0.5):
            assert rm.update(0.0, 0.0, reading=5.0,
                             sensor_uncertainty=sigma) is False
        self._assert_pristine(rm)

    def test_non_finite_position_is_rejected_rather_than_raising(self):
        """``world_to_grid`` does ``int((x - origin) / res)``; ``int(nan)``
        raises ValueError, straight out of the subscription callback."""
        rm = self._make_map()
        for x, y in ((float('nan'), 0.0), (0.0, float('nan')),
                     (float('inf'), 0.0), (0.0, float('-inf'))):
            assert rm.update(x, y, reading=5.0,
                             sensor_uncertainty=0.5) is False
        self._assert_pristine(rm)

    def test_a_good_reading_still_reports_that_it_was_applied(self):
        rm = self._make_map()
        assert rm.update(0.0, 0.0, reading=5.0,
                         sensor_uncertainty=0.5) is True
        assert rm.get_total_readings() > 0

    def test_an_out_of_bounds_reading_is_applied_not_rejected(self):
        """The return value means "usable", not "changed something".

        A reading outside the grid is a legitimate reading of somewhere this
        map does not cover — the loop simply finds no in-bounds cell. Reporting
        it as a rejection would make ``_on_map_update`` warn about a scout that
        merely drove off the edge of a 500 m map.
        """
        rm = self._make_map()
        assert rm.update(999.0, 999.0, reading=5.0,
                         sensor_uncertainty=0.5) is True
        assert rm.get_total_readings() == 0

    def test_one_bad_reading_cannot_poison_a_cell_for_later_good_ones(self):
        """The regression in one line: NaN in, then a real survey on top."""
        rm = self._make_map()
        rm.update(0.0, 0.0, reading=float('nan'), sensor_uncertainty=0.5)
        rm.update(0.0, 0.0, reading=5.0, sensor_uncertainty=0.5)
        mean = rm.get_mean(0.0, 0.0)
        assert mean == mean, 'the cell mean is NaN'          # NaN != NaN
        assert 0.0 < mean < 5.0
