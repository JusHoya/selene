"""Gazebo HAL implementation — bridges Gazebo Harmonic simulation topics
to the abstract HAL interfaces via ROS 2 subscriptions and publishers.

Thread-safe cached-read model: ROS callbacks update cached values under
locks; read() returns the latest cache. Publishers send commands directly.
"""

import math
import threading
import time

import numpy as np

from selene_hal.hal_interface import HalInterface
from selene_hal.sensor_interface import (
    SensorInterface, SensorConfig, ScalarFieldSensor, DepthImageSensor,
    IMUSensor, FillLevelSensor, OdometrySensor,
)
from selene_hal.actuator_interface import (
    ActuatorInterface, ActuatorConfig, DriveActuator, DrillActuator,
    TransferActuator,
)
from selene_hal.battery_interface import BatteryInterface
from selene_hal.kinematics_interface import KinematicsInterface
from selene_hal.data_types import (
    SensorType, ActuatorType, ScalarFieldReading, DepthImageReading,
    IMUReading, FillLevelReading, OdometryReading, BatteryState,
    ActuatorState, Timestamp,
)
from selene_hal.robot_descriptor import RobotDescriptor
from selene_hal.hal_factory import register_hal_backend

from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from std_msgs.msg import Float32, Bool, String
from sensor_msgs.msg import Image, Imu, BatteryState as RosBatteryState
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist

# QoS profile for sensor subscriptions — best-effort / volatile to match
# typical Gazebo publishers that use best-effort transport.
_SENSOR_QOS = QoSProfile(
    depth=5,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
)


def _stamp_to_ts(stamp) -> Timestamp:
    """Convert a ROS builtin_interfaces/Time to HAL Timestamp."""
    return Timestamp(sec=stamp.sec, nanosec=stamp.nanosec)


# ---------------------------------------------------------------------------
# Sensor implementations
# ---------------------------------------------------------------------------

