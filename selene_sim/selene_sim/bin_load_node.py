"""Simulated transport bin load cell for Hauler robots.

Tracks load/unload events for material transport.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String


class BinLoadNode(Node):
    """Simulates hauler transport bin load level."""

    BIN_CAPACITY_KG = 50.0
    TRANSFER_RATE_KG_S = 10.0

    def __init__(self):
        super().__init__('bin_load_node')

        self.declare_parameter('robot_id', 'hauler_01')
        self.declare_parameter('update_rate', 10.0)

        self.robot_id = self.get_parameter('robot_id').value
        update_rate = self.get_parameter('update_rate').value

        self.load_kg = 0.0
        self.transfer_mode = None  # None, 'loading', 'unloading'

        prefix = f'/{self.robot_id}'

        self.load_cmd_sub = self.create_subscription(
            String, f'{prefix}/actuators/load_cmd', self._load_cmd_callback, 10)

        self.load_pub = self.create_publisher(
            Float32, f'{prefix}/sensors/bin_load', 10)

        self.dt = 1.0 / update_rate
        self.timer = self.create_timer(self.dt, self._update)

        self.get_logger().info(
            f'Bin load node started for {self.robot_id}: '
            f'capacity={self.BIN_CAPACITY_KG} kg')

    def _load_cmd_callback(self, msg):
        cmd = msg.data.lower().strip()
        if cmd == 'load':
            self.transfer_mode = 'loading'
        elif cmd == 'unload':
            self.transfer_mode = 'unloading'
        elif cmd == 'stop':
            self.transfer_mode = None

    def _update(self):
        if self.transfer_mode == 'loading':
            self.load_kg = min(self.BIN_CAPACITY_KG,
                               self.load_kg + self.TRANSFER_RATE_KG_S * self.dt)
            if self.load_kg >= self.BIN_CAPACITY_KG:
                self.transfer_mode = None

        elif self.transfer_mode == 'unloading':
            self.load_kg = max(0.0,
                               self.load_kg - self.TRANSFER_RATE_KG_S * self.dt)
            if self.load_kg <= 0.0:
                self.transfer_mode = None

        msg = Float32()
        msg.data = self.load_kg
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
        rclpy.shutdown()


if __name__ == '__main__':
    main()
