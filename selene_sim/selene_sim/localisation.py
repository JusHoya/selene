"""Where a robot BELIEVES it is versus where it actually is.

WHY THIS FILE EXISTS
--------------------
On 2026-07-31 an instrumented 20-minute run delivered 19.0 kg to the depot and
the ledger balanced to float64 zero. The hauler was 241.577 m from the depot at
the time. It had climbed the PSR crater's inner rim wall, pitched over to -35
deg and pinned; from sim 915.2 s to 1235.9 s -- 320.7 s -- its wheel odometry
advanced 126.7 m at the commanded 0.395 m/s cap while its body moved 6.6 cm.
Then it declared arrival and unloaded. (All numbers from that run's analyser
output; not re-measured here.)

NOTHING IN SELENE COULD SEE IT. ``orchestrator_node._check_simulation_stall``
requires a FLEET-WIDE odometry freeze and this robot's odometry was not frozen
-- it advanced at exactly the commanded rate. That is the point: **no
odometry-based check can ever catch a robot whose wheels turn while its body
does not move**, because wheel odometry is the thing that is lying. The only
signal that can is a second, independent position estimate.

WHAT THIS MODULE IS, STATED PLAINLY
-----------------------------------
It is a SIMULATION INSTRUMENT. It compares the dead-reckoned pose against
Gazebo's ground truth, which exists only because this is a simulator. On real
hardware the same comparison is between a localisation stack (star tracker, sun
sensor, visual odometry, terrain-relative nav) and the wheel encoders, and it
is exactly the comparison a real rover runs -- so the *shape* transfers even
though the source does not. Nothing in ``selene_agent``, ``selene_orchestrator``
or ``selene_hal`` imports this file, and nothing should: the autonomy layer must
not be able to ask the simulator where it really is.

THE TWO NUMBERS, AND WHY BOTH
-----------------------------
* ``error_m`` -- the instantaneous distance between the two estimates. Catches
  slow, accumulating drift. In the run above the four robots ended at 13.803 /
  241.577 / 55.247 / 19.437 m.
* ``slip_fraction`` -- over a sliding window, how much of the path the wheels
  reported did the body NOT cover. Catches the pinned-and-spinning case while
  it is happening rather than at the end, and it is the discriminating
  measurement: ``error_m`` alone cannot tell "I drifted 50 m over 20 minutes"
  from "I have been stationary under full throttle for the last 30 seconds".

  Both path lengths are accumulated from the SAME sample instants (see
  ``update``), so a rate difference between the two producers cannot fake a
  slip. Samples are decimated to ``sample_period_s`` before they enter the
  window because the truth stream carries per-step contact jitter: a body
  resting on a heightmap wanders ~1 mm per sample, and integrating |dp| at 166
  Hz turns that into ~0.17 m/s of path that the robot never travelled. At 5 Hz
  the same jitter contributes ~0.1 m over a 20 s window against the 8 m a robot
  at the 0.4 m/s cap covers -- three orders of magnitude of headroom, so the
  decimation is what makes the ratio mean anything.

WHAT IT CANNOT DO
-----------------
It does not correct anything and it does not stop a robot. It reports. The
decision to act on a divergence belongs to the autonomy layer, which cannot see
this signal by construction, so today the only consumer is the operator via a
``FleetAlert``. That is a deliberate stopping point, not an oversight: a
simulator that silently steered the robot back onto its true pose would be the
same class of defect as the one it was written to expose.
"""

from collections import deque
from dataclasses import dataclass
import math


#: Sliding window over which the two path lengths are compared, seconds.
#: 20 s at the 0.4 m/s cap is 8 m of commanded travel, comfortably above the
#: ``SLIP_MIN_ODOM_M`` floor below, and short enough that a robot which pins
#: for 320 s is reported roughly 300 s before it declares a false arrival.
DEFAULT_WINDOW_S: float = 20.0

#: Samples enter the window no more often than this. See the module docstring
#: for why decimation is load-bearing rather than an optimisation.
DEFAULT_SAMPLE_PERIOD_S: float = 0.2

#: The wheels must claim at least this much travel inside the window before a
#: slip ratio is computed at all. Without it a parked robot divides ~0 by ~0
#: and reports 100% slip forever.
DEFAULT_SLIP_MIN_ODOM_M: float = 4.0

#: Fraction of the reported path the body must fail to cover before it counts.
#: 0.70 is well clear of the 4.1% worst-case slip ``scripts/check_drive.sh``
#: measured on healthy ground (lunar_psr.sdf:11-13) and well under the 99.95%
#: the pinned hauler produced.
DEFAULT_SLIP_FRACTION: float = 0.70

#: Distance between the two estimates that counts as a divergence, metres.
#: The ISRU depot radius is 10 m (world_params.yaml) and the haul arrival
#: tolerance is smaller still, so a robot this far out can already deliver to
#: the wrong place.
DEFAULT_ERROR_M: float = 5.0

#: How long a truth sample stays usable. The producer is a Gazebo pose stream
#: at tens of Hz; a second of silence means the simulator or the bridge stopped.
DEFAULT_TRUTH_TIMEOUT_S: float = 1.0


