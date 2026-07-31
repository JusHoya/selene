"""Simulated hopper fill sensor for Excavator robots.

Tracks material extracted while the drill is active over an ice deposit, and
empties the hopper when the excavator's transfer actuator commands it to.

PUBLISHES A FRACTION, NOT KILOGRAMS. ``/{robot_id}/sensors/hopper_fill`` is a
``std_msgs/Float32`` in 0.0-1.0, matching what the HAL documents on
``FillLevelReading.level`` and what ``ExcavateSkill.FILL_THRESHOLD`` (0.95) is
compared against. Until 2026-07-30 this node published kilograms into that
field, so a 20 kg hopper reported "full" at 0.95 kg -- 4.75% -- and the skill
completed after under two seconds of drilling. The kilogram value still exists,
but it is now derived once, in the HAL, from the ``capacity_kg`` this node and
the HAL both read out of the same RCDL. See ``docs/phase5_deviation_register.md``
D-06 and ``selene_sim/selene_sim/fill_model.py``.

SUBSCRIBES TO ``/{robot_id}/actuators/hopper_cmd`` -- its first subscriber ever.
``selene_hal/config/excavator.yaml:46`` has declared that topic since Phase 1
with nothing listening, so the hopper had no way to empty. Without it the
SECOND excavate task on a robot starts already above FILL_THRESHOLD, completes
in one tick, and reports an extracted mass of zero.
"""

import math
import os

import rclpy
import yaml
from nav_msgs.msg import Odometry
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, String

from selene_sim.fill_model import (
    FillModel, parse_transfer_command, read_fill_capacity_kg, read_transfer_rate,
)
from selene_sim.world_frame import WORLD_ODOM_TOPIC


class HopperNode(Node):
    """Simulates excavator hopper fill level."""

    BASE_EXTRACTION_RATE = 0.5  # kg/s at PEAK_CONCENTRATION_WT (10 wt%)

    def __init__(self):
        super().__init__('hopper_node')

        self.declare_parameter('robot_id', 'excavator_01')
        self.declare_parameter('ice_config_file', '')
        self.declare_parameter('update_rate', 10.0)
        # The RCDL this excavator's HAL is built from. Required: there is no
        # default capacity, because guessing one would publish a fraction the
        # HAL converts back into a mass nobody could reconcile.
        self.declare_parameter('rcdl_path', '')
        self.declare_parameter('sensor_name', 'hopper_fill')
        self.declare_parameter('actuator_name', 'hopper')

        self.robot_id = self.get_parameter('robot_id').value
        ice_config_file = self.get_parameter('ice_config_file').value
        update_rate = self.get_parameter('update_rate').value
        rcdl_path = self.get_parameter('rcdl_path').value
        sensor_name = self.get_parameter('sensor_name').value
        actuator_name = self.get_parameter('actuator_name').value

        # Raises on a missing file, entry or non-positive value. Failing the
        # node is the intended behaviour -- a hopper that silently sizes itself
        # wrong is exactly the defect this file is fixing.
        capacity_kg = read_fill_capacity_kg(rcdl_path, sensor_name)
        transfer_rate = read_transfer_rate(rcdl_path, actuator_name)

        self.model = FillModel(
            capacity_kg=capacity_kg,
            fill_rate_kg_s=self.BASE_EXTRACTION_RATE,
            transfer_rate_kg_s=transfer_rate,
        )

        self.current_position = (0.0, 0.0)
        self.is_drilling = False
        self.is_unloading = False
        self.deposits = []

        if ice_config_file and os.path.exists(ice_config_file):
            with open(ice_config_file, 'r') as f:
                config = yaml.safe_load(f)
            self.deposits = config.get('deposits', [])

        prefix = f'/{self.robot_id}'

        # World-referenced pose. The fill rate is a function of the ice
        # concentration UNDER THE DRILL, and the deposits are placed in world
        # metres, so a spawn-relative pose extracts from the wrong ground.
        self.odom_sub = self.create_subscription(
            Odometry, f'{prefix}/{WORLD_ODOM_TOPIC}', self._odom_callback, 10)
        self.drill_sub = self.create_subscription(
            Bool, f'{prefix}/actuators/drill_cmd', self._drill_callback, 10)
        self.hopper_cmd_sub = self.create_subscription(
            String, f'{prefix}/actuators/hopper_cmd',
            self._hopper_cmd_callback, 10)

        self.fill_pub = self.create_publisher(
            Float32, f'{prefix}/sensors/hopper_fill', 10)

        self.dt = 1.0 / update_rate
        self.timer = self.create_timer(self.dt, self._update)

        self.get_logger().info(
            f'Hopper node started for {self.robot_id}: '
            f'capacity={capacity_kg} kg, transfer_rate={transfer_rate} kg/s '
            f'(from {rcdl_path}); publishing a 0.0-1.0 fraction')

    def _odom_callback(self, msg):
        pos = msg.pose.pose.position
        self.current_position = (pos.x, pos.y)

    def _drill_callback(self, msg):
        self.is_drilling = msg.data

    def _hopper_cmd_callback(self, msg):
        """Handle ``unload`` / ``stop``; ignore any ``load`` form.

        Shares ``fill_model.parse_transfer_command`` with the hauler's bin so
        one tested parser covers both topics, then rejects the one mode that
        makes no sense here: an excavator hopper is filled by drilling, not by
        command. A load arriving on this topic is logged rather than silently
        dropped, because it means a caller has confused the hopper with the
        hauler's transport bin.
        """
        command = parse_transfer_command(msg.data, self.model.capacity_kg)

        if command.error is not None:
            self.get_logger().warn(
                f'{self.robot_id}: ignoring hopper_cmd {msg.data!r} -- '
                f'{command.error}')
            return

        if command.mode == 'loading':
            self.get_logger().warn(
                f'{self.robot_id}: ignoring hopper_cmd {msg.data!r} -- an '
                f'excavator hopper fills by drilling, not by command.')
            return

        self.is_unloading = (command.mode == 'unloading')

    def _get_local_concentration(self):
        """Get ice concentration at current position."""
        x, y = self.current_position
        total = 0.0
        for deposit in self.deposits:
            cx, cy = deposit['center']
            sigma = deposit.get('sigma', 10.0)
            peak = deposit.get('peak_concentration', 5.0)
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            total += peak * math.exp(-(dist ** 2) / (2 * sigma ** 2))
        return total

    def _update(self):
        # Unloading wins over drilling. ExcavateSkill stops the drill before it
        # dumps, so the two should never overlap; if they do, draining is the
        # safer interpretation -- material appearing during a dump would make
        # the skill's residual reading disagree with its own delta.
        if self.is_unloading:
            self.model.drain(self.dt)
            if self.model.is_empty:
                self.is_unloading = False
        elif self.is_drilling:
            self.model.fill(self.dt, self._get_local_concentration())

        msg = Float32()
        msg.data = self.model.fraction
        self.fill_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = HopperNode()
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
