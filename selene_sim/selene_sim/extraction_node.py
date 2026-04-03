"""Simulated extraction process for Excavator drill/heater.

Computes extraction rate based on local ice concentration and drill power.
"""

import math
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from std_msgs.msg import Float32, Bool
import yaml
import os


class ExtractionNode(Node):
    """Simulates the extraction process at the drill location."""

    def __init__(self):
        super().__init__('extraction_node')

        self.declare_parameter('robot_id', 'excavator_01')
        self.declare_parameter('ice_config_file', '')
        self.declare_parameter('update_rate', 10.0)

        self.robot_id = self.get_parameter('robot_id').value
        ice_config_file = self.get_parameter('ice_config_file').value
        update_rate = self.get_parameter('update_rate').value

        self.current_position = (0.0, 0.0)
        self.is_drilling = False
        self.total_extracted_kg = 0.0
        self.current_rate = 0.0
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

        self.rate_pub = self.create_publisher(
            Float32, f'{prefix}/extraction/rate', 10)
        self.total_pub = self.create_publisher(
            Float32, f'{prefix}/extraction/total', 10)

        self.dt = 1.0 / update_rate
        self.timer = self.create_timer(self.dt, self._update)

        self.get_logger().info(
            f'Extraction node started for {self.robot_id}')

    def _odom_callback(self, msg):
        pos = msg.pose.pose.position
        self.current_position = (pos.x, pos.y)

    def _drill_callback(self, msg):
        self.is_drilling = msg.data

    def _get_local_concentration(self):
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
        if self.is_drilling:
            concentration = self._get_local_concentration()
            self.current_rate = 0.5 * (concentration / 10.0)  # kg/s
            self.total_extracted_kg += self.current_rate * self.dt
        else:
            self.current_rate = 0.0

        rate_msg = Float32()
        rate_msg.data = self.current_rate
        self.rate_pub.publish(rate_msg)

        total_msg = Float32()
        total_msg.data = self.total_extracted_kg
        self.total_pub.publish(total_msg)


def main(args=None):
    rclpy.init(args=args)
    node = ExtractionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
