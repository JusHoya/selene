"""The wheels-are-lying detector, checked without ROS or Gazebo.

``selene_sim/selene_sim/localisation.py`` is the only thing in this project that
can catch a robot whose wheel odometry advances while its body does not move. It
was written after a hauler did exactly that for 320.7 s on 2026-07-31 and then
reported a successful delivery 241.577 m from the depot, with the heartbeat
check, the fleet-freeze check and the progress check all satisfied throughout.

The scenarios below are built from that run's own numbers where they are known,
so the test says "this detector would have caught THAT" rather than "this
detector catches something".
"""

import math

import pytest

from selene_sim.localisation import (
    DEFAULT_SLIP_MIN_ODOM_M,
    Divergence,
    LocalisationMonitor,
)


def _drive(monitor, seconds, odom_speed, truth_speed, dt=0.05,
           start_t=0.0, heading=0.0):
    """Feed *seconds* of straight-line motion; return the last divergence."""
    t = start_t
    odom = [0.0, 0.0]
    truth = [0.0, 0.0]
    out = None
    steps = int(round(seconds / dt))
    for _ in range(steps):
        t += dt
        odom[0] += odom_speed * dt * math.cos(heading)
        odom[1] += odom_speed * dt * math.sin(heading)
        truth[0] += truth_speed * dt * math.cos(heading)
        truth[1] += truth_speed * dt * math.sin(heading)
        out = monitor.update(t, tuple(odom), tuple(truth))
    return out


# ----------------------------------------------------------------- the basics

def test_a_healthy_drive_reports_no_slip_and_no_divergence():
    """Both estimates agree: nothing to report.

    0.4 m/s is the commanded cap in nav_params.yaml, and 30 s at that rate is
    12 m -- above DEFAULT_SLIP_MIN_ODOM_M, so the ratio really is evaluated
    rather than skipped for want of travel.
    """
    monitor = LocalisationMonitor()
    divergence = _drive(monitor, 30.0, odom_speed=0.4, truth_speed=0.4)
    assert divergence is not None
    assert divergence.slip_fraction == pytest.approx(0.0, abs=1e-9)
    assert divergence.error_m == pytest.approx(0.0, abs=1e-9)
    assert not monitor.is_slipping(divergence)
    assert not monitor.is_diverged(divergence)


def test_the_measured_healthy_slip_does_not_trip_it():
    """4.1% slip is the worst check_drive.sh measured on real ground.

    lunar_psr.sdf:11-13 records a hauler covering 4.4197 m against 4.6065 m of
    odometry on the shipped terrain under lunar gravity. A detector that fires
    on that is useless, so the threshold is pinned against the measurement
    rather than against a round number.
    """
    monitor = LocalisationMonitor()
    divergence = _drive(monitor, 30.0, odom_speed=0.4, truth_speed=0.4 * 0.959)
    assert divergence.slip_fraction == pytest.approx(0.041, abs=0.005)
    assert not monitor.is_slipping(divergence)


def test_a_pinned_robot_is_caught_while_it_is_still_pinned():
    """THE CASE THIS FILE EXISTS FOR.

    The 2026-07-31 hauler: wheels at the commanded 0.395 m/s, body at
    6.6 cm / 320.7 s = 0.0002 m/s. The window is 20 s, so a report is available
    within ~20 s of the pin -- 300 s before the robot declared arrival.
    """
    monitor = LocalisationMonitor()
    divergence = _drive(monitor, 25.0, odom_speed=0.395, truth_speed=0.000206)
    assert monitor.is_slipping(divergence)
    assert divergence.slip_fraction > 0.99
    # ~7.9 m of wheel travel over the retained window, ~0.004 m covered.
    assert divergence.odom_path_m > DEFAULT_SLIP_MIN_ODOM_M
    assert divergence.truth_path_m < 0.01


def test_a_parked_robot_is_not_reported_as_slipping():
    """The clause that keeps the alert log readable.

    A stationary robot satisfies "the body did not move" perfectly. Without the
    odom-travel floor every IDLE robot would raise a CRITICAL every window,
    which is how the register describes an alert becoming wallpaper.
    """
    monitor = LocalisationMonitor()
    divergence = _drive(monitor, 30.0, odom_speed=0.0, truth_speed=0.0)
    assert divergence is not None
    assert not monitor.is_slipping(divergence)


def test_truth_jitter_on_a_stationary_body_cannot_fake_travel():
    """Decimation is load-bearing, not an optimisation.

    A body resting on a heightmap wanders ~1 mm per physics sample. Integrating
    |dp| at the raw rate would turn that into metres of phantom path and mask a
    real slip. Feed pure jitter at 20 Hz against a moving wheel and the slip
    fraction must still read ~1.
    """
    monitor = LocalisationMonitor()
    t = 0.0
    odom = [0.0, 0.0]
    divergence = None
    for i in range(600):                       # 30 s at 20 Hz
        t += 0.05
        odom[0] += 0.4 * 0.05
        jitter = 0.001 * (1 if i % 2 else -1)
        divergence = monitor.update(t, tuple(odom), (jitter, -jitter))
    assert monitor.is_slipping(divergence)
    assert divergence.truth_path_m < 0.2       # 30 s of 1 mm jitter, decimated