class GazeboScalarFieldSensor(ScalarFieldSensor):
    """Subscribes to a std_msgs/Float32 topic and caches the latest value.

    The Gazebo sensor bridge carries only the scalar value, so the
    measurement uncertainty is taken from the RCDL descriptor's
    ``noise_stddev`` (plumbed through ``SensorConfig.extra``). Leaving it at
    the dataclass default of 0.0 claims a noise-free instrument and collapses
    the orchestrator's Bayesian resource-map update to last-sample-wins
    (``ResourceMap.update`` floors sensor variance at 1e-6).

    Caveat, stated plainly: ``noise_stddev`` is a single static figure. The
    simulated neutron spectrometer
    (``selene_sim/selene_sim/neutron_spectrometer_node.py``) applies
    distance-dependent noise, ``noise_base_stddev + coeff * distance``, which
    can exceed the declared constant. This HAL does not model that
    dependence, so the reported sigma is the declared nominal, not a
    per-sample estimate. Not yet validated against simulation.
    """

    def __init__(self, config: SensorConfig, node, qos):
        self._config = config
        self._active = True
        self._lock = threading.Lock()
        self._noise_stddev = self._resolve_noise_stddev(config, node)
        self._cached = ScalarFieldReading(
            sensor_name=config.name, is_valid=False,
        )
        self._sub = node.create_subscription(
            Float32, config.topic, self._cb, qos,
        )

    @staticmethod
    def _resolve_noise_stddev(config: SensorConfig, node) -> float:
        """Return the RCDL-declared sigma, or 0.0 if none was declared.

        A missing / non-positive / non-finite declaration is logged loudly,
        because 0.0 means downstream consumers will treat this sensor as
        exact.
        """
        raw = getattr(config, "extra", {}).get("noise_stddev")
        try:
            sigma = float(raw)
        except (TypeError, ValueError):
            sigma = 0.0
        if not math.isfinite(sigma) or sigma <= 0.0:
            try:
                node.get_logger().warn(
                    f"Sensor '{config.name}' declares no usable noise_stddev "
                    f"in its RCDL descriptor (got {raw!r}); readings will "
                    f"report uncertainty 0.0 and any Bayesian consumer will "
                    f"treat them as noise-free."
                )
            except AttributeError:  # pragma: no cover - node without logger
                pass
            return 0.0
        return sigma

    def _cb(self, msg: Float32) -> None:
        reading = ScalarFieldReading(
            sensor_name=self._config.name,
            is_valid=self._active,
            value=msg.data,
            uncertainty=self._noise_stddev,
        )
        with self._lock:
            self._cached = reading

    def read(self) -> ScalarFieldReading:
        with self._lock:
            return self._cached

    def get_config(self) -> SensorConfig:
        return self._config

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class GazeboDepthImageSensor(DepthImageSensor):
    """Subscribes to a sensor_msgs/Image topic carrying depth data."""

    def __init__(self, config: SensorConfig, node, qos):
        self._config = config
        self._active = True
        self._lock = threading.Lock()
        self._cached = DepthImageReading(
            sensor_name=config.name, is_valid=False,
        )
        self._sub = node.create_subscription(
            Image, config.topic, self._cb, qos,
        )

    def _cb(self, msg: Image) -> None:
        # Handle both 32FC1 (float32) and 16UC1 (uint16) depth encodings.
        if msg.encoding in ("32FC1", "float32"):
            image = np.frombuffer(msg.data, dtype=np.float32).reshape(
                (msg.height, msg.width),
            )
        elif msg.encoding in ("16UC1", "mono16"):
            image = np.frombuffer(msg.data, dtype=np.uint16).reshape(
                (msg.height, msg.width),
            ).astype(np.float32) / 1000.0  # mm -> m
        else:
            # Fallback: try float32 interpretation
            image = np.frombuffer(msg.data, dtype=np.float32).reshape(
                (msg.height, msg.width),
            )

        reading = DepthImageReading(
            timestamp=_stamp_to_ts(msg.header.stamp),
            sensor_name=self._config.name,
            is_valid=self._active,
            image=image,
        )
        with self._lock:
            self._cached = reading

    def read(self) -> DepthImageReading:
        with self._lock:
            return self._cached

    def get_config(self) -> SensorConfig:
        return self._config

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class GazeboIMUSensor(IMUSensor):
    """Subscribes to sensor_msgs/Imu."""

    def __init__(self, config: SensorConfig, node, qos):
        self._config = config
        self._active = True
        self._lock = threading.Lock()
        self._cached = IMUReading(
            sensor_name=config.name, is_valid=False,
        )
        self._sub = node.create_subscription(
            Imu, config.topic, self._cb, qos,
        )

    def _cb(self, msg: Imu) -> None:
        o = msg.orientation
        av = msg.angular_velocity
        la = msg.linear_acceleration
        reading = IMUReading(
            timestamp=_stamp_to_ts(msg.header.stamp),
            sensor_name=self._config.name,
            is_valid=self._active,
            orientation_quaternion=(o.x, o.y, o.z, o.w),
            angular_velocity=(av.x, av.y, av.z),
            linear_acceleration=(la.x, la.y, la.z),
        )
        with self._lock:
            self._cached = reading

    def read(self) -> IMUReading:
        with self._lock:
            return self._cached

    def get_config(self) -> SensorConfig:
        return self._config

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class GazeboFillLevelSensor(FillLevelSensor):
    """Subscribes to a std_msgs/Float32 topic carrying a fill FRACTION.

    The wire value is dimensionless 0.0-1.0 (``FillLevelReading.level``). This
    class is the one and only place it is turned into kilograms, using the
    ``capacity_kg`` its RCDL descriptor declares -- ``excavator.yaml:29``
    hopper_fill 20 kg, ``hauler.yaml:29`` load_cell 50 kg -- plumbed through
    ``SensorConfig.extra``. Leaving ``mass_kg`` at the dataclass default of 0.0
    is not a harmless omission: ``ExcavateSkill`` reports its extracted mass as
    the difference of two ``mass_kg`` readings, so an unpopulated field is a
    measured zero rather than a missing measurement (deviation D-06).
    """

    def __init__(self, config: SensorConfig, node, qos):
        self._config = config
        self._active = True
        self._lock = threading.Lock()
        self._capacity_kg = self._resolve_capacity_kg(config, node)
        self._cached = FillLevelReading(
            sensor_name=config.name, is_valid=False,
        )
        self._sub = node.create_subscription(
            Float32, config.topic, self._cb, qos,
        )

    @staticmethod
    def _resolve_capacity_kg(config: SensorConfig, node) -> float:
        """Return the RCDL-declared capacity in kg, or 0.0 if none was declared.

        Mirrors ``GazeboScalarFieldSensor._resolve_noise_stddev``: a missing /
        non-positive / non-finite declaration is logged loudly and degrades to
        0.0, because the alternative -- guessing a capacity -- would fabricate
        masses that the orchestrator's ledger would then treat as measurements.
        A 0.0 capacity makes every ``mass_kg`` zero, which is visible as
        "nothing was extracted" rather than as a plausible wrong number.
        """
        raw = getattr(config, "extra", {}).get("capacity_kg")
        try:
            capacity = float(raw)
        except (TypeError, ValueError):
            capacity = 0.0
        if not math.isfinite(capacity) or capacity <= 0.0:
            try:
                node.get_logger().warn(
                    f"Fill-level sensor '{config.name}' declares no usable "
                    f"capacity_kg in its RCDL descriptor (got {raw!r}); every "
                    f"reading will report mass_kg = 0.0 and any skill that "
                    f"measures a mass delta will record zero."
                )
            except AttributeError:  # pragma: no cover - node without logger
                pass
            return 0.0
        return capacity

    def _cb(self, msg: Float32) -> None:
        level = float(msg.data)
        reading = FillLevelReading(
            sensor_name=self._config.name,
            is_valid=self._active,
            level=level,
            # The single fraction -> kilogram conversion in the system.
            mass_kg=level * self._capacity_kg,
        )
        with self._lock:
            self._cached = reading

    def read(self) -> FillLevelReading:
        with self._lock:
            return self._cached

    def get_config(self) -> SensorConfig:
        return self._config

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class GazeboOdometrySensor(OdometrySensor):
    """Subscribes to nav_msgs/Odometry and converts to HAL OdometryReading.

    THE TOPIC IS WORLD-REFERENCED, AND THIS CLASS APPLIES NO TRANSFORM.

    The RCDLs point this sensor at ``odom_world``
    (``selene_hal/config/*.yaml``), which
    ``selene_sim/selene_sim/world_odometry_node.py`` publishes after composing
    the robot's spawn SE(2) onto Gazebo's dead-reckoned ``odom``. Until
    2026-07-31 it read ``odom`` directly, so ``OdometryReading.x`` / ``.y`` were
    metres from wherever that robot happened to spawn, along an axis pointing
    down its spawn heading -- and every consumer (the navigator, the bid score,
    ``prospect``/``excavate``/``haul``, ``RobotState.pose``) treated them as
    world. Register D-08.

    NO ARITHMETIC HERE, deliberately. The HAL is the hardware-agnostic boundary
    (CLAUDE.md principle 5): on real hardware this pose comes from a
    localisation stack, and an agent that had to know its own spawn pose to
    interpret its odometry would have a simulation artefact wired into the
    autonomy layer. The conversion happens once, in one node, and this class is
    unaware of which producer it is talking to.

    STILL DEAD-RECKONED. World-referenced is not ground truth: the underlying
    integration is still wheel encoders, so this pose advances perfectly while a
    buried robot's wheels spin in solid rock (``scripts/check_drive.sh``). Any
    check that needs the real position must ask Gazebo, not this sensor.
    """

    def __init__(self, config: SensorConfig, node, qos):
        self._config = config
        self._active = True
        self._lock = threading.Lock()
        self._cached = OdometryReading(
            sensor_name=config.name, is_valid=False,
        )
        self._sub = node.create_subscription(
            Odometry, config.topic, self._cb, qos,
        )

    def _cb(self, msg: Odometry) -> None:
        pos = msg.pose.pose.position
        q = msg.pose.pose.orientation
        # Yaw from quaternion (ZYX convention)
        theta = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        reading = OdometryReading(
            timestamp=_stamp_to_ts(msg.header.stamp),
            sensor_name=self._config.name,
            is_valid=self._active,
            x=pos.x,
            y=pos.y,
            theta=theta,
            linear_velocity=msg.twist.twist.linear.x,
            angular_velocity=msg.twist.twist.angular.z,
        )
        with self._lock:
            self._cached = reading

    def read(self) -> OdometryReading:
        with self._lock:
            return self._cached

    def get_config(self) -> SensorConfig:
        return self._config

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