@dataclass(frozen=True)
class Divergence:
    """One comparison of the two position estimates.

    ``odom_path_m`` and ``truth_path_m`` are path LENGTHS over the window --
    sums of |dp| between consecutive retained samples -- not displacements.
    Path length is invariant under any rigid transform, which is what makes
    ``slip_fraction`` a statement about the vehicle rather than about the frame
    the two estimates are expressed in. A frame error moves ``error_m`` and
    leaves ``slip_fraction`` at 0.
    """

    error_m: float
    odom_path_m: float
    truth_path_m: float
    slip_fraction: float
    window_s: float

    @property
    def slip_is_measurable(self) -> bool:
        """True when the wheels claimed enough travel to divide by."""
        return self.odom_path_m >= DEFAULT_SLIP_MIN_ODOM_M


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


class LocalisationMonitor:
    """Track one robot's dead-reckoned pose against its true pose.

    Feed it pairs of (dead-reckoned, truth) positions with a timestamp; it
    returns the current :class:`Divergence` or ``None`` while the window is
    still filling. Pure arithmetic, no ROS, no I/O -- ``selene_sim/test/
    test_localisation.py`` exercises it on the ROS-free lane.
    """

    def __init__(
        self,
        window_s: float = DEFAULT_WINDOW_S,
        sample_period_s: float = DEFAULT_SAMPLE_PERIOD_S,
        slip_min_odom_m: float = DEFAULT_SLIP_MIN_ODOM_M,
        slip_fraction: float = DEFAULT_SLIP_FRACTION,
        error_m: float = DEFAULT_ERROR_M,
        truth_timeout_s: float = DEFAULT_TRUTH_TIMEOUT_S,
    ):
        self._window_s = max(1.0, float(window_s))
        self._sample_period_s = max(0.0, float(sample_period_s))
        self._slip_min_odom_m = max(0.0, float(slip_min_odom_m))
        self._slip_fraction = min(1.0, max(0.0, float(slip_fraction)))
        self._error_m = max(0.0, float(error_m))
        self._truth_timeout_s = max(0.0, float(truth_timeout_s))
        # (t, dead_reckoned_xy, truth_xy) for the retained window.
        self._samples: deque = deque()
        self._last_sample_t: float | None = None
        self._last_truth_t: float | None = None

    # ---------------------------------------------------------------- input

    def note_truth(self, t: float) -> None:
        """Record that a truth sample arrived at *t*, without comparing.

        Called on every truth message so :meth:`truth_is_fresh` stays honest
        even when the decimation drops the sample.
        """
        self._last_truth_t = float(t)

    def truth_is_fresh(self, t: float) -> bool:
        """True when a truth sample arrived recently enough to trust."""
        if self._last_truth_t is None:
            return False
        return (float(t) - self._last_truth_t) <= self._truth_timeout_s

    def update(
        self,
        t: float,
        dead_reckoned_xy: tuple[float, float],
        truth_xy: tuple[float, float],
    ) -> Divergence | None:
        """Add a sample and return the current divergence, or ``None``.

        ``None`` means "not enough window yet" -- fewer than two retained
        samples, or a span shorter than half the configured window. Returning a
        ratio off a 0.2 s span would let one jittery sample raise a CRITICAL.
        """
        t = float(t)
        self.note_truth(t)

        if (self._last_sample_t is not None
                and (t - self._last_sample_t) < self._sample_period_s):
            # Decimated away. The instantaneous error is still available from
            # the caller's own arithmetic; only the window is throttled.
            return self._divergence(t, dead_reckoned_xy, truth_xy)

        self._last_sample_t = t
        self._samples.append((t, tuple(dead_reckoned_xy), tuple(truth_xy)))
        cutoff = t - self._window_s
        while len(self._samples) > 2 and self._samples[0][0] < cutoff:
            self._samples.popleft()

        return self._divergence(t, dead_reckoned_xy, truth_xy)

    # --------------------------------------------------------------- output

    def _divergence(
        self,
        t: float,
        dead_reckoned_xy: tuple[float, float],
        truth_xy: tuple[float, float],
    ) -> Divergence | None:
        error = _dist(dead_reckoned_xy, truth_xy)
        if len(self._samples) < 2:
            return None
        span = self._samples[-1][0] - self._samples[0][0]
        if span < (self._window_s * 0.5):
            return None

        odom_path = 0.0
        truth_path = 0.0
        previous = None
        for sample in self._samples:
            if previous is not None:
                odom_path += _dist(previous[1], sample[1])
                truth_path += _dist(previous[2], sample[2])
            previous = sample

        if odom_path <= 0.0:
            slip = 0.0
        else:
            slip = min(1.0, max(0.0, 1.0 - (truth_path / odom_path)))

        return Divergence(
            error_m=error,
            odom_path_m=odom_path,
            truth_path_m=truth_path,
            slip_fraction=slip,
            window_s=span,
        )

    # ------------------------------------------------------------- verdicts

    def is_slipping(self, divergence: Divergence | None) -> bool:
        """True when the wheels moved and the body did not.

        Both clauses are required. ``odom_path_m >= slip_min_odom_m`` is what
        keeps a parked robot -- which trivially satisfies "the body did not
        move" -- from raising an alert every window.
        """
        if divergence is None:
            return False
        return (divergence.odom_path_m >= self._slip_min_odom_m
                and divergence.slip_fraction >= self._slip_fraction)

    def is_diverged(self, divergence: Divergence | None) -> bool:
        """True when the two estimates disagree by more than the threshold."""
        if divergence is None:
            return False
        return divergence.error_m > self._error_m

    @property
    def error_threshold_m(self) -> float:
        return self._error_m

    @property
    def slip_threshold(self) -> float:
        return self._slip_fraction
