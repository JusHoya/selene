"""Battery simulation node for SELENE robots.

Subscribes to robot odometry and command velocity to compute energy consumption.
Publishes battery state. Implements solar recharging when in illuminated zone.

Energy model:
  power_draw = P_idle + P_locomotion * speed * slope_factor + P_actuators
  slope_factor = 1.0 + 2.0 * sin(slope_angle)  (clamped min 0.3)
  battery_delta_wh = power_draw * dt / 3600
"""

import math
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState
from std_msgs.msg import Float32, Bool
import yaml
import os


class BatteryNode(Node):
    """Simulates battery energy model for a single robot."""

    # Default energy parameters per robot type
    ENERGY_PARAMS = {
        'scout': {
            'capacity_wh': 50.0,
            'idle_draw_w': 10.0,
            'locomotion_draw_w_per_ms': 150.0,
            'solar_recharge_w': 40.0,
        },
        'excavator': {
            'capacity_wh': 80.0,
            'idle_draw_w': 15.0,
            'locomotion_draw_w_per_ms': 250.0,
            'solar_recharge_w': 40.0,
        },
        'hauler': {
            'capacity_wh': 65.0,
            'idle_draw_w': 12.0,
            'locomotion_draw_w_per_ms': 200.0,
            'solar_recharge_w': 40.0,
        },
    }

    def __init__(self):
        super().__init__('battery_node')

        # Declare parameters
        self.declare_parameter('robot_id', 'robot_01')
        self.declare_parameter('robot_type', 'scout')
        self.declare_parameter('world_params_file', '')
        self.declare_parameter('update_rate', 10.0)

        self.robot_id = self.get_parameter('robot_id').value
        self.robot_type = self.get_parameter('robot_type').value
        update_rate = self.get_parameter('update_rate').value

        # Load energy parameters
        params = self.ENERGY_PARAMS.get(self.robot_type, self.ENERGY_PARAMS['scout'])
        self.capacity_wh = params['capacity_wh']
        self.idle_draw_w = params['idle_draw_w']
        self.loco_draw_w = params['locomotion_draw_w_per_ms']
        self.solar_recharge_w = params['solar_recharge_w']

        # State
        self.remaining_wh = self.capacity_wh
        self.current_speed = 0.0
        self.current_position = (0.0, 0.0, 0.0)
        self.last_position = None
        self.actuator_draw_w = 0.0
        self.is_charging = False

        # Load world params for PSR/solar zone checking
        self.psr_zones = []
        world_params_file = self.get_parameter('world_params_file').value
        if world_params_file and os.path.exists(world_params_file):
            with open(world_params_file, 'r') as f:
                world_config = yaml.safe_load(f)
            if 'world' in world_config and 'psr_zones' in world_config['world']:
                self.psr_zones = world_config['world']['psr_zones']

        # Subscribers
        prefix = f'/{self.robot_id}'
        self.cmd_vel_sub = self.create_subscription(
            Twist, f'{prefix}/cmd_vel', self._cmd_vel_callback, 10)
        self.odom_sub = self.create_subscription(
            Odometry, f'{prefix}/odom', self._odom_callback, 10)
        self.drill_sub = self.create_subscription(
            Bool, f'{prefix}/actuators/drill_cmd', self._drill_callback, 10)

        # Publisher
        self.battery_pub = self.create_publisher(
            BatteryState, f'{prefix}/battery_state', 10)

        # Timer
        self.dt = 1.0 / update_rate
        self.timer = self.create_timer(self.dt, self._update)

        self.get_logger().info(
            f'Battery node started for {self.robot_id} ({self.robot_type}): '
            f'{self.capacity_wh} Wh capacity')

    def _cmd_vel_callback(self, msg):
        self.current_speed = math.sqrt(msg.linear.x ** 2 + msg.linear.y ** 2)

    def _odom_callback(self, msg):
        pos = msg.pose.pose.position
        self.current_position = (pos.x, pos.y, pos.z)

    def _drill_callback(self, msg):
        # When drill is active, add excavator drill power draw
        if msg.data:
            self.actuator_draw_w = 200.0  # drill power
        else:
            self.actuator_draw_w = 0.0

    def _is_in_psr(self):
        """Check if robot is in a permanently shadowed region."""
        x, y = self.current_position[0], self.current_position[1]
        for zone in self.psr_zones:
            if zone.get('type') == 'circle':
                cx, cy = zone['center']
                r = zone['radius']
                dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                if dist <= r:
                    return True
        return False

    def _compute_slope_factor(self):
        """Estimate slope from consecutive positions."""
        if self.last_position is None:
            self.last_position = self.current_position
            return 1.0

        dx = self.current_position[0] - self.last_position[0]
        dy = self.current_position[1] - self.last_position[1]
        dz = self.current_position[2] - self.last_position[2]
        horiz = math.sqrt(dx ** 2 + dy ** 2)

        self.last_position = self.current_position

        if horiz < 0.001:
            return 1.0

        slope_angle = math.atan2(dz, horiz)
        factor = 1.0 + 2.0 * math.sin(slope_angle)
        return max(factor, 0.3)

    def _update(self):
        slope_factor = self._compute_slope_factor()

        # Compute power draw
        power_w = (self.idle_draw_w
                   + self.loco_draw_w * self.current_speed * slope_factor
                   + self.actuator_draw_w)

        # Solar recharging: in solar zone and stationary
        self.is_charging = False
        if not self._is_in_psr() and self.current_speed < 0.05:
            self.is_charging = True
            power_w -= self.solar_recharge_w

        # Update battery
        delta_wh = power_w * self.dt / 3600.0
        self.remaining_wh = max(0.0, min(self.capacity_wh,
                                          self.remaining_wh - delta_wh))

        # Publish BatteryState
        msg = BatteryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.voltage = 48.0  # nominal
        msg.current = power_w / 48.0
        msg.charge = self.remaining_wh / 48.0  # Ah approximation
        msg.capacity = self.capacity_wh / 48.0
        msg.percentage = self.remaining_wh / self.capacity_wh
        msg.power_supply_status = (
            BatteryState.POWER_SUPPLY_STATUS_CHARGING if self.is_charging
            else BatteryState.POWER_SUPPLY_STATUS_DISCHARGING
        )
        msg.present = True
        self.battery_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = BatteryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