# ---------------------------------------------------------------------------
# Actuator implementations
# ---------------------------------------------------------------------------

class GazeboDriveActuator(DriveActuator):
    """Publishes geometry_msgs/Twist to cmd_vel."""

    def __init__(self, config: ActuatorConfig, node):
        self._config = config
        self._active = True
        self._pub = node.create_publisher(Twist, config.topic, 10)

    def command_velocity(self, linear_x: float, angular_z: float) -> None:
        msg = Twist()
        msg.linear.x = float(linear_x)
        msg.angular.z = float(angular_z)
        self._pub.publish(msg)

    def stop(self) -> None:
        self.command_velocity(0.0, 0.0)

    def get_config(self) -> ActuatorConfig:
        return self._config

    def get_state(self) -> ActuatorState:
        return ActuatorState(
            actuator_name=self._config.name, is_active=self._active,
        )

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class GazeboDrillActuator(DrillActuator):
    """Publishes std_msgs/Bool to drill_cmd (True=on, False=off)."""

    def __init__(self, config: ActuatorConfig, node):
        self._config = config
        self._active = False
        self._drilling = False
        self._power = 0.0
        self._pub = node.create_publisher(Bool, config.topic, 10)

    def set_power_level(self, level: float) -> None:
        self._power = max(0.0, min(1.0, level))

    def start_drilling(self) -> None:
        self._drilling = True
        msg = Bool()
        msg.data = True
        self._pub.publish(msg)

    def stop_drilling(self) -> None:
        self._drilling = False
        msg = Bool()
        msg.data = False
        self._pub.publish(msg)

    def is_drilling(self) -> bool:
        return self._drilling

    def get_config(self) -> ActuatorConfig:
        return self._config

    def get_state(self) -> ActuatorState:
        return ActuatorState(
            actuator_name=self._config.name,
            is_active=self._drilling,
            power_level=self._power,
        )

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False
        self.stop_drilling()