# ------------------------------------------------------------------ the drift

def test_drift_is_reported_without_any_slip():
    """A heading error is not a slip, and the two must not be confused.

    The 2026-07-31 scouts covered 95.8 m and 91.3 m of true path against 99.0 m
    and 94.1 m of odometry -- a ratio of 1.03, i.e. distance tracked well -- and
    still ended 55.2 m and 19.4 m from their believed positions, because the
    HEADING was wrong. Path length is invariant under a rigid transform, so
    slip_fraction correctly reads ~0 while error_m grows.
    """
    monitor = LocalisationMonitor()
    t = 0.0
    odom = [0.0, 0.0]
    truth = [0.0, 0.0]
    divergence = None
    for _ in range(600):
        t += 0.05
        odom[0] += 0.4 * 0.05                              # believes: due +x
        truth[0] += 0.4 * 0.05 * math.cos(0.6)             # actually: 0.6 rad off
        truth[1] += 0.4 * 0.05 * math.sin(0.6)
        divergence = monitor.update(t, tuple(odom), tuple(truth))
    assert divergence.slip_fraction == pytest.approx(0.0, abs=1e-6)
    assert not monitor.is_slipping(divergence)
    assert monitor.is_diverged(divergence)
    assert divergence.error_m > 6.0


def test_a_frame_error_never_shows_up_as_slip():
    """The property that makes slip_fraction a statement about the vehicle.

    Rotate and translate the truth stream by an arbitrary rigid transform. The
    error explodes; the two path lengths are unchanged, so the ratio must not
    move at all.
    """
    plain = LocalisationMonitor()
    rotated = LocalisationMonitor()
    t = 0.0
    odom = [0.0, 0.0]
    truth = [0.0, 0.0]
    yaw, tx, ty = 1.1, 37.0, -12.0
    a, b = None, None
    for _ in range(600):
        t += 0.05
        odom[0] += 0.4 * 0.05
        truth[0] += 0.4 * 0.05
        rx = truth[0] * math.cos(yaw) - truth[1] * math.sin(yaw) + tx
        ry = truth[0] * math.sin(yaw) + truth[1] * math.cos(yaw) + ty
        a = plain.update(t, tuple(odom), tuple(truth))
        b = rotated.update(t, tuple(odom), (rx, ry))
    assert b.slip_fraction == pytest.approx(a.slip_fraction, abs=1e-12)
    assert b.truth_path_m == pytest.approx(a.truth_path_m, abs=1e-9)
    assert b.error_m > 30.0


# ------------------------------------------------------------- the guard rails

def test_no_verdict_until_the_window_has_filled():
    """One jittery sample must not be able to raise a CRITICAL."""
    monitor = LocalisationMonitor()
    assert monitor.update(0.0, (0.0, 0.0), (0.0, 0.0)) is None
    assert monitor.update(0.5, (0.2, 0.0), (0.0, 0.0)) is None
    assert not monitor.is_slipping(None)
    assert not monitor.is_diverged(None)


def test_truth_freshness_expires():
    """A silent truth stream is not a fresh one."""
    monitor = LocalisationMonitor(truth_timeout_s=1.0)
    assert not monitor.truth_is_fresh(0.0)     # nothing has arrived yet
    monitor.note_truth(10.0)
    assert monitor.truth_is_fresh(10.5)
    assert monitor.truth_is_fresh(11.0)
    assert not monitor.truth_is_fresh(11.5)


def test_the_window_forgets():
    """A robot that slipped and recovered stops being reported as slipping."""
    monitor = LocalisationMonitor(window_s=20.0)
    divergence = _drive(monitor, 25.0, odom_speed=0.4, truth_speed=0.0)
    assert monitor.is_slipping(divergence)
    divergence = _drive(monitor, 25.0, odom_speed=0.4, truth_speed=0.4,
                        start_t=25.0)
    assert not monitor.is_slipping(divergence)


def test_divergence_reports_its_own_window_length():
    """The alert quotes the span, so it must be the span actually used."""
    monitor = LocalisationMonitor(window_s=20.0)
    divergence = _drive(monitor, 40.0, odom_speed=0.4, truth_speed=0.4)
    assert divergence.window_s <= 20.0 + 1e-9
    assert divergence.window_s >= 19.0


def test_slip_is_measurable_matches_the_floor():
    """The dataclass helper and the monitor agree about the floor."""
    small = Divergence(error_m=0.0, odom_path_m=DEFAULT_SLIP_MIN_ODOM_M - 0.1,
                       truth_path_m=0.0, slip_fraction=1.0, window_s=20.0)
    big = Divergence(error_m=0.0, odom_path_m=DEFAULT_SLIP_MIN_ODOM_M + 0.1,
                     truth_path_m=0.0, slip_fraction=1.0, window_s=20.0)
    assert not small.slip_is_measurable
    assert big.slip_is_measurable
    monitor = LocalisationMonitor()
    assert not monitor.is_slipping(small)
    assert monitor.is_slipping(big)
