"""The robot energy model, as pure Python with zero ROS dependencies.

WHY THIS FILE EXISTS. Until 2026-08-01 this arithmetic lived inside
``battery_node.BatteryNode._update``, behind a module-level ``import rclpy``, and
it had **no tests of any kind** -- no unit test, no wiring test, no
config-agreement test. The only occurrence of ``battery_state`` under any
``test/`` directory was a string in an allow-list. When register entry D-42 asked
whether the simulator could produce ``percentage = 0.0`` within 18.5 s, the
answer had to be re-derived by hand, twice, because there was nothing to run.

Extracting it is the same move ``selene_sim/selene_sim/localisation.py`` and
``world_frame.py`` already make in this package, and it is made for the same
reason: the interesting behaviour is arithmetic, arithmetic is testable in any
lane, and a test that needs a ROS graph runs in one lane out of five.

**Do not add ROS to this module.** ``battery_node`` owns the subscriptions, the
publisher and the clock; this owns the integration and nothing else.

THE MODEL::

    power_w   = idle + locomotion_per_ms * speed * slope_factor + actuators
    slope     = 1 + 2 sin(atan2(dz, horizontal)),  floored at 0.3, so 0.3..3.0
    solar      = subtract solar_recharge_w when OUTSIDE a PSR disc AND stationary
    remaining = clamp(remaining - power_w * dt / 3600, 0, capacity)

TWO PROPERTIES OF THAT LAST LINE ARE LOAD-BEARING, and both are D-42:

1. **The lower clamp returns exactly 0.0.** Not a small residue, not a negative.
   A robot at the clamp publishes ``percentage == 0.0``, which is the literal
   string an operator sees in ``Battery critical (0.0%)``.
2. **Nothing in here decays ``speed``.** The caller supplies it, and
   ``battery_node`` supplies whatever ``cmd_vel`` last carried. A node whose
   simulator has exited therefore keeps integrating locomotion draw at the last
   commanded speed for as long as the process lives -- measured at 85.0 W for a
   scout at 0.5 m/s, which empties a 50 Wh scout in 2118 s and pins it at the
   clamp thereafter. That is not a defect in this model; it is a correct
   integration of an input that stopped being true, and the remedy belongs where
   the input comes from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


#: Ceiling on the slope multiplier: 1 + 2*sin(90 deg).
MAX_SLOPE_FACTOR = 3.0

#: Floor on it, so a steep descent still costs something.
MIN_SLOPE_FACTOR = 0.3

#: A robot moving slower than this counts as stationary for solar purposes.
SOLAR_SPEED_EPSILON = 0.05

#: Horizontal travel below which slope is unmeasurable and assumed flat.
FLAT_EPSILON_M = 0.001


@dataclass(frozen=True)
class BatteryTick:
    """One integration step's outcome."""
    remaining_wh: float
    power_w: float
    is_charging: bool
    slope_factor: float

    @property
    def at_empty_clamp(self) -> bool:
        """True when this tick landed on the lower clamp -- D-42's signature."""
        return self.remaining_wh == 0.0


def slope_factor(dz: float, horizontal: float) -> float:
    """Locomotion multiplier for a step that rose *dz* over *horizontal* metres.

    Bounded in ``[MIN_SLOPE_FACTOR, MAX_SLOPE_FACTOR]`` by construction, which is
    the half of D-42's ruling that closes off "the healthy node's draw ran away":
    no geometry makes this unbounded, so no geometry makes the drain unbounded.
    """
    if horizontal < FLAT_EPSILON_M:
        return 1.0
    return max(1.0 + 2.0 * math.sin(math.atan2(dz, horizontal)),
               MIN_SLOPE_FACTOR)


def is_in_psr(x: float, y: float, psr_zones) -> bool:
    """True when (x, y) is inside any permanently shadowed disc.

    *psr_zones* is the ``world.psr_zones`` list from ``world_params.yaml``:
    dicts with ``type: circle``, ``center: [x, y]`` and ``radius``. Anything
    with another ``type`` is ignored rather than guessed at.
    """
    for zone in psr_zones or ():
        if zone.get('type') != 'circle':
            continue
        cx, cy = zone['center']
        if math.hypot(x - cx, y - cy) <= zone['radius']:
            return True
    return False


class BatteryModel:
    """Stateful energy integrator for one robot.

    Holds ``remaining_wh`` and the previous position (for the slope estimate).
    Every other input is passed to :meth:`step`, because every other input is
    something the caller learned from a message and this module has no messages.
    """

    def __init__(self, capacity_wh: float, idle_draw_w: float,
                 locomotion_draw_w_per_ms: float, solar_recharge_w: float,
                 psr_zones=None, remaining_wh: float | None = None):
        self.capacity_wh = float(capacity_wh)
        self.idle_draw_w = float(idle_draw_w)
        self.locomotion_draw_w_per_ms = float(locomotion_draw_w_per_ms)
        self.solar_recharge_w = float(solar_recharge_w)
        self.psr_zones = list(psr_zones or ())
        self.remaining_wh = (
            self.capacity_wh if remaining_wh is None else float(remaining_wh))
        self.last_position: tuple[float, float, float] | None = None

    @property
    def charge_fraction(self) -> float:
        """0..1. This is the number published as ``BatteryState.percentage``."""
        return self.remaining_wh / self.capacity_wh

    def step(self, dt: float, speed: float,
             position: tuple[float, float, float],
             actuator_draw_w: float = 0.0) -> BatteryTick:
        """Integrate one tick of *dt* seconds and return what happened."""
        if self.last_position is None:
            factor = 1.0
        else:
            dx = position[0] - self.last_position[0]
            dy = position[1] - self.last_position[1]
            dz = position[2] - self.last_position[2]
            factor = slope_factor(dz, math.hypot(dx, dy))
        self.last_position = position

        power_w = (self.idle_draw_w
                   + self.locomotion_draw_w_per_ms * speed * factor
                   + actuator_draw_w)

        charging = False
        if (not is_in_psr(position[0], position[1], self.psr_zones)
                and speed < SOLAR_SPEED_EPSILON):
            charging = True
            power_w -= self.solar_recharge_w

        delta_wh = power_w * dt / 3600.0
        # The clamp. Lower bound returns the float 0.0 exactly; see the module
        # docstring, and selene_sim/test/test_battery_model.py for the pin.
        self.remaining_wh = max(
            0.0, min(self.capacity_wh, self.remaining_wh - delta_wh))

        return BatteryTick(remaining_wh=self.remaining_wh, power_w=power_w,
                           is_charging=charging, slope_factor=factor)
