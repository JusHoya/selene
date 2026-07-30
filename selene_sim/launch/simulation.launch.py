"""SELENE simulation launch — starts Gazebo world with full robot fleet.

Usage:
    ros2 launch selene_sim simulation.launch.py
    ros2 launch selene_sim simulation.launch.py num_scouts:=3 num_excavators:=2
    ros2 launch selene_sim simulation.launch.py world:=/path/to/other.sdf

WHY THIS IS AN OpaqueFunction AND NOT A PLAIN LaunchDescription
The robot counts have to be READ to build the right number of spawn, bridge and
sensor nodes, and a LaunchConfiguration cannot be read at description time — it
is a substitution resolved later. The original version declared num_scouts /
num_excavators / num_haulers and then built the fleet from literal `range(2)`,
`range(1)`, `range(1)`, so the arguments existed and did nothing (FR-SIM-7(c),
deviation D-07).

That was worse than a no-op. unified_sim.launch.py honours the same arguments for
the ORCHESTRATOR and the AGENT nodes and passes them down here, so
`num_scouts:=3` really did start a third agent — one that registered with the
fleet, bid on tasks and won them, with no Gazebo model behind it. It looked like
a coordination bug rather than a launch bug.

OpaqueFunction defers the body until a context exists, so `.perform(context)`
returns the real values and the loops below build the fleet that was asked for.
"""

import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction,
    SetEnvironmentVariable, TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _positions_for(spawn_positions, group, wanted, config_path):
    """Return `wanted` spawn poses from `group`, or fail loudly.

    NO PROCEDURAL FALLBACK, on purpose. Every z in spawn_positions.yaml is a
    MEASURED collision surface plus a 0.30 m margin — see the header of that
    file and scripts/check_terrain.sh. Inventing a pose for a robot the config
    does not describe would put it at an unsurveyed XY, which is precisely how
    this project spent months with robots buried in the terrain, wheels turning,
    odometry advancing, world displacement exactly zero.

    So: ask for more robots than the config describes and the launch stops, with
    a message that says how to add them properly.
    """
    available = spawn_positions.get(group) or []
    if wanted > len(available):
        raise RuntimeError(
            f'{group}: {wanted} requested but {config_path} defines only '
            f'{len(available)} spawn pose(s).\n'
            f'  Add {wanted - len(available)} more entry/entries under '
            f'"{group}:" in that file.\n'
            f'  z is NOT free to guess: it must be the collision surface '
            f'measured at that exact XY plus 0.30 m. Add the coordinate to the '
            f'POINTS list in scripts/check_terrain.sh, run it, and read the '
            f'surface_z column. A guessed z spawns the robot inside the terrain, '
            f'where it will report healthy odometry and never move.'
        )
    return available[:wanted]


