"""SELENE simulation launch — starts Gazebo world with full robot fleet.

Usage:
    ros2 launch selene_sim simulation.launch.py
    ros2 launch selene_sim simulation.launch.py num_scouts:=3 num_excavators:=2
"""

import os
import yaml
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory('selene_sim')

    # Paths
    world_file = os.path.join(pkg_share, 'worlds', 'lunar_psr.sdf')
    models_path = os.path.join(pkg_share, 'models')
    scout_sdf = os.path.join(models_path, 'scout', 'model.sdf')
    excavator_sdf = os.path.join(models_path, 'excavator', 'model.sdf')
    hauler_sdf = os.path.join(models_path, 'hauler', 'model.sdf')
    ice_config = os.path.join(pkg_share, 'config', 'ice_deposits.yaml')
    world_params = os.path.join(pkg_share, 'config', 'world_params.yaml')
    spawn_config_path = os.path.join(pkg_share, 'config', 'spawn_positions.yaml')
    rviz_config = os.path.join(pkg_share, 'rviz', 'selene_sim.rviz')

    # Load spawn positions
    with open(spawn_config_path, 'r') as f:
        spawn_positions = yaml.safe_load(f)

    # Launch arguments
    num_scouts_arg = DeclareLaunchArgument(
        'num_scouts', default_value='2', description='Number of scout robots')
    num_excavators_arg = DeclareLaunchArgument(
        'num_excavators', default_value='1', description='Number of excavator robots')
    num_haulers_arg = DeclareLaunchArgument(
        'num_haulers', default_value='1', description='Number of hauler robots')
    use_rviz_arg = DeclareLaunchArgument(
        'rviz', default_value='false', description='Launch RViz2')

    # Set Gazebo model path
    gz_resource_path = SetEnvironmentVariable(
        'GZ_SIM_RESOURCE_PATH', models_path)


    # Start Gazebo
    gz_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('ros_gz_sim'),
                'launch', 'gz_sim.launch.py'
            )
        ),
        # -s = server-only (no GUI).  Avoids OGRE shader crashes on WSL2
        # and keeps the footprint small; the dashboard is the operator UI.
        launch_arguments={'gz_args': ['-s -r ', world_file]}.items(),
    )

    # Build robot spawn actions
    spawn_actions = []
    spawn_delay = 2.0  # seconds between spawns to avoid collision

    # Scouts
    for i, pos in enumerate(spawn_positions.get('scouts', [])[:2]):
        robot_id = f'scout_{i + 1:02d}'
        spawn_actions.append(TimerAction(
            period=spawn_delay * (len(spawn_actions) + 1),
            actions=[
                Node(
                    package='ros_gz_sim',
                    executable='create',
                    arguments=['-name', robot_id, '-file', scout_sdf,
                               '-x', str(pos['x']), '-y', str(pos['y']),
                               '-z', str(pos['z']), '-Y', str(pos.get('yaw', 0.0))],
                    output='screen',
                ),
            ],
        ))

    # Excavators
    for i, pos in enumerate(spawn_positions.get('excavators', [])[:1]):
        robot_id = f'excavator_{i + 1:02d}'
        spawn_actions.append(TimerAction(
            period=spawn_delay * (len(spawn_actions) + 1),
            actions=[
                Node(
                    package='ros_gz_sim',
                    executable='create',
                    arguments=['-name', robot_id, '-file', excavator_sdf,
                               '-x', str(pos['x']), '-y', str(pos['y']),
                               '-z', str(pos['z']), '-Y', str(pos.get('yaw', 0.0))],
                    output='screen',
                ),
            ],
        ))

    # Haulers
    for i, pos in enumerate(spawn_positions.get('haulers', [])[:1]):
        robot_id = f'hauler_{i + 1:02d}'
        spawn_actions.append(TimerAction(
            period=spawn_delay * (len(spawn_actions) + 1),
            actions=[
                Node(
                    package='ros_gz_sim',
                    executable='create',
                    arguments=['-name', robot_id, '-file', hauler_sdf,
                               '-x', str(pos['x']), '-y', str(pos['y']),
                               '-z', str(pos['z']), '-Y', str(pos.get('yaw', 0.0))],
                    output='screen',
                ),
            ],
        ))

    # Bridge nodes (one per robot)
    bridge_actions = []
    all_robots = []
    for i in range(2):
        all_robots.append(('scout', f'scout_{i + 1:02d}'))
    for i in range(1):
        all_robots.append(('excavator', f'excavator_{i + 1:02d}'))
    for i in range(1):
        all_robots.append(('hauler', f'hauler_{i + 1:02d}'))

    for robot_type, robot_id in all_robots:
        bridge_actions.append(Node(
            package='ros_gz_bridge',
            executable='parameter_bridge',
            name=f'bridge_{robot_id}',
            arguments=[
                f'/model/{robot_id}/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist',
                f'/model/{robot_id}/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry',
            ],
            remappings=[
                (f'/model/{robot_id}/cmd_vel', f'/{robot_id}/cmd_vel'),
                (f'/model/{robot_id}/odometry', f'/{robot_id}/odom'),
            ],
            output='screen',
        ))

    # Sensor/simulation nodes
    sensor_actions = []

    # Battery nodes for all robots
    for robot_type, robot_id in all_robots:
        sensor_actions.append(Node(
            package='selene_sim',
            executable='battery_node',
            name=f'battery_{robot_id}',
            parameters=[{
                'robot_id': robot_id,
                'robot_type': robot_type,
                'world_params_file': world_params,
            }],
            output='screen',
        ))

    # Neutron spectrometer for scouts
    for i in range(2):
        robot_id = f'scout_{i + 1:02d}'
        sensor_actions.append(Node(
            package='selene_sim',
            executable='neutron_spectrometer_node',
            name=f'neutron_spec_{robot_id}',
            parameters=[{
                'robot_id': robot_id,
                'ice_config_file': ice_config,
            }],
            output='screen',
        ))

    # Hopper and extraction nodes for excavators
    for i in range(1):
        robot_id = f'excavator_{i + 1:02d}'
        sensor_actions.append(Node(
            package='selene_sim',
            executable='hopper_node',
            name=f'hopper_{robot_id}',
            parameters=[{
                'robot_id': robot_id,
                'ice_config_file': ice_config,
            }],
            output='screen',
        ))
        sensor_actions.append(Node(
            package='selene_sim',
            executable='extraction_node',
            name=f'extraction_{robot_id}',
            parameters=[{
                'robot_id': robot_id,
                'ice_config_file': ice_config,
            }],
            output='screen',
        ))

    # Bin load node for haulers
    for i in range(1):
        robot_id = f'hauler_{i + 1:02d}'
        sensor_actions.append(Node(
            package='selene_sim',
            executable='bin_load_node',
            name=f'bin_load_{robot_id}',
            parameters=[{'robot_id': robot_id}],
            output='screen',
        ))

    # RViz2 (optional)
    rviz = Node(
        package='rviz2',
        executable='rviz2',
        arguments=['-d', rviz_config],
        condition=IfCondition(LaunchConfiguration('rviz')),
        output='screen',
    )

    return LaunchDescription([
        num_scouts_arg,
        num_excavators_arg,
        num_haulers_arg,
        use_rviz_arg,
        gz_resource_path,
        gz_sim,
        *spawn_actions,
        *bridge_actions,
        *sensor_actions,
        rviz,
    ])
