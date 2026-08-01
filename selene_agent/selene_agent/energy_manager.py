"""Energy tracking and budget decisions for SELENE agents.

Pure Python -- zero ROS dependencies.  Wraps a HAL BatteryInterface
to provide higher-level affordability checks and range estimation.
"""

from __future__ import annotations

import math
from typing import Optional

from selene_hal.battery_interface import BatteryInterface
from selene_hal.data_types import BatteryState


# Default assumed locomotion speed when computing energy costs (m/s).
_DEFAULT_SPEED = 0.3

# Safety margin multiplier applied to total mission energy budget.
_SAFETY_MARGIN = 1.10  # 10%


# ---------------------------------------------------------------------------
#  Recharge reasons returned by ``EnergyManager.recharge_reason``.
#
#  Strings rather than an enum because they are logged verbatim and because
#  ``agent_node`` has no other use for them; '' is the "no reason" answer, so
#  the predicate reads as ``if reason:`` at every call site.
# ---------------------------------------------------------------------------

#: At or below ``critical_threshold``. The emergency; the tick loop's own
#: ENERGY_CRITICAL branch normally gets here first.
RECHARGE_CRITICAL = 'battery_critical'

#: At or below ``recharge_threshold`` -- the configured floor.
RECHARGE_BELOW_THRESHOLD = 'below_recharge_threshold'

#: Above the floor, but no longer enough energy to drive home with margin.
RECHARGE_RETURN_MARGIN = 'no_return_margin'


