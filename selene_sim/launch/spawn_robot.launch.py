"""Spawn a single SELENE robot into Gazebo and start its bridge + sensor nodes."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


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
            # Ground-truth model pose: Gazebo -> ROS 2. The PosePublisher block
            # in models/<type>/model.sdf puts the model's TRUE world pose on
            # /model/<name>/pose as a one-entry gz.msgs.Pose_V. Without this
            # entry world_odometry_node has no localisation source, falls back
            # to dead reckoning and says so once every minute.
            ['/model/', robot_id, '/pose@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V'],
        ],
        remappings=[
            (['/model/', robot_id, '/cmd_vel'], ['/', robot_id, '/cmd_vel']),
            (['/model/', robot_id, '/odometry'], ['/', robot_id, '/odom']),
            (['/', robot_id, '/imu'], ['/', robot_id, '/sensors/imu']),
            (['/', robot_id, '/depth_camera'], ['/', robot_id, '/sensors/depth']),
            (['/model/', robot_id, '/pose'], ['/', robot_id, '/pose_truth']),
        ],
        output='screen',
    )

    # THE FRAME CONVERSION (all robot types). Gazebo dead-reckons the bridged
    # /{robot_id}/odom from this robot's spawn pose, so its origin is wherever
    # the robot started and its x-axis points along the spawn heading. Every
    # consumer of position -- the battery node below, the agent's HAL, the
    # sensor sim nodes -- reads /{robot_id}/odom_world, which only this node
    # publishes. Without it they all sit on their is_valid=False defaults:
    # a robot that is up, healthy and never moves.
    #
    # The spawn pose is the SAME four LaunchConfigurations handed to
    # `ros_gz_sim create` above, so the transform cannot describe a placement
    # Gazebo did not perform. See
    # selene_sim/selene_sim/world_odometry_node.py.
    # ParameterValue(..., value_type=float) IS REQUIRED, not decoration. A bare
    # LaunchConfiguration in a parameter dict is resolved as a STRING, and
    # world_odometry_node declares these as doubles, so the node would abort at
    # start with ParameterTypeException for every robot. `ros2 launch` does not
    # coerce. (simulation.launch.py has no such problem: it is an
    # OpaqueFunction and passes real Python floats.)
    def _as_float(substitution):
        return ParameterValue(substitution, value_type=float)

    world_odom = Node(
        package='selene_sim',
        executable='world_odometry_node',
        name=['world_odom_', robot_id],
        parameters=[{
            'robot_id': robot_id,
            'spawn_x': _as_float(x),
            'spawn_y': _as_float(y),
            'spawn_z': _as_float(z),
            'spawn_yaw': _as_float(yaw),
        }],
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
        world_odom,
        battery,
    ])
