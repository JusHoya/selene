"""Simulated hopper fill sensor for Excavator robots.

Tracks material extracted when drill is active at an ice deposit location.
"""

import math
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from std_msgs.msg import Float32, Bool
import yaml
import os


class HopperNode(Node):
    """Simulates excavator hopper fill level."""

    HOPPER_CAPACITY_KG = 20.0
    BASE_EXTRACTION_RATE = 0.5  # kg/s at peak concentration

    def __init__(self):
        super().__init__('hopper_node')

        self.declare_parameter('robot_id', 'excavator_01')
        self.declare_parameter('ice_config_file', '')
        self.declare_parameter('update_rate', 10.0)

        self.robot_id = self.get_parameter('robot_id').value
        ice_config_file = self.get_parameter('ice_config_file').value
        update_rate = self.get_parameter('update_rate').value

        self.current_position = (0.0, 0.0)
        self.is_drilling = False
        self.fill_kg = 0.0
        self.deposits = []

        if ice_config_file and os.path.exists(ice_config_file):
            with open(ice_config_file, 'r') as f:
                config = yaml.safe_load(f)
            self.deposits = config.get('deposits', [])

        prefix = f'/{self.robot_id}'

        self.odom_sub = self.create_subscription(
            Odometry, f'{prefix}/odom', self._odom_callback, 10)
        self.drill_sub = self.create_subscription(
            Bool, f'{prefix}/actuators/drill_cmd', self._drill_callback, 10)

        self.fill_pub = self.create_publisher(
            Float32, f'{prefix}/sensors/hopper_fill', 10)

        self.dt = 1.0 / update_rate
        self.timer = self.create_timer(self.dt, self._update)

        self.get_logger().info(
            f'Hopper node started for {self.robot_id}: '
            f'capacity={self.HOPPER_CAPACITY_KG} kg')

    def _odom_callback(self, msg):
        pos = msg.pose.pose.position
        self.current_position = (pos.x, pos.y)

    def _drill_callback(self, msg):
        self.is_drilling = msg.data

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
        if self.is_drilling and self.fill_kg < self.HOPPER_CAPACITY_KG:
            concentration = self._get_local_concentration()
            # Extraction rate proportional to concentration (normalized to 10 wt%)
            rate = self.BASE_EXTRACTION_RATE * (concentration / 10.0)
            self.fill_kg = min(self.HOPPER_CAPACITY_KG,
                               self.fill_kg + rate * self.dt)

        msg = Float32()
        msg.data = self.fill_kg
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
        rclpy.shutdown()


if __name__ == '__main__':
    main()
