"""The fleet distance accumulator — deviation D-31.

WHAT WAS WRONG. A 30-minute ten-robot run on 2026-07-31 reported
``fleet_distance_total`` = 1665.37 m against a ground-truth path integral of
about 753 m: 2.21x, an excess of 913.07 m. The accumulator was integrating a
pose the agent FABRICATED. ``GazeboOdometrySensor.read()`` never raises; before
the first ``/odom_world`` message it returns a cached ``OdometryReading`` whose
defaults are ``is_valid=False, x=0.0, y=0.0``, and ``AgentNode._publish_state``
copied that straight into ``RobotState.pose`` with no validity test. The message
had no way to say "this is not a measurement", so ``FleetMonitor.update_robot``
seeded ``_last_pose`` from the fabricated origin and booked ``|spawn|`` --
90.050 m to 127.224 m per robot -- the first time a real pose arrived.

THE ARITHMETIC, REPRODUCED TWICE against the real module (once by the diagnosis
and once independently by its reviewer, both landing on the same digits): two
(0, 0) samples then the true spawn pose books **1096.580 m** over the shipped
ten-robot fleet, and **102.416 m** for a single scout at (-45, -92). Every one
of those increments is under the 500 m implausible-jump guard, so nothing
rejected any of them and nothing counted them either.

WHAT IS PROVEN AND WHAT IS NOT — and the distinction matters, because 1096.580
OVER-explains the 913.07 m excess rather than matching it.

* PROVEN: the mechanism. It is reproduced here, in this file, by mutation.
* NOT PROVEN: that it accounts for the whole excess. The launch timing
  guarantees only that robots 7-10 fabricated -- agents all start at t = 12 s
  (``selene_sim/launch/unified_sim.launch.py``) while spawns are staggered 2 s
  apart (``selene_sim/launch/simulation.launch.py``), so those four spend 2-8 s
  publishing before their model exists. Their spawns sum to 470.717 m, 51.6% of
  the excess. Whether the other six also fabricated was never measured. If they
  did not, roughly 442 m remains unattributed.
* NOT ELIMINATED: a second mechanism of the same shape. ``world_odometry_node``
  re-evaluates ``truth_fresh`` on every odom message against a 1.0 s timeout, so
  one second of silence on ``/pose_truth`` flips the published pose to dead
  reckoning and back -- two jumps of |DR - truth| per episode, which the register
  measures at 166.2 m for hauler_02 on that same run, all of it under the 500 m
  guard. The figure usually cited against this ("worst |odom_world - truth| =
  0.0816 m") is ~0 BY CONSTRUCTION in localisation mode, because odom_world IS
  truth whenever the truth is fresh; it cannot detect a flip. That is why every
  rejected increment now carries its MAGNITUDE: a count of eight cannot
  distinguish eight 2.6 m hiccups from four 166 m flips.

WHAT THIS FILE IS. Until 2026-07-31 ``get_total_distance`` had ZERO test callers
and ``get_robot_distance`` had zero callers anywhere in the repository -- a
sixth instance of this codebase's wired-but-never-called pattern. These are the
first assertions the accumulator has ever carried.

Nothing here was run against ROS. Every number below is the real
``FleetMonitor`` executed on the Windows host.
"""

import ast
import math
import pathlib

import pytest
import yaml

