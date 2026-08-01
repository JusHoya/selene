"""The follower must retire a waypoint it has stopped steering toward.

WHY THIS FILE EXISTS
--------------------
On 2026-08-01 a two-scout fleet spent sixteen minutes making 0.044 m/s of net
progress toward survey waypoints while driving at its full commanded 0.5 m/s,
with a path/net ratio that grew from 1.30x to 5.29x as it entered the crater
approach. Six of ten survey waypoints completed; the other four never did, so
``HTNPlanner``'s ``select_site`` conjunction never resolved, no excavate or haul
task was ever created, and the excavator and hauler recorded ZERO FSM
transitions for the entire run. Register open item 22(b).

THE CAUSE IS AN INVARIANT VIOLATION BETWEEN TWO CONSTANTS, not a tuning problem.
``PathFollower._find_lookahead`` stops steering toward a waypoint once it is
within ``lookahead_distance`` (2.0 m) and scans forward FROM ``_target_idx``;
the retirement loop in ``update`` advanced ``_target_idx`` only within
``waypoint_tolerance`` (1.0 m). Between those two radii sits a band in which the
follower has stopped steering toward a waypoint but has not retired it. On a
straight path the robot crosses that band anyway. On a REVERSAL it curves away,
never closes to 1 m, the index never advances, and the next scan re-acquires the
same waypoint -- the robot orbits.

WHAT MADE IT APPEAR: commit 9c1a4d7, which closed D-28 by enforcing the slope
limit per STEP. That turned A* routes across the crater wall into long chains
with reversals up to 135 deg, which is precisely the geometry that makes a 2 m
lookahead miss a 1 m tolerance. The follower code is older than the symptom.

EVERY TEST BELOW FAILS AGAINST THE PRE-FIX RETIREMENT RULE. The plant here is
IDEAL -- it moves exactly as commanded, cannot slip and has no inertia -- so
nothing in this file can be explained by terrain, traction or latency.
"""

import math

import pytest

from selene_agent.navigator import PathFollower, PathFollowerStatus


class _IdealOdom:
    """A perfect odometry sensor over a pose the test plant owns."""

    def __init__(self, plant):
        self._plant = plant

    def read(self):
        return self._plant


class _Pose:
    is_valid = True

    def __init__(self, x, y, theta):
        self.x = x
        self.y = y
        self.theta = theta
        self.linear_velocity = 0.0
        self.angular_velocity = 0.0


class _IdealKinematics:
    """Just the numbers PathFollower asks the kinematics interface for."""

    def __init__(self, max_speed=0.5, turn_radius=0.0):
        self._max_speed = max_speed
        self._turn_radius = turn_radius

    def get_max_speed(self):
        return self._max_speed

    def get_turn_radius(self):
        return self._turn_radius

    def get_kinematic_model(self):
        return 'differential'

    def get_mass(self):
        return 50.0


class _IdealPlant:
    """Moves exactly as commanded. No slip, no inertia, no terrain."""

    def __init__(self, x=0.0, y=0.0, theta=0.0, max_speed=0.5):
        self.pose = _Pose(x, y, theta)
        self.max_speed = max_speed
        self.path_length = 0.0
        self.yaw_swept = 0.0
        self._v = 0.0
        self._w = 0.0

    # -- DriveInterface ------------------------------------------------------
    def command_velocity(self, linear, angular):
        self._v = linear
        self._w = angular

    def stop(self):
        self._v = 0.0
        self._w = 0.0

    def get_max_speed(self):
        return self.max_speed

    # -- integration ---------------------------------------------------------
    def step(self, dt):
        self.pose.theta += self._w * dt
        self.yaw_swept += abs(self._w) * dt
        dx = self._v * math.cos(self.pose.theta) * dt
        dy = self._v * math.sin(self.pose.theta) * dt
        self.pose.x += dx
        self.pose.y += dy
        self.path_length += math.hypot(dx, dy)
        self.pose.linear_velocity = self._v
        self.pose.angular_velocity = self._w


