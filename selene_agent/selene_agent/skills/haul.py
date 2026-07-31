"""Haul skill -- pickup material from site, deliver to depot."""

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from selene_agent.skills.base_skill import BaseSkill, SkillState


class HaulPhase(str, Enum):
    NAVIGATING_TO_PICKUP = "navigating_to_pickup"
    LOADING = "loading"
    NAVIGATING_TO_DEPOT = "navigating_to_depot"
    UNLOADING = "unloading"


@dataclass(frozen=True)
class HaulResult:
    pickup_position: tuple[float, float]
    depot_position: tuple[float, float]
    # Mass taken on at the pickup site, kg: the load cell after loading
    # settled minus the load cell on arrival.
    loaded_kg: float
    # The load cell's ABSOLUTE reading once loading finished, kg. This is
    # MaterialEvent.residual_mass_kg for the 'loaded' event -- that field is
    # defined as the instrument's own reading immediately after the transfer,
    # so it is a genuine second number and not loaded_kg restated: a bin that
    # arrived with residue reads higher than it loaded.
    bin_mass_after_load_kg: float
    # Mass put down at the depot, kg: the load cell before the dump minus the
    # load cell after it. This is a DIFFERENT measurement from loaded_kg and
    # they are both needed -- the ledger's extracted / in_transit / deposited
    # split is exactly the difference between them. Before this change the
    # field was named "delivered" but was assigned the load cell's reading at
    # LOAD time, so a haul that dropped nothing at the depot still reported a
    # full delivery.
    delivered_kg: float
    # Load cell reading after the dump, kg. Expected near zero; a hauler that
    # reports 19 kg delivered while still reading 7 kg is a fault this makes
    # visible on the orchestrator side.
    residual_mass_kg: float
    timestamp: float
    # NaN in any of the three masses above means the load cell could not be
    # read at the moment that measurement was due -- see HaulSkill._read_fill.
    # agent_node publishes no MaterialEvent for a non-finite mass, because a
    # missing measurement is honest and a fabricated 0.0 is not.


