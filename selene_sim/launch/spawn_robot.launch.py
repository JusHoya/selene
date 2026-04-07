"""Spawn a single SELENE robot into Gazebo and start its bridge + sensor nodes."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    robot_id = LaunchConfiguration('robot_id')
    robot_type = LaunchConfiguration('robot_type')
    model_file = LaunchConfiguration('model_file')
    x = LaunchConfiguration('x', default='0.0')
    y = LaunchConfiguration('y', default='0.0')
    z = LaunchConfiguration('z', default='0.5')
    yaw = LaunchConfiguration('yaw', default='0.0')
    world_params = LaunchConfiguration('world_params', default='')

    # Spawn robot into Gazebo
    spawn = Node(
        package='ros_gz_sim',
        executable='create',
        arguments=[
            '-name', robot_id,
            '-file', model_file,
            '-x', x, '-y', y, '-z', z,
            '-Y', yaw,
        ],
        output='screen',
    )

    # Bridge: Gazebo transport <-> ROS 2
    # Maps cmd_vel (ROS2->GZ), odom (GZ->ROS2), IMU (GZ->ROS2), depth (GZ->ROS2)
    bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name=['bridge_', robot_id],
        arguments=[
            # cmd_vel: ROS 2 -> Gazebo
            ['/model/', robot_id, '/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist'],
            # odometry: Gazebo -> ROS 2
            ['/model/', robot_id, '/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry'],
            # IMU: Gazebo -> ROS 2
            ['/', robot_id, '/imu@sensor_msgs/msg/Imu[gz.msgs.IMU'],
            # Depth camera: Gazebo -> ROS 2
            ['/', robot_id, '/depth_camera@sensor_msgs/msg/Image[gz.msgs.Image'],
        ],
        remappings=[
            (['/model/', robot_id, '/cmd_vel'], ['/', robot_id, '/cmd_vel']),
            (['/model/', robot_id, '/odometry'], ['/', robot_id, '/odom']),
            (['/', robot_id, '/imu'], ['/', robot_id, '/sensors/imu']),
            (['/', robot_id, '/depth_camera'], ['/', robot_id, '/sensors/depth']),
        ],
        output='screen',
    )

    # Battery simulation node (all robot types)
    battery = Node(
        package='selene_sim',
        executable='battery_node',
        name=['battery_', robot_id],
        parameters=[{
            'robot_id': robot_id,
            'robot_type': robot_type,
            'world_params_file': world_params,
            'update_rate': 10.0,
        }],
        output='screen',
    )

    return LaunchDescription([
        DeclareLaunchArgument('robot_id', description='Unique robot ID'),
        DeclareLaunchArgument('robot_type', description='Robot type: scout/excavator/hauler'),
        DeclareLaunchArgument('model_file', description='Path to robot model SDF file'),
        DeclareLaunchArgument('x', default_value='0.0'),
        DeclareLaunchArgument('y', default_value='0.0'),
        DeclareLaunchArgument('z', default_value='0.5'),
        DeclareLaunchArgument('yaw', default_value='0.0'),
        DeclareLaunchArgument('ice_config', default_value=''),
        DeclareLaunchArgument('world_params', default_value=''),
        spawn,
        bridge,
        battery,
    ])
