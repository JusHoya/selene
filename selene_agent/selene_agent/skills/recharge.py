"""Recharge skill -- navigate to solar zone and charge to target level."""

from selene_agent.skills.base_skill import BaseSkill, SkillState


class RechargeSkill(BaseSkill):
    """Navigate to the solar recharge station and wait until battery is charged.

    Two phases:
    1. Navigate to the recharge position (progress 0-30%).
    2. Charge until battery reaches the target level (progress 30-100%).
    """

    RECHARGE_TARGET = 0.9

    def __init__(self, recharge_position: tuple[float, float] = (40.0, 40.0),
                 recharge_target: float = 0.9):
        super().__init__("recharge")
        self._recharge_pos = recharge_position
        self._recharge_target = recharge_target
        self._at_station = False
        self._initial_distance = 1.0
        self._hal = None
        self._navigator = None

    def start(self, hal, navigator, **params) -> None:
        self._hal = hal
        self._navigator = navigator
        self._at_station = False
        self._state = SkillState.RUNNING
        self._progress = 0.0

        result = navigator.plan_to(self._recharge_pos)
        if not result.success:
            self._state = SkillState.FAILED
            self._error_message = (
                f"Cannot plan path to recharge station: {result.failure_reason}"
            )
            return

        self._initial_distance = max(navigator.get_distance_to_goal(), 1.0)
        navigator.start_following(result.path)

    def update(self, dt: float) -> None:
        if self._state != SkillState.RUNNING:
            return

        if not self._at_station:
            self._update_navigating(dt)
        else:
            self._update_charging(dt)

    def _update_navigating(self, dt: float) -> None:
        nav_status = self._navigator.update(dt)
        dist = self._navigator.get_distance_to_goal()
        self._progress = max(0.0, 0.3 * (1.0 - dist / self._initial_distance))

        if nav_status == "goal_reached":
            self._at_station = True
            self._hal.get_actuator("drive").stop()
        elif nav_status == "blocked":
            self._state = SkillState.FAILED
            self._error_message = "Cannot reach recharge station"

    def _update_charging(self, dt: float) -> None:
        battery = self._hal.get_battery().get_state()
        charge = battery.charge_fraction
        self._progress = 0.3 + 0.7 * min(charge / self._recharge_target, 1.0)

        if charge >= self._recharge_target:
            self._state = SkillState.COMPLETE
            self._progress = 1.0

    def abort(self) -> None:
        if self._hal:
            try:
                self._hal.get_actuator("drive").stop()
            except (KeyError, AttributeError):
                pass
        if self._navigator:
            self._navigator.stop()
        self._state = SkillState.ABORTED