def _drive(path, start=(0.0, 0.0, 0.0), seconds=240.0, dt=0.1, **kw):
    """Run the REAL PathFollower over *path* with an ideal plant."""
    plant = _IdealPlant(*start)
    follower = PathFollower(
        drive_actuator=plant, odometry_sensor=_IdealOdom(plant.pose),
        kinematics=_IdealKinematics(plant.max_speed),
        lookahead_distance=kw.pop('lookahead_distance', 2.0),
        waypoint_tolerance=kw.pop('waypoint_tolerance', 1.0),
        **kw,
    )
    follower.set_path(path)
    status = None
    for _ in range(int(seconds / dt)):
        status = follower.update(dt)
        if status in (PathFollowerStatus.GOAL_REACHED, PathFollowerStatus.NO_PATH):
            break
        plant.step(dt)
    net = math.hypot(plant.pose.x - start[0], plant.pose.y - start[1])
    return {
        'status': status, 'plant': plant, 'follower': follower,
        'net': net, 'path': plant.path_length,
        'ratio': plant.path_length / net if net > 1e-9 else float('inf'),
        'target_idx': follower._target_idx,
    }


# ---------------------------------------------------------------------------
# The invariant itself
# ---------------------------------------------------------------------------

def test_retirement_radius_is_at_least_the_lookahead():
    """A waypoint the lookahead scan skips must be retired, or the index sticks.

    This is the whole bug in one assertion. It is stated over the CONSTANTS
    rather than over a trajectory so that it fails immediately and by name if
    anyone re-separates the two radii.
    """
    plant = _IdealPlant()
    follower = PathFollower(drive_actuator=plant,
                            odometry_sensor=_IdealOdom(plant.pose),
                            kinematics=_IdealKinematics(plant.max_speed),
                            lookahead_distance=2.0, waypoint_tolerance=1.0)
    follower.set_path([(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)])
    # Sit 1.5 m from waypoint 0 -- inside the lookahead, outside the tolerance.
    plant.pose.x, plant.pose.y = -1.5, 0.0
    follower.update(0.1)
    assert follower._target_idx >= 1, (
        'the follower is 1.5 m from waypoint 0, which _find_lookahead will skip '
        'because it is inside the 2.0 m lookahead, yet the waypoint was not '
        'retired. That is the orbit condition.')


def test_the_shipped_config_satisfies_the_invariant():
    """nav_params.yaml must not reintroduce tolerance < lookahead unnoticed."""
    import os
    import yaml
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, 'config', 'nav_params.yaml')) as handle:
        nav = yaml.safe_load(handle)
    section = nav.get('path_following', nav)
    look = None
    tol = None
    for block in (section, nav):
        if isinstance(block, dict):
            look = block.get('lookahead_distance', look)
            tol = block.get('waypoint_tolerance', tol)
            for v in block.values():
                if isinstance(v, dict):
                    look = v.get('lookahead_distance', look)
                    tol = v.get('waypoint_tolerance', tol)
    assert look is not None and tol is not None, 'constants not found in nav_params.yaml'
    # The fix makes the retirement radius max(tol, lookahead), so the shipped
    # values no longer have to satisfy tol >= lookahead. This test pins that the
    # values are still the ones the fix was reasoned about, so a future change
    # to either has to come here and read why.
    assert (look, tol) == (2.0, 1.0), (
        'lookahead/tolerance changed from (2.0, 1.0); re-read the retirement '
        'comment in PathFollower.update before adjusting either'
    )


# ---------------------------------------------------------------------------
# The trajectory that was actually failing
# ---------------------------------------------------------------------------

def test_a_135_degree_reversal_does_not_orbit():
    """The geometry D-28's per-step routes produce, in isolation.

    Pre-fix this never terminates: the follower rounds the corner, sits between
    1 m and 2 m of the corner waypoint, steers to the next one, curves away, and
    re-acquires the corner forever.
    """
    # Approach heading +x, then reverse 135 degrees.
    path = [(0.0, 0.0), (10.0, 0.0), (2.9, 7.1), (-4.0, 14.0)]
    r = _drive(path, start=(-2.0, 0.0, 0.0), seconds=300.0)
    assert r['status'] == PathFollowerStatus.GOAL_REACHED, (
        f"never reached the goal: drove {r['path']:.1f} m, swept "
        f"{r['plant'].yaw_swept * 180 / math.pi:.0f} deg of yaw, "
        f"stuck at waypoint index {r['target_idx']}"
    )
    assert r['ratio'] < 3.0, f"path/net ratio {r['ratio']:.2f}x on a single corner"


