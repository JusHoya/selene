"""Battery simulation node for SELENE robots.

Subscribes to robot odometry and command velocity to compute energy consumption.
Publishes battery state. Implements solar recharging when in illuminated zone.

Energy model:
  power_draw = P_idle + P_locomotion * speed * slope_factor + P_actuators
  slope_factor = 1.0 + 2.0 * sin(slope_angle)  (clamped min 0.3)
  battery_delta_wh = power_draw * dt / 3600

SHADOW IS A PROPERTY OF THE WORLD, NOT OF A ROBOT'S ODOMETER. ``_is_in_psr()``
tests the robot's position against the PSR disc in ``world_params.yaml``, which
is placed in world metres. This node used to subscribe to ``/{robot_id}/odom``,
which Gazebo dead-reckons from each robot's spawn pose, so the shadow test was
evaluated at a coordinate the robot was not at -- a different wrong coordinate
per robot, since each carries its own spawn offset (register D-08). It now reads
``/{robot_id}/odom_world``.

Expect this to CHANGE observed energy behaviour, correctly: a robot working at
the survey waypoints is now genuinely inside the 60 m PSR disc and gets no solar
recharge there, which is the physics the mission was designed around and the
reason ``spawn_positions.yaml`` places the fleet outside the disc.
"""

import math
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState
from std_msgs.msg import Bool
import yaml
import os

from selene_sim.world_frame import WORLD_ODOM_TOPIC
from selene_sim.battery_model import BatteryModel


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

        # State. current_speed and current_position are LATCHED from the last
        # message on each topic; nothing decays either. See _update.
        self.remaining_wh = self.capacity_wh
        self.current_speed = 0.0
        self.current_position = (0.0, 0.0, 0.0)
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

        self._model = BatteryModel(
            capacity_wh=self.capacity_wh,
            idle_draw_w=self.idle_draw_w,
            locomotion_draw_w_per_ms=self.loco_draw_w,
            solar_recharge_w=self.solar_recharge_w,
            psr_zones=self.psr_zones,
        )

        # Subscribers
        prefix = f'/{self.robot_id}'
        self.cmd_vel_sub = self.create_subscription(
            Twist, f'{prefix}/cmd_vel', self._cmd_vel_callback, 10)
        self.odom_sub = self.create_subscription(
            Odometry, f'{prefix}/{WORLD_ODOM_TOPIC}', self._odom_callback, 10)
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

    def _update(self):
        # THE ARITHMETIC LIVES IN selene_sim.battery_model AND IS TESTED THERE.
        # It used to be inline here, behind this file's module-level `import
        # rclpy`, which meant it ran in one pytest lane out of five and in
        # practice was covered by none of them: this node had zero tests of any
        # kind until 2026-08-01. Register D-42 had to re-derive its arithmetic by
        # hand as a result. See selene_sim/test/test_battery_model.py.
        #
        # `self.current_speed` is whatever cmd_vel last carried and nothing
        # decays it -- see _cmd_vel_callback. That is the input the model
        # integrates, and it is the reason an orphaned battery_node drains to the
        # model's lower clamp and then publishes exactly 0.0 forever.
        tick = self._model.step(
            self.dt, self.current_speed, self.current_position,
            self.actuator_draw_w,
        )
        self.remaining_wh = tick.remaining_wh
        self.is_charging = tick.is_charging

        # Publish BatteryState
        msg = BatteryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.voltage = 48.0  # nominal
        msg.current = tick.power_w / 48.0
        msg.charge = self.remaining_wh / 48.0  # Ah approximation
        msg.capacity = self.capacity_wh / 48.0
        msg.percentage = self._model.charge_fraction
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
