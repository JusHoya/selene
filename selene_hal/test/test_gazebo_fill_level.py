"""The Gazebo half of the fraction -> kilogram conversion.

NOT EXECUTED ON THE MACHINE THIS WAS WRITTEN ON. ``selene_hal.gazebo_hal``
imports ``rclpy``, ``std_msgs``, ``sensor_msgs``, ``nav_msgs`` and
``geometry_msgs``; none of those exist on a Windows box without a ROS install,
so the whole module skips here. It runs under ``colcon test`` in the CI image
(``ros:humble-ros-base-jammy``) and on the WSL2 Jazzy box.

It is written and committed rather than quietly omitted because the stub-HAL
version of the same arithmetic (``test_fill_level_units.py``) proves nothing
about this path: the two backends are separate implementations of one contract,
and the one that runs in the field is this one.

The subscription itself is not exercised -- ``_cb`` is called directly with a
message-shaped object -- so this covers the arithmetic and the capacity
resolution, not the DDS plumbing.
"""

import sys

import pytest

# Belt and braces for deviation D-14. selene_orchestrator/test/conftest.py
# builds hand-written stand-ins for rclpy and friends and now scopes them to
# its own directory, so in a cross-package run this module sees no rclpy at all
# and importorskip does the right thing. If that scoping ever regresses, the
# stub would be here — and importing gazebo_hal against it is the one outcome
# to avoid, because it either aborts collection (an ImportError on a name the
# stub lacks is not a ModuleNotFoundError, so importorskip re-raises it) or,
# worse, succeeds and runs the assertions below against fakes. Skip instead.
# selene_hal/test/test_ros_stub_isolation.py fails loudly if this ever fires.
if getattr(sys.modules.get('rclpy'), '__selene_test_stub__', False):
    pytest.skip(
        'a selene_orchestrator ROS stub is installed in this process; '
        'selene_hal.gazebo_hal must not be imported against it (D-14)',
        allow_module_level=True,
    )

gazebo_hal = pytest.importorskip(
    'selene_hal.gazebo_hal',
    reason='requires rclpy and the ROS message packages',
)

from selene_hal.data_types import SensorType          # noqa: E402
from selene_hal.sensor_interface import SensorConfig  # noqa: E402


class _FakeLogger:
    def __init__(self):
        self.warnings = []

    def warn(self, message):
        self.warnings.append(message)


class _FakeNode:
    """Minimal stand-in: records the subscription, hands back a logger."""

    def __init__(self):
        self.logger = _FakeLogger()
        self.subscriptions = []

    def create_subscription(self, msg_type, topic, callback, qos):
        self.subscriptions.append((msg_type, topic, callback, qos))
        return object()

    def get_logger(self):
        return self.logger


class _Float32Like:
    def __init__(self, data):
        self.data = data


def _sensor(node, capacity_kg, name='hopper_fill'):
    config = SensorConfig(
        name=name,
        sensor_type=SensorType.FILL_LEVEL,
        topic=f'/excavator_01/sensors/{name}',
        capacity_kg=capacity_kg,
    )
    return gazebo_hal.GazeboFillLevelSensor(config, node, qos=10)


def test_cb_derives_mass_from_the_rcdl_capacity():
    sensor = _sensor(_FakeNode(), 20.0)

    sensor._cb(_Float32Like(0.95))
    reading = sensor.read()

    assert reading.level == pytest.approx(0.95)
    assert reading.mass_kg == pytest.approx(19.0)
    assert reading.is_valid


def test_cb_matches_the_stub_backend_exactly():
    """The two backends must agree, or a green stub test is meaningless."""
    from selene_hal.stub_hal import StubFillLevelSensor

    config = SensorConfig(
        name='load_cell', sensor_type=SensorType.FILL_LEVEL,
        topic='/hauler_01/sensors/load_cell', capacity_kg=50.0,
    )
    stub = StubFillLevelSensor(config)
    gazebo = gazebo_hal.GazeboFillLevelSensor(config, _FakeNode(), qos=10)

    for fraction in (0.0, 0.02, 0.37, 0.95, 1.0):
        stub.set_level(fraction)
        gazebo._cb(_Float32Like(fraction))
        assert stub.read().mass_kg == pytest.approx(gazebo.read().mass_kg)


def test_missing_capacity_warns_and_reports_zero_mass():
    node = _FakeNode()
    sensor = _sensor(node, None)

    sensor._cb(_Float32Like(0.95))

    assert sensor.read().level == pytest.approx(0.95)
    assert sensor.read().mass_kg == 0.0
    assert any('capacity_kg' in w for w in node.logger.warnings)


def test_reading_before_any_message_is_invalid():
    """An absent sensor must be distinguishable from an empty one."""
    sensor = _sensor(_FakeNode(), 20.0)

    reading = sensor.read()

    assert not reading.is_valid
    assert reading.mass_kg == 0.0


def test_transfer_actuator_encodes_the_authorised_bound():
    """``trigger_load(max_kg)`` -> ``load:<kg>``; unbounded stays bare ``load``."""

    class _Pub:
        def __init__(self):
            self.published = []

        def publish(self, msg):
            self.published.append(msg.data)

    class _PubNode:
        def __init__(self):
            self.pub = _Pub()

        def create_publisher(self, msg_type, topic, qos):
            return self.pub

    from selene_hal.actuator_interface import ActuatorConfig
    from selene_hal.data_types import ActuatorType

    node = _PubNode()
    actuator = gazebo_hal.GazeboTransferActuator(
        ActuatorConfig(name='transport_bin', actuator_type=ActuatorType.TRANSFER,
                       topic='/hauler_01/actuators/load_cmd'),
        node,
    )

    actuator.trigger_load()
    actuator.trigger_load(max_kg=12.5)
    actuator.trigger_unload()

    assert node.pub.published == ['load', 'load:12.500', 'unload']


def test_transfer_complete_never_returns_true_after_a_trigger():
    """Pins the defect ``GazeboTransferActuator``'s docstring records.

    Nothing subscribes to a completion signal from the simulation, so
    ``_complete`` can only be reset by ``cancel_transfer``. A skill that gates
    on this flag stalls until its own timeout. This test exists so that if
    somebody later wires up a real completion signal, the docstring claiming
    otherwise fails with it.
    """

    class _Pub:
        def publish(self, msg):
            pass

    class _PubNode:
        def create_publisher(self, msg_type, topic, qos):
            return _Pub()

    from selene_hal.actuator_interface import ActuatorConfig
    from selene_hal.data_types import ActuatorType

    actuator = gazebo_hal.GazeboTransferActuator(
        ActuatorConfig(name='transport_bin', actuator_type=ActuatorType.TRANSFER,
                       topic='/hauler_01/actuators/load_cmd'),
        _PubNode(),
    )

    assert actuator.is_transfer_complete()      # true only before any trigger
    actuator.trigger_load(max_kg=12.5)
    assert not actuator.is_transfer_complete()
    actuator.cancel_transfer()
    assert actuator.is_transfer_complete()      # the only way back
