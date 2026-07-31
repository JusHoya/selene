"""Simulated neutron spectrometer sensor node.

Reads ice deposit ground truth, computes concentration at robot position,
adds Gaussian noise, and publishes scalar readings.

THE POSITION IS WORLD, AND THAT IS THE WHOLE POINT OF THIS SENSOR. The deposits
in ``ice_deposits.yaml`` are placed in world metres, so evaluating the field at
anything else samples the wrong ground. Until 2026-07-31 this node subscribed to
``/{robot_id}/odom``, which Gazebo dead-reckons from each robot's spawn pose,
so it evaluated the ice field at a coordinate the robot was not at and stamped
that coordinate onto ``ResourceMapUpdate.location``. The map was internally
consistent -- the same wrong coordinate was both the sample point and the map
index -- which is exactly why it looked right (register D-08). It now reads
``/{robot_id}/odom_world`` from ``world_odometry_node``, the single place the
spawn SE(2) is applied.
"""

import math
import random
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from std_msgs.msg import Float32
import yaml
import os

from selene_sim.world_frame import WORLD_ODOM_TOPIC


class NeutronSpectrometerNode(Node):
    """Simulates neutron spectrometer readings based on ice deposit proximity."""

    def __init__(self):
        super().__init__('neutron_spectrometer_node')

        self.declare_parameter('robot_id', 'scout_01')
        self.declare_parameter('ice_config_file', '')
        self.declare_parameter('random_seed', 42)

        self.robot_id = self.get_parameter('robot_id').value
        ice_config_file = self.get_parameter('ice_config_file').value
        seed = self.get_parameter('random_seed').value

        self.rng = random.Random(seed)
        self.current_position = (0.0, 0.0)
        self.deposits = []
        self.sensor_params = {
            'max_detection_range': 10.0,
            'noise_base_stddev': 0.3,
            'noise_distance_coefficient': 0.1,
            'sampling_period': 2.0,
        }

        # Load ice deposits config
        if ice_config_file and os.path.exists(ice_config_file):
            with open(ice_config_file, 'r') as f:
                config = yaml.safe_load(f)
            self.deposits = config.get('deposits', [])
            sp = config.get('sensor_parameters', {}).get(
                'neutron_spectrometer', {})
            self.sensor_params.update(sp)

        prefix = f'/{self.robot_id}'

        # World-referenced pose, not raw /odom. See the module docstring.
        self.odom_sub = self.create_subscription(
            Odometry, f'{prefix}/{WORLD_ODOM_TOPIC}', self._odom_callback, 10)

        # Publishers
        self.reading_pub = self.create_publisher(
            Float32, f'{prefix}/sensors/neutron_spec', 10)

        # Timer at sampling period
        period = self.sensor_params['sampling_period']
        self.timer = self.create_timer(period, self._sample)

        self.get_logger().info(
            f'Neutron spectrometer node started for {self.robot_id}: '
            f'{len(self.deposits)} deposits loaded')

    def _odom_callback(self, msg):
        pos = msg.pose.pose.position
        self.current_position = (pos.x, pos.y)

    def _compute_concentration(self):
        """Compute ice concentration at current position from all deposits."""
        x, y = self.current_position
        total_concentration = 0.0
        min_distance = float('inf')

        for deposit in self.deposits:
            cx, cy = deposit['center']
            sigma = deposit.get('sigma', 10.0)
            peak = deposit.get('peak_concentration', 5.0)
            radius = deposit.get('radius', 20.0)

            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)

            if dist <= radius + self.sensor_params['max_detection_range']:
                # Gaussian spatial profile
                conc = peak * math.exp(-(dist ** 2) / (2 * sigma ** 2))
                total_concentration += conc
                min_distance = min(min_distance, dist)

        return total_concentration, min_distance

    def _sample(self):
        """Take a sensor reading and publish."""
        concentration, min_dist = self._compute_concentration()

        # Add noise proportional to distance
        if min_dist == float('inf'):
            min_dist = self.sensor_params['max_detection_range']
        noise_stddev = (self.sensor_params['noise_base_stddev']
                        + self.sensor_params['noise_distance_coefficient']
                        * min_dist)
        noise = self.rng.gauss(0.0, noise_stddev)

        # Clamp to non-negative
        reading = max(0.0, concentration + noise)

        msg = Float32()
        msg.data = reading
        self.reading_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = NeutronSpectrometerNode()
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
