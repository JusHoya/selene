"""Simulated transport bin load cell for Hauler robots.

Tracks load/unload events for material transport.

TWO DEFECTS THIS NODE CARRIED UNTIL 2026-07-30, both silent (deviation D-06):

1. WRONG TOPIC. It published on ``/{robot_id}/sensors/bin_load``, but
   ``selene_hal/config/hauler.yaml:27`` declares the load cell on
   ``sensors/load_cell`` and ``selene_hal/selene_hal/gazebo_hal.py`` builds a
   sensor's topic as ``/{robot_id}/{sd.topic}``. So the HAL had always
   subscribed to a topic nothing published, and ``HaulSkill`` read the
   ``is_valid=False`` default forever. ``sensors/bin_load`` had zero
   subscribers repo-wide. The SIM NODE MOVED, not the RCDL: the RCDL is the
   published contract for a robot type and already follows the
   ``sensors/<name>`` convention every other sensor uses.

2. WRONG UNIT. It published kilograms into a value the HAL documents as a
   0.0-1.0 fraction (``FillLevelReading.level``). It now publishes the
   fraction; the HAL derives kilograms from the ``capacity_kg`` both sides read
   out of the same RCDL.

It also filled to the full 50 kg on any bare ``load`` command, regardless of
whether any excavator had extracted anything -- material created from nothing,
which is precisely what FR-ISRU-2's acceptance ("no material is lost or
duplicated") forbids. ``load:<kg>`` bounds the fill to what the orchestrator's
ledger authorised.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String

from selene_sim.fill_model import (
    FillModel, parse_transfer_command, read_fill_capacity_kg, read_transfer_rate,
)


class BinLoadNode(Node):
    """Simulates hauler transport bin load level."""

    def __init__(self):
        super().__init__('bin_load_node')

        self.declare_parameter('robot_id', 'hauler_01')
        self.declare_parameter('update_rate', 10.0)
        # The RCDL this hauler's HAL is built from. Required -- see hopper_node.
        self.declare_parameter('rcdl_path', '')
        self.declare_parameter('sensor_name', 'load_cell')
        self.declare_parameter('actuator_name', 'transport_bin')

        self.robot_id = self.get_parameter('robot_id').value
        update_rate = self.get_parameter('update_rate').value
        rcdl_path = self.get_parameter('rcdl_path').value
        sensor_name = self.get_parameter('sensor_name').value
        actuator_name = self.get_parameter('actuator_name').value

        capacity_kg = read_fill_capacity_kg(rcdl_path, sensor_name)
        transfer_rate = read_transfer_rate(rcdl_path, actuator_name)

        self.model = FillModel(
            capacity_kg=capacity_kg,
            transfer_rate_kg_s=transfer_rate,
        )

        self.transfer_mode = None  # None, 'loading', 'unloading'
        self.load_target_kg = 0.0

        prefix = f'/{self.robot_id}'

        self.load_cmd_sub = self.create_subscription(
            String, f'{prefix}/actuators/load_cmd', self._load_cmd_callback, 10)

        self.load_pub = self.create_publisher(
            Float32, f'{prefix}/sensors/load_cell', 10)

        self.dt = 1.0 / update_rate
        self.timer = self.create_timer(self.dt, self._update)

        self.get_logger().info(
            f'Bin load node started for {self.robot_id}: '
            f'capacity={capacity_kg} kg, transfer_rate={transfer_rate} kg/s '
            f'(from {rcdl_path}); publishing a 0.0-1.0 fraction on '
            f'{prefix}/sensors/load_cell')

    def _load_cmd_callback(self, msg):
        """Apply a ``load`` | ``load:<kg>`` | ``unload`` | ``stop`` command.

        The parsing itself is in ``fill_model.parse_transfer_command`` so it can
        be tested without rclpy; this method only applies the result. A
        rejected payload leaves the current transfer ALONE rather than stopping
        it -- a garbled message should not silently abort a load in progress.
        """
        command = parse_transfer_command(msg.data, self.model.capacity_kg)

        if command.error is not None:
            self.get_logger().warn(
                f'{self.robot_id}: ignoring load_cmd {msg.data!r} -- '
                f'{command.error}')
            return

        if command.mode == 'loading':
            self.load_target_kg = command.target_kg
        self.transfer_mode = None if command.mode == 'idle' else command.mode

    def _update(self):
        if self.transfer_mode == 'loading':
            # load_toward returns the kilograms it actually moved, so a zero
            # means the target (or the capacity) has been reached. Testing that
            # rather than comparing floats avoids an epsilon that would have to
            # agree with the transfer rate and the tick period.
            if self.model.load_toward(self.dt, self.load_target_kg) <= 0.0:
                self.transfer_mode = None

        elif self.transfer_mode == 'unloading':
            self.model.drain(self.dt)
            if self.model.is_empty:
                self.transfer_mode = None

        msg = Float32()
        msg.data = self.model.fraction
        self.load_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = BinLoadNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        # GUARDED, because a launch-level shutdown gets there first. When the
        # simulator dies, simulation.launch.py brings the whole system down and
        # every node is SIGINT-ed; rclpy has already shut the context down by
        # the time this runs, and calling it again raises
        #   RCLError: failed to shutdown: rcl_shutdown already called
        # out of `finally`, so the process exits 1 and the launch reports
        # "process has died [exit code 1]". Eight of those buried the actual
        # diagnosis in the 2026-07-31 smoke test. A clean teardown must not
        # look like eight crashes, least of all on the one code path whose
        # whole purpose is to be legible after a crash.
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
