"""Per-robot agent launch wrapper.

Args:
  robot_id     (e.g. 'scout_01')
  robot_type   ('scout' | 'excavator' | 'hauler')
  rcdl         ('scout.yaml' | 'excavator.yaml' | 'hauler.yaml')
  orchestrated (default true)
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    robot_id = LaunchConfiguration('robot_id')
    robot_type = LaunchConfiguration('robot_type')
    rcdl = LaunchConfiguration('rcdl')
    orchestrated = LaunchConfiguration('orchestrated')

    rcdl_path = PathJoinSubstitution([
        FindPackageShare('selene_hal'),
        'config',
        rcdl,
    ])
    nav_config = PathJoinSubstitution([
        FindPackageShare('selene_agent'),
        'config',
        'nav_params.yaml',
    ])

    agent = Node(
        package='selene_agent',
        executable='agent_node',
        name=['agent_', robot_id],
        output='screen',
        parameters=[{
            'robot_id': robot_id,
            'robot_type': robot_type,
            'rcdl_path': rcdl_path,
            'hal_backend': 'gazebo',
            'nav_config_path': nav_config,
            'orchestrated': orchestrated,
        }],
    )

    return LaunchDescription([
        DeclareLaunchArgument('robot_id'),
        DeclareLaunchArgument('robot_type'),
        DeclareLaunchArgument('rcdl'),
        DeclareLaunchArgument('orchestrated', default_value='true'),
        agent,
    ])