class GazeboTransferActuator(TransferActuator):
    """Publishes std_msgs/String to a transfer topic.

    Payloads: ``"load"`` | ``"load:<kg>"`` | ``"unload"`` | ``"stop"``. The
    bare ``"load"`` spelling is kept so an unpatched caller still works; with a
    bound it becomes ``load:<kg>``, where ``<kg>`` is the ABSOLUTE mass to fill
    to, not an increment. ``selene_sim/selene_sim/bin_load_node.py`` parses
    both.

    ``is_transfer_complete()`` NEVER BECOMES TRUE ON THIS BACKEND AFTER A
    TRIGGER. This is a static observation of the code below, not something
    observed on a running system: ``_complete`` is set ``True`` only in
    ``__init__`` and in ``cancel_transfer``; ``trigger_load`` and
    ``trigger_unload`` set it ``False``; nothing else assigns it, because
    nothing subscribes to any completion signal from the simulation. Callers
    must therefore observe completion from the FILL SENSOR -- the load cell or
    hopper level settling -- and not from this method. ``HaulSkill`` gated on
    it until 2026-07-30, which under this backend means every haul would sit in
    LOADING until ``LOAD_TIMEOUT``; the stub HAL hid it by returning ``True``
    unconditionally. Removing the flag outright is a wider interface change
    than deviation D-06 covers, so it is recorded here instead.
    """

    def __init__(self, config: ActuatorConfig, node):
        self._config = config
        self._active = True
        self._complete = True
        self._pub = node.create_publisher(String, config.topic, 10)

    def trigger_load(self, max_kg: float = -1.0) -> None:
        self._complete = False
        msg = String()
        # Negative means unbounded: fill to the container's RCDL capacity_kg,
        # which is what the bare command has always meant.
        msg.data = "load" if max_kg < 0.0 else f"load:{max_kg:.3f}"
        self._pub.publish(msg)

    def trigger_unload(self) -> None:
        self._complete = False
        msg = String()
        msg.data = "unload"
        self._pub.publish(msg)

    def is_transfer_complete(self) -> bool:
        return self._complete

    def cancel_transfer(self) -> None:
        self._complete = True
        msg = String()
        msg.data = "stop"
        self._pub.publish(msg)

    def get_config(self) -> ActuatorConfig:
        return self._config

    def get_state(self) -> ActuatorState:
        return ActuatorState(
            actuator_name=self._config.name, is_active=self._active,
        )

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------

