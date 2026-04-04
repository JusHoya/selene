"""Gazebo HAL implementation — bridges Gazebo Harmonic simulation topics
to the abstract HAL interfaces via ROS 2 subscriptions and publishers.

Thread-safe cached-read model: ROS callbacks update cached values under
locks; read() returns the latest cache. Publishers send commands directly.
"""

import math
import threading

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

import rclpy
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
    """Subscribes to a std_msgs/Float32 topic and caches the latest value."""

    def __init__(self, config: SensorConfig, node, qos):
        self._config = config
        self._active = True
        self._lock = threading.Lock()
        self._cached = ScalarFieldReading(
            sensor_name=config.name, is_valid=False,
        )
        self._sub = node.create_subscription(
            Float32, config.topic, self._cb, qos,
        )

    def _cb(self, msg: Float32) -> None:
        reading = ScalarFieldReading(
            sensor_name=self._config.name,
            is_valid=self._active,
            value=msg.data,
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
    """Subscribes to std_msgs/Float32 representing fill fraction."""

    def __init__(self, config: SensorConfig, node, qos):
        self._config = config
        self._active = True
        self._lock = threading.Lock()
        self._cached = FillLevelReading(
            sensor_name=config.name, is_valid=False,
        )
        self._sub = node.create_subscription(
            Float32, config.topic, self._cb, qos,
        )

    def _cb(self, msg: Float32) -> None:
        reading = FillLevelReading(
            sensor_name=self._config.name,
            is_valid=self._active,
            level=msg.data,
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
    """Subscribes to nav_msgs/Odometry and converts to HAL OdometryReading."""

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
    """Publishes std_msgs/String ("load"/"unload"/"stop") to a transfer topic."""

    def __init__(self, config: ActuatorConfig, node):
        self._config = config
        self._active = True
        self._complete = True
        self._pub = node.create_publisher(String, config.topic, 10)

    def trigger_load(self) -> None:
        self._complete = False
        msg = String()
        msg.data = "load"
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
        self._cached = BatteryState(
            capacity_wh=descriptor.battery.capacity,
            remaining_wh=descriptor.battery.capacity,
        )
        topic = f"/{robot_id}/battery_state"
        self._sub = node.create_subscription(
            RosBatteryState, topic, self._cb, qos,
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
        )
        with self._lock:
            self._cached = state

    def get_state(self) -> BatteryState:
        with self._lock:
            return self._cached

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