def _launch_setup(context, *args, **kwargs):
    pkg_share = get_package_share_directory('selene_sim')

    def arg(name):
        return LaunchConfiguration(name).perform(context)

    def count(name):
        raw = arg(name)
        try:
            value = int(raw)
        except ValueError:
            raise RuntimeError(f'{name} must be an integer, got {raw!r}')
        if value < 0:
            raise RuntimeError(f'{name} must be >= 0, got {value}')
        return value

    # Paths — all overridable (FR-SIM-7(d)). These were hardcoded, so the
    # "configurable world file and ice deposit layout" clause was unmet even
    # though nothing else in the file assumed a particular world.
    world_file = arg('world') or os.path.join(pkg_share, 'worlds', 'lunar_psr.sdf')
    ice_config = arg('ice_config') or os.path.join(
        pkg_share, 'config', 'ice_deposits.yaml')
    spawn_config_path = arg('spawn_config') or os.path.join(
        pkg_share, 'config', 'spawn_positions.yaml')
    models_path = os.path.join(pkg_share, 'models')
    world_params = os.path.join(pkg_share, 'config', 'world_params.yaml')
    rviz_config = os.path.join(pkg_share, 'rviz', 'selene_sim.rviz')

    for label, path in (('world', world_file), ('ice_config', ice_config),
                        ('spawn_config', spawn_config_path)):
        if not os.path.isfile(path):
            raise RuntimeError(f'{label} does not exist: {path}')

    sdf_for = {
        'scout': os.path.join(models_path, 'scout', 'model.sdf'),
        'excavator': os.path.join(models_path, 'excavator', 'model.sdf'),
        'hauler': os.path.join(models_path, 'hauler', 'model.sdf'),
    }

    with open(spawn_config_path, 'r') as f:
        spawn_positions = yaml.safe_load(f) or {}

    counts = {
        'scout': count('num_scouts'),
        'excavator': count('num_excavators'),
        'hauler': count('num_haulers'),
    }
    group_of = {'scout': 'scouts', 'excavator': 'excavators', 'hauler': 'haulers'}

    # (robot_type, robot_id, pose) for the whole fleet, in a fixed order, so the
    # spawn, bridge and sensor loops below cannot disagree about who exists.
    fleet = []
    for robot_type in ('scout', 'excavator', 'hauler'):
        poses = _positions_for(spawn_positions, group_of[robot_type],
                               counts[robot_type], spawn_config_path)
        for i, pose in enumerate(poses):
            fleet.append((robot_type, f'{robot_type}_{i + 1:02d}', pose))

    gz_resource_path = SetEnvironmentVariable('GZ_SIM_RESOURCE_PATH', models_path)

    gz_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('ros_gz_sim'),
                         'launch', 'gz_sim.launch.py')
        ),
        # -s = server-only (no GUI). Avoids OGRE shader crashes on WSL2 and
        # keeps the footprint small; the dashboard is the operator UI.
        launch_arguments={'gz_args': ['-s -r ', world_file]}.items(),
    )

    spawn_delay = 2.0   # seconds between spawns, to avoid collision
    spawn_actions = []
    for robot_type, robot_id, pose in fleet:
        spawn_actions.append(TimerAction(
            period=spawn_delay * (len(spawn_actions) + 1),
            actions=[
                Node(
                    package='ros_gz_sim',
                    executable='create',
                    arguments=['-name', robot_id, '-file', sdf_for[robot_type],
                               '-x', str(pose['x']), '-y', str(pose['y']),
                               '-z', str(pose['z']),
                               '-Y', str(pose.get('yaw', 0.0))],
                    output='screen',
                ),
            ],
        ))

    bridge_actions = []
    for robot_type, robot_id, _pose in fleet:
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

    sensor_actions = []
    for robot_type, robot_id, _pose in fleet:
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
        if robot_type == 'scout':
            sensor_actions.append(Node(
                package='selene_sim',
                executable='neutron_spectrometer_node',
                name=f'neutron_spec_{robot_id}',
                parameters=[{'robot_id': robot_id, 'ice_config_file': ice_config}],
                output='screen',
            ))
        elif robot_type == 'excavator':
            sensor_actions.append(Node(
                package='selene_sim',
                executable='hopper_node',
                name=f'hopper_{robot_id}',
                parameters=[{'robot_id': robot_id, 'ice_config_file': ice_config}],
                output='screen',
            ))
            sensor_actions.append(Node(
                package='selene_sim',
                executable='extraction_node',
                name=f'extraction_{robot_id}',
                parameters=[{'robot_id': robot_id, 'ice_config_file': ice_config}],
                output='screen',
            ))
        elif robot_type == 'hauler':
            sensor_actions.append(Node(
                package='selene_sim',
                executable='bin_load_node',
                name=f'bin_load_{robot_id}',
                parameters=[{'robot_id': robot_id}],
                output='screen',
            ))

    actions = [gz_resource_path, gz_sim,
               *spawn_actions, *bridge_actions, *sensor_actions]

    if LaunchConfiguration('rviz').perform(context).lower() in ('true', '1'):
        actions.append(Node(
            package='rviz2',
            executable='rviz2',
            arguments=['-d', rviz_config],
            output='screen',
        ))

    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'num_scouts', default_value='2',
            description='Number of scout robots. Must not exceed the entries '
                        'under "scouts:" in spawn_config.'),
        DeclareLaunchArgument(
            'num_excavators', default_value='1',
            description='Number of excavator robots.'),
        DeclareLaunchArgument(
            'num_haulers', default_value='1',
            description='Number of hauler robots.'),
        DeclareLaunchArgument(
            'rviz', default_value='false',
            description='Launch RViz2 with the FR-MAP-4 resource-map overlay.'),
        DeclareLaunchArgument(
            'world', default_value='',
            description='World SDF to load. Empty = '
                        'selene_sim/worlds/lunar_psr.sdf.'),
        DeclareLaunchArgument(
            'ice_config', default_value='',
            description='Ice deposit layout YAML. Empty = '
                        'selene_sim/config/ice_deposits.yaml.'),
        DeclareLaunchArgument(
            'spawn_config', default_value='',
            description='Robot spawn poses YAML. Empty = '
                        'selene_sim/config/spawn_positions.yaml.'),
        OpaqueFunction(function=_launch_setup),
    ])