class GazeboBattery(BatteryInterface):
    """Subscribes to sensor_msgs/BatteryState and caches HAL BatteryState."""

    def __init__(self, descriptor: RobotDescriptor, robot_id: str, node, qos):
        self._desc = descriptor
        self._lock = threading.Lock()
        # is_valid=False: NOTHING HAS ARRIVED YET, and this object must be able
        # to say so. The capacity numbers are real (they come from the RCDL) and
        # charge_fraction stays at the dataclass default 1.0, so a consumer that
        # ignores the flag sees exactly the pre-D-42 behaviour. Register D-42.
        self._cached = BatteryState(
            capacity_wh=descriptor.battery.capacity,
            remaining_wh=descriptor.battery.capacity,
            is_valid=False,
        )
        self._topic = f"/{robot_id}/battery_state"
        self._node = node
        self._msg_count = 0
        self._last_rx_monotonic: float | None = None
        self._sub = node.create_subscription(
            RosBatteryState, self._topic, self._cb, qos,
        )

    def _cb(self, msg: RosBatteryState) -> None:
        capacity = self._desc.battery.capacity
        charge_fraction = msg.percentage  # 0.0 - 1.0
        remaining = charge_fraction * capacity
        state = BatteryState(
            timestamp=_stamp_to_ts(msg.header.stamp),
            charge_fraction=charge_fraction,
            voltage=msg.voltage,
            current_draw=msg.current,
            capacity_wh=capacity,
            remaining_wh=remaining,
            is_charging=(msg.power_supply_status
                         == RosBatteryState.POWER_SUPPLY_STATUS_CHARGING),
            is_valid=True,
        )
        with self._lock:
            self._cached = state
            self._msg_count += 1
            self._last_rx_monotonic = time.monotonic()

    def get_state(self) -> BatteryState:
        with self._lock:
            return self._cached

    # ---- D-42 instrumentation. ----
    #
    # THIS IS THE OBSERVATION D-42 SAID IT NEEDED: "a live probe of
    # /<rid>/battery_state -- its rate, its percentage field, and whether the
    # value the HAL caches matches what the node publishes". Two of those three
    # are answerable from inside the HAL and are exposed here; the third is a
    # comparison the agent makes.
    #
    # publisher_count() exists because the topic is not guaranteed to have ONE
    # publisher. Measured on 2026-08-01: signalling `ros2 launch` left a complete
    # SELENE stack -- gz sim, four battery_nodes, four agents, an orchestrator
    # and rosbridge -- alive, and a second launch then put TWO battery_nodes on
    # this topic. An orphaned battery_node latches its last cmd_vel forever
    # (battery_node.py:121-122 assigns on message and nothing decays it), so with
    # the simulator gone it keeps integrating locomotion draw at that speed,
    # crosses zero, and is clamped by `max(0.0, ...)` at battery_node.py:182 to
    # EXACTLY 0.0 -- which it then publishes at 10 Hz for as long as it lives.
    # `_cb` above takes whichever message arrived last with no notion of source,
    # so the cache flips between the healthy node's value and the orphan's zero.
    #
    # The HAL does not act on any of this. It reports; the agent decides.

    def message_count(self) -> int:
        """How many battery messages this HAL has received, ever."""
        with self._lock:
            return self._msg_count

    def seconds_since_last_message(self) -> float | None:
        """Monotonic seconds since the last battery message, or None if never."""
        with self._lock:
            if self._last_rx_monotonic is None:
                return None
            return time.monotonic() - self._last_rx_monotonic

    def publisher_count(self) -> int:
        """Live count of publishers on this robot's battery topic.

        More than one means something outside this stack is asserting this
        robot's charge. Exactly zero means the simulator's battery node is not
        running -- which is survivable and silent today, because the cached
        state simply stops changing.
        """
        try:
            return self._node.count_publishers(self._topic)
        except Exception:      # pragma: no cover - rclpy teardown races
            return -1

    def topic(self) -> str:
        return self._topic

    def get_capacity_wh(self) -> float:
        return self._desc.battery.capacity

    def get_idle_draw_w(self) -> float:
        return self._desc.battery.idle_draw

    def get_locomotion_draw_w(self) -> float:
        return self._desc.battery.locomotion_draw


# ---------------------------------------------------------------------------
# Kinematics (identical to StubKinematics — pure descriptor, no ROS)
# ---------------------------------------------------------------------------

class GazeboKinematics(KinematicsInterface):
    def __init__(self, descriptor: RobotDescriptor):
        self._desc = descriptor

    def get_max_speed(self) -> float:
        return self._desc.max_speed

    def get_turn_radius(self) -> float:
        return self._desc.turn_radius

    def get_kinematic_model(self) -> str:
        return self._desc.kinematic_model

    def get_mass(self) -> float:
        return self._desc.mass


# ---------------------------------------------------------------------------
# Sensor / actuator type -> class mapping
# ---------------------------------------------------------------------------

_GAZEBO_SENSOR_MAP = {
    SensorType.SCALAR_FIELD: GazeboScalarFieldSensor,
    SensorType.DEPTH_IMAGE: GazeboDepthImageSensor,
    SensorType.IMU: GazeboIMUSensor,
    SensorType.FILL_LEVEL: GazeboFillLevelSensor,
    SensorType.ODOMETRY: GazeboOdometrySensor,
}