class HaulSkill(BaseSkill):
    """Drive to a pickup site, load material, drive to depot, unload.

    Internal phases:
    NAVIGATING_TO_PICKUP (0-25%) -> LOADING (25-50%) ->
    NAVIGATING_TO_DEPOT (50-75%) -> UNLOADING (75-100%) -> COMPLETE

    **The pickup leg stops short.** LOADING begins at
    ``PICKUP_STANDOFF_M`` from the pickup coordinate, not on it, because that
    coordinate routinely has a parked excavator on it -- see the constant.
    The depot leg is unchanged and still drives all the way in; multiple
    haulers converging on one depot marker is the same hazard and is NOT
    addressed here (register D-22).

    **Transfer completion is observed from the load cell, not from
    ``TransferActuator.is_transfer_complete()``.** On the Gazebo backend
    ``_complete`` is set True only in the constructor
    (``selene_hal/selene_hal/gazebo_hal.py:491``) and in ``cancel_transfer``
    (``:512``), while ``trigger_load`` and ``trigger_unload`` set it False and
    nothing sets it back -- so a skill that gates on it never advances and
    fails at LOAD_TIMEOUT on every haul. That is a **static argument from
    reading gazebo_hal.py**, not something observed on a running system; the
    unit suite never caught it because ``StubTransferActuator`` returns True
    unconditionally (``stub_hal.py``). Watching the load cell replaces an
    actuator self-report with a measurement, which is also the number the
    material ledger needs.
    """

    LOAD_TIMEOUT = 30.0
    UNLOAD_TIMEOUT = 30.0

    # ------------------------------------------------------------------
    # Rendezvous standoff (deviation D-22)
    # ------------------------------------------------------------------
    # A haul used to drive ONTO its pickup coordinate. With the excavator
    # staying in the field after excavating (the D-19 recharge fix) that
    # coordinate is where a 150 kg excavator is parked, and the two bodies
    # interpenetrated deeply enough that gz-sim's ODE collision space aborted
    # the whole simulator -- `ODE INTERNAL ERROR 1: assertion "aabbBound >=
    # dMinIntExact && aabbBound < dMaxIntExact" failed in collide()`, SIGABRT,
    # exit 134. MEASURED LIVE TWICE on 2026-07-31 (ROS 2 Jazzy / Gazebo
    # Harmonic); the abort was the next Gazebo line after this skill logged
    # `phase=loading`. `ros2 launch` survives the abort, so the fleet then
    # degrades silently -- which is the half D-21 addressed, from the other
    # side: FleetMonitor's frozen-odometry detector NOTICES the abort. This
    # removes one cause of it. The two are complements, and neither makes ODE
    # robust: deep interpenetration aborting gz-sim is not fixable from here.
    #
    # THIS IS THE CONTROL-SIDE GUARANTEE, and it is here rather than in the
    # planner because the planner is not the only source of a pickup: an
    # operator can inject a haul at any coordinate (FR-DASH-5), including one
    # with a robot standing on it. Everything below applies to that path too.
    #
    # DERIVATION. Required standoff = footprint clearance + how far the
    # obstacle robot may be from the coordinate + how far this robot may
    # travel past the moment it decides to stop.
    #
    #   footprint clearance                                  1.169 m
    #     circumscribed XY radius of the excavator and of the hauler, from
    #     the collision links in selene_sim/models/{excavator,hauler}/model.sdf
    #     (0.5847 m each, both set by a front wheel). Re-derived from those
    #     files by test_haul_pickup_standoff.py.
    #   excavator rest offset from its excavate target       1.180 m
    #     PathFollower declares arrival at waypoint_tolerance 1.0 m
    #     (navigator.py:385,436 and selene_agent/config/nav_params.yaml:14)
    #     + one 10 Hz tick at its 0.3 m/s max_speed (excavator.yaml:4)  0.030 m
    #     + coast v^2/2a at max_linear_acceleration 0.3 m/s^2
    #       (excavator/model.sdf:518)                                   0.150 m
    #   this hauler's travel past the stop decision          0.307 m
    #     one 10 Hz tick at 0.4 m/s (hauler.yaml:4)                     0.040 m
    #     + coast 0.4^2/(2*0.3) (hauler/model.sdf:420)                  0.267 m
    #                                                        -------
    #                                                        2.656 m
    #
    # plus HTNPlanner.HAUL_PICKUP_OFFSET_M (1.2 m), because the planner's
    # pickup is offset from the site and this radius is measured from the
    # PICKUP: approached from the far side, the stopping sphere passes within
    # |standoff - offset| of the site. 2.656 + 1.2 = 3.856 m required.
    #
    # 4.5 m leaves 0.64 m of clear air between the two footprints in the worst
    # composition, and 1.84 m for an operator-injected haul (no planner
    # offset). test_haul_pickup_standoff.py re-derives all of it, reading the
    # planner's constant out of htn_planner.py so the two cannot drift apart
    # in silence.
    #
    # ARITHMETIC, NOT A MEASUREMENT. The tick and coast terms are computed
    # from the configured rates and the plugin's declared acceleration limit;
    # no stopping distance was timed on a running system, and note that the
    # SAME plugin silently ignores <cmd_timeout> (hauler/model.sdf:424-437),
    # so a declared element being honoured is not something to assume.
    #
    # COSTS NOTHING IN MATERIAL. bin_load_node subscribes to
    # `actuators/load_cmd` and to no odometry at all: the bin fills on command
    # wherever the hauler stands, so stopping short changes no mass, no
    # MaterialEvent and no ledger entry.
    PICKUP_STANDOFF_M = 4.5

    # Fill fractions. FULL_THRESHOLD is the unconstrained stop condition (the
    # authorised mass is the bin's own capacity). EMPTY_THRESHOLD is only the
    # COARSE half of the unload stop condition -- see EMPTY_MASS_KG.
    FULL_THRESHOLD = 0.99
    EMPTY_THRESHOLD = 0.02

    # The unload stop condition is ALSO bounded in absolute kilograms, because
    # the number it produces is judged in kilograms: the orchestrator raises a
    # WARNING alert when `abs(residual_mass_kg) > material_residual_tolerance_kg`
    # (orchestrator_node.py:783, default 0.5 in orchestrator_params.yaml:65).
    # A fraction cannot be compared against that without the capacity, and the
    # two do not agree here -- EMPTY_THRESHOLD of the transport bin's 50 kg
    # (selene_hal/config/hauler.yaml:29) is 1.0 kg, twice the tolerance. So a
    # bin this skill called empty reported a residual that tripped a false
    # FR-ISRU-2 instrument-disagreement alert, and delivered_kg (a delta
    # against that reading) was short by the same mass. ExcavateSkill's 20 kg
    # hopper takes the same 0.02 to 0.4 kg and stays inside the tolerance;
    # that is arithmetic on two capacities rather than a shared property,
    # which is why test_haul_against_fill_model.py asserts both.
    #
    # 0.1 kg is 5x inside the tolerance and below one drain sample: the bin
    # drains at transfer_rate 10 kg/s (hauler.yaml:43) and bin_load_node
    # publishes at update_rate 10 Hz (its own default, and what
    # spawn_robot.launch.py:66 passes), so the level steps down 1.0 kg at a
    # time and the skill now waits for the sample that reads a genuinely empty
    # bin instead of stopping on the last non-empty one. ARITHMETIC FROM THE
    # CONFIGURED RATES and from a co-simulation of the real FillModel against
    # the real skill (test_haul_against_fill_model.py) -- not observed on a
    # running system.
    EMPTY_MASS_KG = 0.1

    # Settle detection. A transfer is also considered finished when the load
    # cell stops moving: LEVEL_EPSILON is the largest change still counted as
    # "no change", and SETTLE_TICKS consecutive such updates end the phase.
    LEVEL_EPSILON = 1e-4
    SETTLE_TICKS = 5

    # Settle detection is armed only after this many seconds in the phase.
    # Without it the very first updates -- taken before the load command has
    # crossed DDS and the sim node has published a single new sample -- read
    # an unchanging 0.0 and would end the phase reporting a 0 kg transfer. At
    # the agent's 10 Hz tick SETTLE_TICKS alone is 0.5 s, which is not a safe
    # margin for a command-out/sample-back round trip. ARITHMETIC FROM THE
    # TICK RATE, not a measured latency: no round trip was timed.
    SETTLE_GRACE = 2.0

    def __init__(self):
        super().__init__("haul")
        self._pickup = (0.0, 0.0)
        self._depot = (50.0, 50.0)
        self._quantity_kg = 0.0
        self._phase = HaulPhase.NAVIGATING_TO_PICKUP
        self._phase_timer = 0.0
        self._initial_distance = 1.0
        self._load_triggered = False
        self._unload_triggered = False
        self._mass_on_arrival = 0.0
        self._mass_after_load = 0.0
        self._mass_before_unload = 0.0
        self._loaded_kg = 0.0
        self._delivered_kg = 0.0
        self._residual_mass_kg = 0.0
        self._last_level: Optional[float] = None
        self._settle_ticks = 0
        self._result: Optional[HaulResult] = None
        self._hal = None
        self._navigator = None

    def start(self, hal, navigator, pickup: tuple[float, float] = (0.0, 0.0),
              depot: tuple[float, float] = (50.0, 50.0),
              quantity_kg: float = 0.0, **params) -> None:
        """Begin a haul.

        ``quantity_kg`` is the mass this assignment authorises
        (``TaskAssignment.quantity_kg``), which for a haul is what the
        orchestrator's ledger says is actually waiting at the pickup site.
        0.0 means unconstrained -- fill to the bin's capacity, the behaviour
        every haul had before the field existed. A positive value is clamped
        to the load cell's RCDL ``capacity_kg``
        (``selene_hal/config/hauler.yaml:29``, 50 kg) and passed down to
        ``TransferActuator.trigger_load(max_kg=...)``, so the simulated bin
        can no longer be filled with material no excavator ever extracted.
        """
        self._hal = hal
        self._navigator = navigator
        self._pickup = pickup
        self._depot = depot
        self._phase = HaulPhase.NAVIGATING_TO_PICKUP
        self._state = SkillState.RUNNING
        self._progress = 0.0
        self._phase_timer = 0.0
        self._load_triggered = False
        self._unload_triggered = False
        self._mass_on_arrival = 0.0
        self._mass_after_load = 0.0
        self._mass_before_unload = 0.0
        self._loaded_kg = 0.0
        self._delivered_kg = 0.0
        self._residual_mass_kg = 0.0
        self._last_level = None
        self._settle_ticks = 0
        self._result = None
        self._quantity_kg = self._clamp_quantity(quantity_kg)

        result = navigator.plan_to(pickup)
        if not result.success:
            self._state = SkillState.FAILED
            self._error_message = (
                f"Cannot plan path to pickup {pickup}: {result.failure_reason}"
            )
            return

        self._initial_distance = max(navigator.get_distance_to_goal(), 1.0)
        navigator.start_following(result.path)

    # -------------------------------------------------------------------
    # HAL reads
    # -------------------------------------------------------------------

    def _clamp_quantity(self, quantity_kg) -> float:
        """Clamp an authorised mass to the bin's RCDL capacity.

        Returns 0.0 (unconstrained) for a missing, negative or non-finite
        request. The capacity comes from the load cell's ``SensorConfig``,
        populated by the HAL from ``capacity_kg`` in the RCDL -- the single
        source of truth for this number (contract §3). If the HAL does not
        expose it the request is honoured unclamped; the sim node caps the
        fill at its own capacity regardless.
        """
        try:
            requested = float(quantity_kg)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(requested) or requested <= 0.0:
            return 0.0

        capacity = 0.0
        try:
            config = self._hal.get_sensor("load_cell").get_config()
            capacity = float(getattr(config, 'extra', {}).get('capacity_kg', 0.0))
        except (KeyError, AttributeError, TypeError, ValueError):
            capacity = 0.0
        if math.isfinite(capacity) and capacity > 0.0:
            return min(requested, capacity)
        return requested

    def _read_fill(self) -> tuple[bool, float, float]:
        """Read the load cell as ``(is_valid, level, mass_kg)``.

        ``level`` is the documented 0.0-1.0 fraction of the RCDL capacity;
        ``mass_kg`` is the HAL-derived mass. An unreadable or invalid sensor
        yields ``mass_kg = NaN`` so every mass derived from it is NaN too and
        reaches agent_node as "not measured" rather than as zero. ``level``
        is still returned for progress reporting, but callers must gate any
        threshold decision on ``is_valid``.
        """
        try:
            reading = self._hal.get_sensor("load_cell").read()
        except (KeyError, AttributeError):
            return False, 0.0, float('nan')
        level = float(getattr(reading, 'level', 0.0) or 0.0)
        if not getattr(reading, 'is_valid', False):
            return False, level, float('nan')
        return True, level, float(getattr(reading, 'mass_kg', 0.0) or 0.0)

    def _settled(self, valid: bool, level: float) -> bool:
        """True once the load cell has stopped moving for SETTLE_TICKS.

        Only armed after SETTLE_GRACE seconds in the current phase (see the
        constant). An invalid reading resets the counter: a sensor that is
        not reporting is not the same as a transfer that has finished.
        """
        if not valid:
            self._settle_ticks = 0
            self._last_level = None
            return False
        previous = self._last_level
        self._last_level = level
        if previous is None or abs(level - previous) > self.LEVEL_EPSILON:
            self._settle_ticks = 0
            return False
        self._settle_ticks += 1
        return (
            self._phase_timer >= self.SETTLE_GRACE
            and self._settle_ticks >= self.SETTLE_TICKS
        )

    def _enter_transfer_phase(self, phase: HaulPhase) -> None:
        """Reset the per-phase timers and settle detector."""
        self._phase = phase
        self._phase_timer = 0.0
        self._last_level = None
        self._settle_ticks = 0

    # -------------------------------------------------------------------
    # Tick
    # -------------------------------------------------------------------

    def update(self, dt: float) -> None:
        if self._state != SkillState.RUNNING:
            return

        if self._phase == HaulPhase.NAVIGATING_TO_PICKUP:
            self._update_navigating_to_pickup(dt)
        elif self._phase == HaulPhase.LOADING:
            self._update_loading(dt)
        elif self._phase == HaulPhase.NAVIGATING_TO_DEPOT:
            self._update_navigating_to_depot(dt)
        elif self._phase == HaulPhase.UNLOADING:
            self._update_unloading(dt)

    def _update_navigating_to_pickup(self, dt: float) -> None:
        nav_status = self._navigator.update(dt)
        dist = self._navigator.get_distance_to_goal()
        self._progress = max(0.0, 0.25 * (1.0 - dist / self._initial_distance))

        # PICKUP_STANDOFF_M is the arrival condition; "goal_reached" is kept as
        # a fallback and is normally unreachable on this leg, because the
        # navigator only reports it inside waypoint_tolerance (1.0 m), well
        # inside the standoff. It stays because this skill does not own the
        # navigator's arrival rule and must not fail if that rule changes.
        #
        # A hauler that is ALREADY inside the standoff when the task starts
        # stops where it is and loads from there. That is deliberate: it has
        # not driven anywhere, so it cannot have driven into anything, and
        # backing off to the exact radius would be motion undertaken purely to
        # satisfy an inequality.
        if nav_status == "goal_reached" or dist <= self.PICKUP_STANDOFF_M:
            self._arrive_at_pickup()
        elif nav_status == "blocked":
            self._state = SkillState.FAILED
            self._error_message = "Path blocked on route to pickup"

    def _arrive_at_pickup(self) -> None:
        """Stop short of the pickup and begin LOADING.

        ``navigator.stop()`` as well as ``drive.stop()``: on this path the
        navigator has NOT reached its own goal, so its status is still
        NAVIGATING and its follower still holds the remainder of the path.
        Clearing it is what stops a later ``update()`` from resuming the drive
        toward the coordinate this standoff exists to keep the robot off.
        """
        self._enter_transfer_phase(HaulPhase.LOADING)
        self._load_triggered = False
        # Unguarded, like ``abort()``'s call to the same method: a navigator
        # without ``stop()`` is a broken navigator, and swallowing that here
        # would leave the robot creeping toward the pickup with no error.
        self._navigator.stop()
        self._hal.get_actuator("drive").stop()

    def _update_loading(self, dt: float) -> None:
        self._phase_timer += dt

        if not self._load_triggered:
            # Baseline BEFORE the actuator is triggered, so a bin that
            # arrived with residue is not credited to this pickup.
            _v, _lvl, self._mass_on_arrival = self._read_fill()
            self._load_triggered = True
            self._hal.get_actuator("transport_bin").trigger_load(
                max_kg=self._quantity_kg if self._quantity_kg > 0.0 else -1.0
            )

        valid, level, current_mass = self._read_fill()
        loaded = current_mass - self._mass_on_arrival

        # "Reaches the authorised fraction" is evaluated in KILOGRAMS: the
        # fraction alone cannot be compared against a kg quota without the
        # capacity, and kilograms are what the ledger records. An unreadable
        # sensor makes `loaded` NaN, every comparison False, and the phase
        # falls through to LOAD_TIMEOUT -- which is a failure, correctly, and
        # not a silent zero-kilogram success.
        quota_met = (
            self._quantity_kg > 0.0
            and math.isfinite(loaded)
            and loaded >= self._quantity_kg
        )
        bin_full = valid and level >= self.FULL_THRESHOLD

        if quota_met or bin_full or self._settled(valid, level):
            self._loaded_kg = loaded
            self._mass_after_load = current_mass
            self._progress = 0.5

            # Plan path to depot
            result = self._navigator.plan_to(self._depot)
            if not result.success:
                self._state = SkillState.FAILED
                self._error_message = (
                    f"Cannot plan to depot: {result.failure_reason}"
                )
                return

            self._initial_distance = max(
                self._navigator.get_distance_to_goal(), 1.0
            )
            self._navigator.start_following(result.path)
            self._phase = HaulPhase.NAVIGATING_TO_DEPOT
            return

        # Progress 25-50% based on timeout
        load_frac = min(self._phase_timer / self.LOAD_TIMEOUT, 1.0)
        self._progress = max(0.0, 0.25 + 0.25 * load_frac)

        if self._phase_timer >= self.LOAD_TIMEOUT:
            self._state = SkillState.FAILED
            self._error_message = "Loading timed out"

    def _update_navigating_to_depot(self, dt: float) -> None:
        nav_status = self._navigator.update(dt)
        dist = self._navigator.get_distance_to_goal()
        self._progress = max(
            0.0, 0.5 + 0.25 * (1.0 - dist / self._initial_distance)
        )

        if nav_status == "goal_reached":
            self._enter_transfer_phase(HaulPhase.UNLOADING)
            self._unload_triggered = False
            self._hal.get_actuator("drive").stop()
        elif nav_status == "blocked":
            self._state = SkillState.FAILED
            self._error_message = "Path blocked on route to depot"

    def _update_unloading(self, dt: float) -> None:
        self._phase_timer += dt

        if not self._unload_triggered:
            # Baseline BEFORE the dump. delivered_kg is this minus whatever
            # is left afterwards, which is a different measurement from
            # loaded_kg: material can be lost in transit, and the ledger's
            # in_transit term only closes if both are reported.
            _v, _lvl, self._mass_before_unload = self._read_fill()
            self._unload_triggered = True
            self._hal.get_actuator("transport_bin").trigger_unload()

        valid, level, current_mass = self._read_fill()

        # Empty in BOTH units. The kilogram gate is what keeps the residual
        # this skill reports inside the orchestrator's tolerance; the fraction
        # gate stays because mass_kg is a HAL DERIVATION of level, and a
        # sensor whose RCDL declares no usable capacity_kg reports
        # mass_kg = 0.0 for the life of the process (the "loud zero" of
        # gazebo_hal.py:267-294). A kilogram-only test would read that as an
        # empty bin on the first tick of the dump and complete the haul
        # without ever waiting for the transfer.
        #
        # A bin that does NOT drain is still caught by _settled below, which
        # ends the phase on an unchanging level and reports the full residual
        # -- the orchestrator alert then fires on a real fault, which is the
        # case it was written for.
        emptied = (
            valid
            and level <= self.EMPTY_THRESHOLD
            and current_mass <= self.EMPTY_MASS_KG
        )
        if emptied or self._settled(valid, level):
            self._delivered_kg = self._mass_before_unload - current_mass
            self._residual_mass_kg = current_mass
            self._state = SkillState.COMPLETE
            self._progress = 1.0
            self._result = HaulResult(
                pickup_position=self._pickup,
                depot_position=self._depot,
                loaded_kg=self._loaded_kg,
                bin_mass_after_load_kg=self._mass_after_load,
                delivered_kg=self._delivered_kg,
                residual_mass_kg=self._residual_mass_kg,
                timestamp=time.time(),
            )
            return

        # Progress 75-100% based on timeout
        unload_frac = min(self._phase_timer / self.UNLOAD_TIMEOUT, 1.0)
        self._progress = max(0.0, 0.75 + 0.25 * unload_frac)

        if self._phase_timer >= self.UNLOAD_TIMEOUT:
            self._state = SkillState.FAILED
            self._error_message = "Unloading timed out"

    def get_result(self) -> Optional[HaulResult]:
        return self._result

    def abort(self) -> None:
        if self._hal:
            try:
                self._hal.get_actuator("transport_bin").cancel_transfer()
            except (KeyError, AttributeError):
                pass
            try:
                self._hal.get_actuator("drive").stop()
            except (KeyError, AttributeError):
                pass
        if self._navigator:
            self._navigator.stop()
        self._state = SkillState.ABORTED
