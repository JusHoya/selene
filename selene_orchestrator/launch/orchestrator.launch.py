"""Orchestrator launch wrapper.

Args:
  fleet_robot_ids (string list, e.g. "['scout_01','scout_02','excavator_01','hauler_01']")
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    fleet_ids = LaunchConfiguration('fleet_robot_ids')
    params_file = PathJoinSubstitution([
        FindPackageShare('selene_orchestrator'),
        'config',
        'orchestrator_params.yaml',
    ])

    orchestrator = Node(
        package='selene_orchestrator',
        executable='orchestrator_node',
        name='orchestrator',
        output='screen',
        parameters=[
            params_file,
            {'fleet_robot_ids': fleet_ids},
        ],
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'fleet_robot_ids',
            default_value="['scout_01','scout_02','excavator_01','hauler_01']",
        ),
        orchestrator,
    ])