def test_a_switchback_chain_terminates_and_is_efficient():
    """Twenty waypoints with repeated reversals -- the shipped crater route shape."""
    path = [(0.0, 0.0)]
    x, y = 0.0, 0.0
    for i in range(10):
        x += 6.0 if i % 2 == 0 else -6.0
        y += 4.0
        path.append((x, y))
    r = _drive(path, seconds=600.0)
    assert r['status'] == PathFollowerStatus.GOAL_REACHED, (
        f"switchback chain never completed: {r['path']:.1f} m driven, "
        f"index stuck at {r['target_idx']} of {len(path) - 1}"
    )
    # An ideal plant on this path should be close to the path length itself.
    assert r['ratio'] < 4.0, f'path/net {r["ratio"]:.2f}x'
    assert r['plant'].yaw_swept < 8.0 * math.pi, (
        f'swept {r["plant"].yaw_swept * 180 / math.pi:.0f} deg of yaw on a '
        f'10-corner path; the orbit signature is tens of thousands of degrees'
    )


def test_a_straight_path_is_unaffected():
    """The fix must not change behaviour where the old rule was already fine."""
    r = _drive([(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (20.0, 0.0)], seconds=120.0)
    assert r['status'] == PathFollowerStatus.GOAL_REACHED
    assert r['ratio'] < 1.15, f'straight path took {r["ratio"]:.2f}x the direct route'


def test_the_index_advances_monotonically_and_reaches_the_end():
    path = [(0.0, 0.0), (4.0, 3.0), (8.0, -3.0), (12.0, 3.0), (16.0, 0.0)]
    plant = _IdealPlant()
    follower = PathFollower(drive_actuator=plant,
                            odometry_sensor=_IdealOdom(plant.pose),
                            kinematics=_IdealKinematics(plant.max_speed),
                            lookahead_distance=2.0, waypoint_tolerance=1.0)
    follower.set_path(path)
    seen = []
    for _ in range(3000):
        status = follower.update(0.1)
        seen.append(follower._target_idx)
        if status == PathFollowerStatus.GOAL_REACHED:
            break
        plant.step(0.1)
    assert seen == sorted(seen), 'target index went backwards'
    assert seen[-1] == len(path) - 1, (
        f'index reached {seen[-1]} of {len(path) - 1}; the follower stalled')


def test_arrival_tolerance_is_still_tight():
    """Retirement got looser; ARRIVAL must not.

    The goal test still uses waypoint_tolerance, so a robot may not declare
    GOAL_REACHED from 2 m away. This is the assertion that stops the fix from
    being a widened threshold in disguise.
    """
    path = [(0.0, 0.0), (10.0, 0.0)]
    plant = _IdealPlant(x=8.5, y=0.0, theta=0.0)
    follower = PathFollower(drive_actuator=plant,
                            odometry_sensor=_IdealOdom(plant.pose),
                            kinematics=_IdealKinematics(plant.max_speed),
                            lookahead_distance=2.0, waypoint_tolerance=1.0)
    follower.set_path(path)
    # 1.5 m from the goal: inside the lookahead, outside the arrival tolerance.
    assert follower.update(0.1) != PathFollowerStatus.GOAL_REACHED, (
        'declared arrival from 1.5 m with a 1.0 m tolerance')
    plant.pose.x = 9.5
    assert follower.update(0.1) == PathFollowerStatus.GOAL_REACHED


@pytest.mark.parametrize('turn_deg', [30, 60, 90, 120, 135, 150, 170])
def test_every_turn_angle_terminates(turn_deg):
    """Sweep the corner angle; pre-fix the sharp end of this range hangs."""
    a = math.radians(turn_deg)
    path = [(0.0, 0.0), (8.0, 0.0),
            (8.0 + 8.0 * math.cos(a), 8.0 * math.sin(a))]
    r = _drive(path, start=(-2.0, 0.0, 0.0), seconds=400.0)
    assert r['status'] == PathFollowerStatus.GOAL_REACHED, (
        f'{turn_deg} deg corner never completed: {r["path"]:.1f} m driven, '
        f'index {r["target_idx"]}')
