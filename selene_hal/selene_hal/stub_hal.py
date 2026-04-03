"""Stub HAL implementation for Phase 1 testing.

Returns valid but zeroed/default data for all interfaces.
Allows agent development without a running simulation.
"""

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


class StubScalarFieldSensor(ScalarFieldSensor):
    def __init__(self, config: SensorConfig):
        self._config = config
        self._active = True

    def read(self) -> ScalarFieldReading:
        return ScalarFieldReading(sensor_name=self._config.name, is_valid=self._active)

    def get_config(self) -> SensorConfig:
        return self._config

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class StubDepthImageSensor(DepthImageSensor):
    def __init__(self, config: SensorConfig):
        self._config = config
        self._active = True

    def read(self) -> DepthImageReading:
        return DepthImageReading(sensor_name=self._config.name, is_valid=self._active)

    def get_config(self) -> SensorConfig:
        return self._config

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class StubIMUSensor(IMUSensor):
    def __init__(self, config: SensorConfig):
        self._config = config
        self._active = True

    def read(self) -> IMUReading:
        return IMUReading(sensor_name=self._config.name, is_valid=self._active)

    def get_config(self) -> SensorConfig:
        return self._config

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class StubFillLevelSensor(FillLevelSensor):
    def __init__(self, config: SensorConfig):
        self._config = config
        self._active = True

    def read(self) -> FillLevelReading:
        return FillLevelReading(sensor_name=self._config.name, is_valid=self._active)

    def get_config(self) -> SensorConfig:
        return self._config

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class StubOdometrySensor(OdometrySensor):
    def __init__(self, config: SensorConfig):
        self._config = config
        self._active = True

    def read(self) -> OdometryReading:
        return OdometryReading(sensor_name=self._config.name, is_valid=self._active)

    def get_config(self) -> SensorConfig:
        return self._config

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class StubDriveActuator(DriveActuator):
    def __init__(self, config: ActuatorConfig):
        self._config = config
        self._active = True

    def command_velocity(self, linear_x: float, angular_z: float) -> None:
        pass

    def stop(self) -> None:
        pass

    def get_config(self) -> ActuatorConfig:
        return self._config

    def get_state(self) -> ActuatorState:
        return ActuatorState(actuator_name=self._config.name, is_active=self._active)

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class StubDrillActuator(DrillActuator):
    def __init__(self, config: ActuatorConfig):
        self._config = config
        self._active = False
        self._drilling = False
        self._power = 0.0

    def set_power_level(self, level: float) -> None:
        self._power = max(0.0, min(1.0, level))

    def start_drilling(self) -> None:
        self._drilling = True

    def stop_drilling(self) -> None:
        self._drilling = False

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
        self._drilling = False


class StubTransferActuator(TransferActuator):
    def __init__(self, config: ActuatorConfig):
        self._config = config
        self._active = True
        self._complete = True

    def trigger_load(self) -> None:
        self._complete = True

    def trigger_unload(self) -> None:
        self._complete = True

    def is_transfer_complete(self) -> bool:
        return self._complete

    def cancel_transfer(self) -> None:
        self._complete = True

    def get_config(self) -> ActuatorConfig:
        return self._config

    def get_state(self) -> ActuatorState:
        return ActuatorState(actuator_name=self._config.name, is_active=self._active)

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False


class StubBattery(BatteryInterface):
    def __init__(self, descriptor: RobotDescriptor):
        self._desc = descriptor

    def get_state(self) -> BatteryState:
        return BatteryState(
            capacity_wh=self._desc.battery.capacity,
            remaining_wh=self._desc.battery.capacity,
        )

    def get_capacity_wh(self) -> float:
        return self._desc.battery.capacity

    def get_idle_draw_w(self) -> float:
        return self._desc.battery.idle_draw

    def get_locomotion_draw_w(self) -> float:
        return self._desc.battery.locomotion_draw


class StubKinematics(KinematicsInterface):
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


# Sensor type mapping
_STUB_SENSOR_MAP = {
    SensorType.SCALAR_FIELD: StubScalarFieldSensor,
    SensorType.DEPTH_IMAGE: StubDepthImageSensor,
    SensorType.IMU: StubIMUSensor,
    SensorType.FILL_LEVEL: StubFillLevelSensor,
    SensorType.ODOMETRY: StubOdometrySensor,
}

_STUB_ACTUATOR_MAP = {
    ActuatorType.DRILL: StubDrillActuator,
    ActuatorType.TRANSFER: StubTransferActuator,
}


class StubHal(HalInterface):
    """Stub HAL returning default/zero values for all interfaces."""

    def __init__(self, descriptor: RobotDescriptor, robot_id: str,
                 ros_node=None):
        self._descriptor = descriptor
        self._robot_id = robot_id

        # Create stub sensors
        self._sensors: dict[str, SensorInterface] = {}
        for sd in descriptor.sensors:
            config = SensorConfig(
                name=sd.name,
                sensor_type=SensorType(sd.type.value),
                topic=f"/{robot_id}/{sd.topic}",
                power_draw=sd.power_draw,
            )
            stub_cls = _STUB_SENSOR_MAP.get(SensorType(sd.type.value))
            if stub_cls:
                self._sensors[sd.name] = stub_cls(config)

        # Create stub actuators (+ implicit drive)
        self._actuators: dict[str, ActuatorInterface] = {}
        drive_config = ActuatorConfig(
            name="drive",
            actuator_type=ActuatorType.DRIVE,
            topic=f"/{robot_id}/cmd_vel",
        )
        self._actuators["drive"] = StubDriveActuator(drive_config)

        for ad in descriptor.actuators:
            config = ActuatorConfig(
                name=ad.name,
                actuator_type=ActuatorType(ad.type.value),
                topic=f"/{robot_id}/{ad.topic}",
                power_draw=ad.power_draw,
            )
            stub_cls = _STUB_ACTUATOR_MAP.get(ActuatorType(ad.type.value))
            if stub_cls:
                self._actuators[ad.name] = stub_cls(config)

        self._battery = StubBattery(descriptor)
        self._kinematics = StubKinematics(descriptor)

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
        pass


# Register the stub backend
register_hal_backend("stub", StubHal)