class EnergyManager:
    """Energy bookkeeper for a single lunar robot.

    Parameters
    ----------
    battery:
        HAL battery interface providing raw state and power parameters.
    critical_threshold:
        Charge fraction at or below which ENERGY_CRITICAL fires.
    recharge_target:
        Charge fraction at or above which the robot is "fully charged".
    recharge_station:
        (x, y) coordinates of the recharge station on the surface.
    recharge_threshold:
        Charge fraction at or below which the robot should go and charge
        even though it is not yet critical -- the FLOOR under
        ``recharge_reason``. Must sit strictly between *critical_threshold*
        and *recharge_target*; see ``recharge_reason`` for what happens
        otherwise.
    """

    def __init__(
        self,
        battery: BatteryInterface,
        critical_threshold: float = 0.15,
        recharge_target: float = 0.90,
        recharge_station: tuple[float, float] = (40.0, 40.0),
        recharge_threshold: float = 0.30,
    ):
        self._battery = battery
        self._critical_threshold = critical_threshold
        self._recharge_target = recharge_target
        self._recharge_station = recharge_station
        self._recharge_threshold = recharge_threshold
        self._cached_state: Optional[BatteryState] = None

    # -- State updates --------------------------------------------------------

    def update(self, state: BatteryState) -> None:
        """Cache the latest battery state snapshot."""
        self._cached_state = state

    # -- Queries --------------------------------------------------------------

    def _current_state(self) -> BatteryState:
        """Return cached state, falling back to a live read."""
        if self._cached_state is not None:
            return self._cached_state
        return self._battery.get_state()

    def has_valid_reading(self) -> bool:
        """True when the cached charge came from a reading that actually arrived.

        Added 2026-08-01 closing D-42. ``BatteryState.charge_fraction`` defaults
        to 1.0 and ``GazeboBattery`` seeds its cache from the RCDL capacity, so a
        HAL that has received nothing reports a confident full battery. That is
        the safe direction for the *value* and the wrong direction for the
        *claim*: the agent must be able to tell "full" from "unknown", because
        the two call for different behaviour and only one of them is a fact.
        """
        return bool(self._current_state().is_valid)

    def is_critical(self) -> bool:
        """True when charge fraction is at or below the critical threshold.

        FALSE ON AN UNVALIDATED READING, and that is the whole D-42 fix on this
        side. An unvalidated reading is not evidence of a full battery either --
        it is not evidence of anything - so the emergency does not fire on it.
        ``agent_node`` is responsible for noticing that a reading has STAYED
        unvalidated, which is a different fault with a different remedy; see
        ``_check_battery_health``.
        """
        state = self._current_state()
        if not state.is_valid:
            return False
        return state.charge_fraction <= self._critical_threshold

    def is_fully_charged(self) -> bool:
        """True when charge fraction is at or above the recharge target."""
        return self._current_state().charge_fraction >= self._recharge_target

    def get_charge_fraction(self) -> float:
        """Return current charge as a 0-1 fraction."""
        return self._current_state().charge_fraction

    def get_remaining_wh(self) -> float:
        """Return remaining energy in watt-hours."""
        return self._current_state().remaining_wh

    def estimate_range_m(self, speed: float = _DEFAULT_SPEED) -> float:
        """Estimated remaining travel range in meters at *speed*."""
        return self._battery.estimate_range_m(speed)

    # -- Budget checks --------------------------------------------------------

    def compute_energy_cost_wh(
        self,
        distance_m: float,
        task_energy_wh: float = 0.0,
    ) -> float:
        """Compute total energy cost for travelling *distance_m* and performing a task.

        Energy model:
            travel_time_s  = distance_m / speed
            locomotion_wh  = locomotion_draw_w * speed * travel_time_s / 3600
            idle_wh        = idle_draw_w * travel_time_s / 3600
            total          = locomotion_wh + idle_wh + task_energy_wh
        """
        speed = _DEFAULT_SPEED
        if speed <= 0:
            return task_energy_wh

        travel_time_s = distance_m / speed
        locomotion_wh = (
            self._battery.get_locomotion_draw_w() * speed * travel_time_s / 3600.0
        )
        idle_wh = self._battery.get_idle_draw_w() * travel_time_s / 3600.0
        return locomotion_wh + idle_wh + task_energy_wh

    def can_afford_task(
        self,
        current_position: tuple[float, float],
        task_position: tuple[float, float],
        task_energy_wh: float = 0.0,
    ) -> bool:
        """Return True if the robot can go to the task, do it, and return to base.

        Budget:
            go_distance   = ||current_position - task_position||
            return_dist   = ||task_position - recharge_station||
            total_energy  = cost(go_distance + return_dist, task_energy) * 1.10
        """
        go_dist = _euclidean(current_position, task_position)
        return_dist = _euclidean(task_position, self._recharge_station)
        total_distance = go_dist + return_dist
        cost = self.compute_energy_cost_wh(total_distance, task_energy_wh)
        budget = cost * _SAFETY_MARGIN
        return self.get_remaining_wh() >= budget

    def get_distance_to_base(
        self, current_position: tuple[float, float]
    ) -> float:
        """Euclidean distance from *current_position* to the recharge station."""
        return _euclidean(current_position, self._recharge_station)

    def can_return_to_base(
        self, current_position: tuple[float, float]
    ) -> bool:
        """True if the robot could still drive home from *current_position*.

        The same energy model and the same 1.10 safety margin as
        ``can_afford_task``, with the outbound leg and the task cost removed:
        this asks only "can I still get back", which is the question that
        decides whether it is safe to STAY in the field.

        ``can_afford_task`` is the wrong predicate for that decision even
        though it looks close. It measures a specific proposed task, so it
        answers "should I bid", and a robot with no task in front of it has
        nothing to pass to it. This one is total over the robot's own state.
        """
        distance = self.get_distance_to_base(current_position)
        cost = self.compute_energy_cost_wh(distance)
        return self.get_remaining_wh() >= cost * _SAFETY_MARGIN

    def recharge_reason(
        self,
        current_position: Optional[tuple[float, float]] = None,
    ) -> str:
        """Why this robot should go and charge NOW, or '' if it should not.

        This is the whole recharge policy, in one pure function, tested
        without ROS. ``agent_node`` used to have no policy at all: every task
        ended with an unconditional ``_start_recharge()``, so a scout that
        finished a waypoint at 91% drove back to base, charged to 90%, and
        did it again -- measured live on 2026-07-31 at 88-93% per cycle, with
        the fleet in RECHARGING for the majority of two runs and the HTN's
        SelectSite unable to resolve because the survey waypoints never all
        completed. See deviation D-19.

        Three tiers, most urgent first:

        1. ``battery_critical`` -- at or below ``critical_threshold``. The
           agent's tick loop tests ``is_critical()`` directly and normally
           fires ENERGY_CRITICAL before this is ever reached; it is here so
           the predicate is total rather than relying on a caller ordering.
        2. ``below_recharge_threshold`` -- at or below ``recharge_threshold``.
           THE FLOOR, and deliberately a flat fraction: it is the one tier
           that needs no position, so it still holds when odometry is
           unreadable, which is exactly when the margin calculation below
           cannot be trusted.
        3. ``no_return_margin`` -- above the floor, but the energy left no
           longer covers the drive home with the 1.10 margin. This is the
           tier that makes the policy safe rather than merely cheap: a flat
           percentage is a bet that the robot is never further from base than
           that percentage can carry it, and nothing in this system enforces
           that bet. Requires a position; skipped when *current_position* is
           None (see the caller in ``agent_node._recharge_reason``).

        A misconfigured ``recharge_threshold >= recharge_target`` would make
        a robot that has just finished charging immediately want to charge
        again -- a busy loop between IDLE and RETURNING. That is NOT clamped
        here, because this class has no logger and silently substituting a
        different number is how a configuration defect becomes invisible;
        ``agent_node`` validates it once at construction, where it can say so.
        """
        # NO READING, NO POLICY. All three tiers below are arithmetic on a
        # charge fraction, and on an unvalidated reading that fraction is the
        # dataclass default rather than a measurement (D-42). Returning '' here
        # is the same ANSWER the tiers would have produced -- an unvalidated
        # state reports 1.0, which is above every threshold -- but it is a
        # different STATEMENT: "I have nothing to decide on" rather than "I
        # decided, and the answer is that the battery is fine". The agent's
        # ``_check_battery_health`` is what turns a persistent absence of
        # readings into an alarm; this function's job is only to not invent one.
        if not self.has_valid_reading():
            return ''
        if self.is_critical():
            return RECHARGE_CRITICAL
        if self.get_charge_fraction() <= self._recharge_threshold:
            return RECHARGE_BELOW_THRESHOLD
        if current_position is not None and not self.can_return_to_base(
            current_position
        ):
            return RECHARGE_RETURN_MARGIN
        return ''

    def get_recharge_threshold(self) -> float:
        """The configured recharge floor, as a 0-1 charge fraction."""
        return self._recharge_threshold


# -- Helpers ------------------------------------------------------------------


def _euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    """2D Euclidean distance."""
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.sqrt(dx * dx + dy * dy)