_GAZEBO_ACTUATOR_MAP = {
    ActuatorType.DRILL: GazeboDrillActuator,
    ActuatorType.TRANSFER: GazeboTransferActuator,
}


# ---------------------------------------------------------------------------
# Main GazeboHal class
# ---------------------------------------------------------------------------

class GazeboHal(HalInterface):
    """Gazebo Harmonic HAL driver.

    Bridges Gazebo simulation topics to the abstract HAL interfaces using
    ROS 2 subscriptions (sensors, battery) and publishers (actuators).
    """

    def __init__(self, descriptor: RobotDescriptor, robot_id: str,
                 ros_node=None):
        if ros_node is None:
            raise ValueError(
                "GazeboHal requires a live rclpy.Node (ros_node)")
        self._descriptor = descriptor
        self._robot_id = robot_id
        self._node = ros_node

        # -- Sensors --
        self._sensors: dict[str, SensorInterface] = {}
        for sd in descriptor.sensors:
            config = SensorConfig(
                name=sd.name,
                sensor_type=SensorType(sd.type.value),
                topic=f"/{robot_id}/{sd.topic}",
                power_draw=sd.power_draw,
                # Forwarded via SensorConfig.extra so scalar-field sensors can
                # report a real measurement sigma instead of 0.0.
                noise_stddev=sd.noise_stddev,
                # Likewise for fill-level sensors: the RCDL is the single
                # source of truth for how many kilograms a full container
                # holds, and this is the only route by which the HAL learns it.
                capacity_kg=sd.capacity_kg,
            )
            sensor_cls = _GAZEBO_SENSOR_MAP.get(SensorType(sd.type.value))
            if sensor_cls:
                self._sensors[sd.name] = sensor_cls(
                    config, self._node, _SENSOR_QOS,
                )

        # -- Actuators (+ implicit drive) --
        self._actuators: dict[str, ActuatorInterface] = {}
        drive_config = ActuatorConfig(
            name="drive",
            actuator_type=ActuatorType.DRIVE,
            topic=f"/{robot_id}/cmd_vel",
        )
        self._actuators["drive"] = GazeboDriveActuator(
            drive_config, self._node,
        )

        for ad in descriptor.actuators:
            config = ActuatorConfig(
                name=ad.name,
                actuator_type=ActuatorType(ad.type.value),
                topic=f"/{robot_id}/{ad.topic}",
                power_draw=ad.power_draw,
            )
            actuator_cls = _GAZEBO_ACTUATOR_MAP.get(
                ActuatorType(ad.type.value),
            )
            if actuator_cls:
                self._actuators[ad.name] = actuator_cls(
                    config, self._node,
                )

        # -- Battery --
        self._battery = GazeboBattery(
            descriptor, robot_id, self._node, _SENSOR_QOS,
        )

        # -- Kinematics --
        self._kinematics = GazeboKinematics(descriptor)

    # -- HalInterface implementation --

    def get_sensor(self, name: str) -> SensorInterface:
        if name not in self._sensors:
            raise KeyError(
                f"No sensor '{name}' on {self._descriptor.robot_type}. "
                f"Available: {list(self._sensors.keys())}")
        return self._sensors[name]

    def get_actuator(self, name: str) -> ActuatorInterface:
        if name not in self._actuators:
            raise KeyError(
                f"No actuator '{name}' on {self._descriptor.robot_type}. "
                f"Available: {list(self._actuators.keys())}")
        return self._actuators[name]

    def get_kinematics(self) -> KinematicsInterface:
        return self._kinematics

    def get_battery(self) -> BatteryInterface:
        return self._battery

    def get_capabilities(self) -> list:
        return list(self._descriptor.capabilities)

    def list_sensors(self) -> list:
        return list(self._sensors.keys())

    def list_actuators(self) -> list:
        return list(self._actuators.keys())

    def shutdown(self) -> None:
        """Stop all actuators and release ROS resources."""
        # Stop drive
        drive = self._actuators.get("drive")
        if drive is not None and isinstance(drive, GazeboDriveActuator):
            drive.stop()

        # Stop any drills
        for act in self._actuators.values():
            if isinstance(act, GazeboDrillActuator) and act.is_drilling():
                act.stop_drilling()

        # Cancel any transfers
        for act in self._actuators.values():
            if isinstance(act, GazeboTransferActuator):
                if not act.is_transfer_complete():
                    act.cancel_transfer()


# Register the Gazebo backend so the factory can instantiate it.
register_hal_backend("gazebo", GazeboHal)