from selene_orchestrator.fleet_monitor import (
    DISTANCE_REJECTION_HISTORY,
    MAX_PLAUSIBLE_POSE_JUMP_M,
    FleetMonitor,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
SPAWNS = REPO / 'selene_sim' / 'config' / 'spawn_positions.yaml'


def _spawn_fleet() -> list[tuple[str, float, float]]:
    """(robot_id, x, y) for the shipped ten-robot fleet, from the config.

    READ, never hardcoded. This file has already moved twice -- the whole ring
    was relocated when the heightmap row order was fixed, and again when the
    fleet was staged up to ten -- and a literal copied out of it becomes a lie
    on the next move without anything going red.

    The id convention is simulation.launch.py's: the group key minus its
    trailing 's', then a 1-based two-digit index.
    """
    doc = yaml.safe_load(SPAWNS.read_text(encoding='utf-8'))
    fleet = []
    for group, poses in doc.items():
        prefix = group[:-1] if group.endswith('s') else group
        for i, pose in enumerate(poses, start=1):
            fleet.append((f'{prefix}_{i:02d}',
                          float(pose['x']), float(pose['y'])))
    return fleet


def _push(monitor, rid, x, y, ts, *, pose_valid=True, fsm_state='IDLE'):
    monitor.update_robot(
        robot_id=rid, robot_type='scout', fsm_state=fsm_state,
        pose_x=x, pose_y=y, pose_theta=0.0,
        battery_level=0.8, current_task_id='', capabilities=[],
        timestamp=ts, pose_valid=pose_valid)


# --------------------------------------------------------------------------- #
#  The regression                                                              #
# --------------------------------------------------------------------------- #

class TestTheFabricatedOrigin:

    def test_invalid_pose_never_seeds_the_accumulator(self):
        """THE regression test for D-31.

        Three samples at the fabricated (0, 0) with no fix, then a real pose at
        the scout_01 spawn. WITHOUT THE FIX this books 102.416 m -- executed
        against this module, before and after, by passing pose_valid=True on
        the fabricated samples, which is bit-for-bit the pre-fix code path
        because the pre-fix method had no flag and accumulated unconditionally.
        """
        m = FleetMonitor()
        for ts in (0.0, 0.5, 1.0):
            _push(m, 'scout_01', 0.0, 0.0, ts, pose_valid=False)
        _push(m, 'scout_01', -45.0, -92.0, 1.5)

        assert m.get_total_distance() == 0.0, (
            'the fabricated (0, 0) is being integrated again; the pre-fix '
            'value here is %.3f m' % (math.hypot(45.0, 92.0),))
        assert m.get_robot_distance('scout_01') == 0.0
        # And the real pose IS now the anchor, so the next real move counts.
        _push(m, 'scout_01', -45.0, -91.0, 2.0)
        assert m.get_robot_distance('scout_01') == pytest.approx(1.0)

    def test_the_mutation_is_exactly_the_pre_fix_path(self):
        """Proof that the test above can fail, not merely that it passes.

        Same samples, ``pose_valid=True`` on the fabricated ones. That IS the
        pre-fix behaviour -- ``update_robot`` had no such parameter and took
        this branch for every sample -- so the figure it produces is the figure
        the fix removes.
        """
        m = FleetMonitor()
        for ts in (0.0, 0.5, 1.0):
            _push(m, 'scout_01', 0.0, 0.0, ts, pose_valid=True)
        _push(m, 'scout_01', -45.0, -92.0, 1.5)
        assert m.get_total_distance() == pytest.approx(102.416, abs=1e-3)

    def test_ten_robot_startup_books_no_phantom_distance(self):
        """The number that closes D-31, derived rather than embedded.

        Two fabricated samples per robot then the true spawn pose, over the
        whole fleet ``spawn_positions.yaml`` describes for NFR-1.4. The
        pre-fix total is exactly sum(|spawn|) and is computed here from the
        same poses, so it tracks the config instead of asserting a stale
        literal.
        """
        fleet = _spawn_fleet()
        assert len(fleet) == 10, fleet
        phantom = sum(math.hypot(x, y) for _rid, x, y in fleet)

        m = FleetMonitor()
        for rid, x, y in fleet:
            _push(m, rid, 0.0, 0.0, 0.0, pose_valid=False)
            _push(m, rid, 0.0, 0.0, 0.5, pose_valid=False)
            _push(m, rid, x, y, 1.0)

        assert m.get_total_distance() == 0.0, (
            'the ten-robot startup is booking phantom distance again. The '
            'pre-fix value for this exact fixture is %.3f m, per robot %.3f to '
            '%.3f m.'
            % (phantom,
               min(math.hypot(x, y) for _r, x, y in fleet),
               max(math.hypot(x, y) for _r, x, y in fleet)))
        assert all(m.get_robot_distance(rid) == 0.0 for rid, _x, _y in fleet)

    def test_the_ten_robot_mutation_reproduces_1096_580_m(self):
        """The other half of the mutation, on the fleet fixture.

        Reproduced independently twice before this test existed: 1096.580 m
        total, 90.050 m (scout_03) to 127.224 m (hauler_02) per robot.
        """
        fleet = _spawn_fleet()
        m = FleetMonitor()
        for rid, x, y in fleet:
            _push(m, rid, 0.0, 0.0, 0.0, pose_valid=True)
            _push(m, rid, 0.0, 0.0, 0.5, pose_valid=True)
            _push(m, rid, x, y, 1.0)

        assert m.get_total_distance() == pytest.approx(1096.580, abs=1e-3)
        per_robot = {rid: m.get_robot_distance(rid) for rid, _x, _y in fleet}
        assert min(per_robot.values()) == pytest.approx(90.050, abs=1e-3)
        assert max(per_robot.values()) == pytest.approx(127.224, abs=1e-3)

    def test_the_500_m_gate_admits_every_phantom_increment(self):
        """ATTRIBUTION, made executable — the flag is the fix, not the gate.

        A kinematic jump gate would also have rejected the 90-127 m phantom
        increments, and landing both changes together would have made it
        impossible to say which one repaired the number. The gate was therefore
        left exactly where it was, and this asserts what it does: nothing. Zero
        rejections on the fixture that produced the entire defect.
        """
        fleet = _spawn_fleet()
        m = FleetMonitor()
        for rid, x, y in fleet:
            _push(m, rid, 0.0, 0.0, 0.0, pose_valid=True)
            _push(m, rid, x, y, 0.5)

        assert m.distance_rejections == 0, (
            'the implausible-jump guard is now rejecting startup increments, '
            'so it is confounded with the pose_valid fix and neither can be '
            'attributed')
        assert max(math.hypot(x, y) for _r, x, y in fleet) < (
            MAX_PLAUSIBLE_POSE_JUMP_M), (
            'the guard has been tightened below the phantom increments; that '
            'would hide D-31 rather than fix it')

    def test_a_robot_with_no_fix_has_no_position(self):
        """The same fabricated zero also poisoned the FR-MAP-3 centroid.

        ``_survey_reference_position`` averages ``get_robot_position`` over the
        prospect-capable robots, so a fleet still waiting for odometry dragged
        the adaptive survey target ~100 m toward the world origin. The caller
        already filters None.
        """
        m = FleetMonitor()
        _push(m, 'scout_01', 0.0, 0.0, 0.0, pose_valid=False)
        assert m.get_robot_position('scout_01') is None
        # get_robot() is NOT gated: the operator-command paths read it and need
        # a well-formed record. It says the same thing a different way.
        assert m.get_robot('scout_01')['pose_valid'] is False
        assert m.get_robot('scout_01')['pose'] == (0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- #
#  What the accumulator is supposed to compute                                 #
# --------------------------------------------------------------------------- #

class TestTheAccumulator:

    def test_distance_is_the_polyline_of_valid_poses(self):
        """The first assertion this accumulator has ever carried."""
        path = [(0.0, 0.0), (3.0, 4.0), (3.0, 10.0), (-1.0, 10.0)]
        expected = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
        assert expected == pytest.approx(5.0 + 6.0 + 4.0)

        m = FleetMonitor()
        for i, (x, y) in enumerate(path):
            _push(m, 'scout_01', x, y, float(i))
        assert m.get_total_distance() == pytest.approx(expected)
        assert m.get_robot_distance('scout_01') == pytest.approx(expected)

    def test_the_fleet_total_is_the_sum_over_robots(self):
        m = FleetMonitor()
        for rid, step in (('scout_01', 1.0), ('hauler_01', 2.5)):
            _push(m, rid, 0.0, 0.0, 0.0)
            _push(m, rid, step, 0.0, 1.0)
        assert m.get_total_distance() == pytest.approx(3.5)

    def test_duplicate_delivery_adds_nothing(self):
        """A CHARACTERIZATION PIN, not a regression test.

        It passes on the pre-fix code too (measured: ratio 1.0000), because
        ``_last_pose[robot_id]`` is overwritten inside the same call. It exists
        so a refactor that moves that assignment out of ``update_robot`` cannot
        reintroduce double counting unnoticed -- which matters more now that
        RobotState is published on FSM transitions as well as on its timer, so
        near-duplicate samples are ordinary rather than exotic.
        """
        once = FleetMonitor()
        _push(once, 'scout_01', 0.0, 0.0, 0.0)
        _push(once, 'scout_01', 5.0, 0.0, 1.0)

        twice = FleetMonitor()
        _push(twice, 'scout_01', 0.0, 0.0, 0.0)
        _push(twice, 'scout_01', 5.0, 0.0, 1.0)
        _push(twice, 'scout_01', 5.0, 0.0, 1.0)

        assert once.get_total_distance() == pytest.approx(5.0)
        assert twice.get_total_distance() == pytest.approx(
            once.get_total_distance())

    def test_subsampling_never_exceeds_full_rate(self):
        """The invariant the whole D-31 deduction rests on.

        FleetMonitor samples the same ``odom_world`` stream the reference
        integral was computed over, so by the triangle inequality its total
        CANNOT exceed that reference. 1665.37 m against ~753 m is therefore
        proof that non-trajectory increments were being booked -- a deduction,
        not a preference between plausible stories. This makes it a provable
        property of the code rather than an argument in a document.
        """
        path = []
        x = y = 0.0
        for i in range(400):
            x += math.sin(i * 0.37) * 0.4
            y += math.cos(i * 0.11) * 0.3
            path.append((x, y))

        def integrate(points):
            m = FleetMonitor()
            for i, (px, py) in enumerate(points):
                _push(m, 'scout_01', px, py, float(i))
            return m.get_total_distance()

        full = integrate(path)
        assert full > 0.0
        for stride in (2, 5, 10, 83):
            assert integrate(path[::stride]) <= full + 1e-9, (
                f'sub-sampling at every {stride}th point produced a LONGER '
                f'path than the full rate, which is geometrically impossible')


# --------------------------------------------------------------------------- #
#  Rejections, and why a count is not enough                                   #
# --------------------------------------------------------------------------- #

class TestRejections:

    def test_an_implausible_jump_is_rejected_and_recorded_with_its_magnitude(
            self):
        """A count of 8 cannot tell eight hiccups from four 166 m flips."""
        m = FleetMonitor()
        _push(m, 'scout_01', 0.0, 0.0, 0.0)
        _push(m, 'scout_01', 600.0, 0.0, 0.5)

        assert m.get_robot_distance('scout_01') == 0.0
        assert m.distance_rejections == 1
        (record,) = m.get_distance_rejections('scout_01')
        assert record['increment_m'] == pytest.approx(600.0)
        assert record['prev_pose'] == (0.0, 0.0)
        assert record['new_pose'] == (600.0, 0.0)
        assert record['timestamp'] == pytest.approx(0.5)
        assert record['seq'] == 1

    def test_the_gate_is_not_a_motion_threshold(self):
        """Nothing below the guard is discarded, however small.

        A floor on the accumulator would suppress D-31's symptom by throwing
        away real slow motion, which is precisely the "adjust the instrument
        until it stops reporting" move this register exists to name.
        """
        m = FleetMonitor()
        _push(m, 'scout_01', 0.0, 0.0, 0.0)
        _push(m, 'scout_01', 0.0005, 0.0, 0.5)
        assert m.get_robot_distance('scout_01') == pytest.approx(0.0005)
        assert m.distance_rejections == 0

    def test_the_rejection_record_is_bounded(self):
        """Memory in a long-running node. The COUNT is not bounded."""
        m = FleetMonitor()
        _push(m, 'scout_01', 0.0, 0.0, 0.0)
        for i in range(DISTANCE_REJECTION_HISTORY + 5):
            _push(m, 'scout_01', 0.0 if i % 2 else 600.0, 0.0, float(i + 1))

        assert len(m.get_distance_rejections('scout_01')) == (
            DISTANCE_REJECTION_HISTORY)
        assert m.distance_rejections == DISTANCE_REJECTION_HISTORY + 5
        seqs = [r['seq'] for r in m.get_distance_rejections('scout_01')]
        assert seqs == sorted(seqs)
        assert seqs[-1] == m.distance_rejections

    def test_a_fix_outage_does_not_book_the_catch_up_jump(self):
        """The other side of forgetting the anchor.

        A robot that loses its fix at (0, 0) and regains it 50 m away did not
        necessarily travel 50 m in a straight line, and at 0.5 m/s it could not
        have travelled it at all in a short outage. The path across the gap is
        unobservable, so it is not integrated -- the metric under-reports
        rather than inventing a leg. Nothing is rejected here either: this is
        the seed path, not the guard.
        """
        m = FleetMonitor()
        _push(m, 'hauler_01', 0.0, 0.0, 0.0)
        _push(m, 'hauler_01', 1.0, 0.0, 1.0)
        _push(m, 'hauler_01', 0.0, 0.0, 2.0, pose_valid=False)
        _push(m, 'hauler_01', 50.0, 0.0, 3.0)

        assert m.get_robot_distance('hauler_01') == pytest.approx(1.0)
        assert m.distance_rejections == 0
        # And it is anchored on the new pose, so travel resumes immediately.
        _push(m, 'hauler_01', 52.0, 0.0, 4.0)
        assert m.get_robot_distance('hauler_01') == pytest.approx(3.0)


# --------------------------------------------------------------------------- #
#  The orphans now have a reader                                               #
# --------------------------------------------------------------------------- #

def test_the_orchestrator_reads_the_per_robot_distance_and_the_rejections():
    """Otherwise this is a seventh wired-but-never-called instance.

    ``get_robot_distance`` had zero callers anywhere in the repository and
    ``get_distance_rejections`` would have been born with the same defect. A
    residual second mechanism stays as invisible as this one was unless
    something prints the numbers.

    AST, not grep, so a mention in a comment or a docstring cannot satisfy it.
    """
    source = (pathlib.Path(__file__).resolve().parents[1]
              / 'selene_orchestrator' / 'orchestrator_node.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    report = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == '_report_distance_rejections')
    called = {n.func.attr for n in ast.walk(report)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for name in ('get_distance_rejections', 'get_robot_distance'):
        assert name in called, (
            f'{name} has no production reader; calls found: {sorted(called)}')

    heartbeat = next(n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef)
                     and n.name == '_heartbeat_check')
    assert '_report_distance_rejections' in {
        n.func.attr for n in ast.walk(heartbeat)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}, (
        'the rejection report is never called, so refused increments are '
        'silent again -- which is how D-31 survived a full run')
