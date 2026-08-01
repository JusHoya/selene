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
    DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction,
    RegisterEventHandler, SetEnvironmentVariable, TimerAction,
)
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

#: The action name ros_gz_sim's gz_sim.launch.py gives the simulator process
#: (/opt/ros/jazzy/share/ros_gz_sim/launch/gz_sim.launch.py:140,
#: ExecuteProcess(..., name='gazebo')). It is what makes the launch prefix read
#: `[gazebo-1]`, which is how the three archived ODE aborts identify themselves:
#:     [ERROR] [gazebo-1]: process has died ... exit code 134
_GZ_ACTION_NAME = 'gazebo'


def _diagnose_simulator_exit(event, context):
    """Say why everything is about to stop, when it is the simulator that died.

    WHAT THIS IS FOR. On 2026-07-30/31 Gazebo hit an ODE assertion in collide()
    and exited 134 three times mid-mission. `ros2 launch` SURVIVED every time:
    the orchestrator kept auctioning, every agent kept publishing RobotState at
    2 Hz and kept its heartbeat, and the fleet quietly stopped being connected
    to a physics engine. The register's phrase for it is "the fleet then
    degrades silently". The root cause of the abort is STILL UNKNOWN -- the
    instrumented run of 2026-07-31 did not reproduce it -- so this does not fix
    it. It makes it loud, which is a different and achievable thing.

    Two mechanisms, and they are complementary rather than redundant:

    * `on_exit_shutdown: 'true'` on the gz_sim include (below) is upstream's own
      switch and is what actually brings the launch down. It is a plain
      ExecuteProcess on_exit=Shutdown(), so it fires for ANY simulator exit,
      including a clean one.
    * this handler, which prints the diagnosis. Shutdown alone produces a wall
      of "process has died" lines with no statement of which death mattered.

    It fires on every process exit and filters by name, because the simulator is
    started through an IncludeLaunchDescription and there is no action object
    here to target.
    """
    name = getattr(event, 'process_name', '') or ''
    if _GZ_ACTION_NAME not in name:
        return None
    code = getattr(event, 'returncode', None)
    return [LogInfo(msg=(
        '================================================================\n'
        f'THE SIMULATOR EXITED (process {name}, return code {code}). Shutting '
        'the whole launch down.\n'
        'Nothing the fleet does after this point is meaningful: the '
        'orchestrator will keep auctioning, every agent will keep its '
        'heartbeat, and no pose will ever change again. That combination -- a '
        'healthy-looking fleet attached to a dead world -- is what three '
        'mid-mission ODE aborts produced on 2026-07-30/31, and it is why this '
        'shuts down instead of continuing.\n'
        'Return code 134 is SIGABRT and is the known signature:\n'
        '  ODE INTERNAL ERROR 1: assertion "aabbBound >= dMinIntExact && '
        'aabbBound < dMaxIntExact" failed in collide()\n'
        'Its cause is UNKNOWN. It did not reproduce under instrumentation on '
        '2026-07-31. Keep the log.\n'
        '================================================================'))]


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
        #
        # on_exit_shutdown IS THE ANSWER TO "what should the system do when the
        # simulator dies". Upstream defaults it to 'false', which is why
        # `ros2 launch` outlived all three ODE aborts and left a fleet talking
        # to a dead world. It maps to ExecuteProcess(on_exit=Shutdown()) at
        # ros_gz_sim/launch/gz_sim.launch.py:135-146. See
        # _diagnose_simulator_exit above for the half of this that explains
        # itself in the log.
        launch_arguments={
            'gz_args': ['-s -r ', world_file],
            'on_exit_shutdown': 'true',
        }.items(),
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
                # THE SECOND, INDEPENDENT POSITION ESTIMATE. /model/<name>/pose
                # is the PosePublisher block in models/<type>/model.sdf; with
                # <publish_model_pose> and <use_pose_vector_msg> it carries one
                # gz.msgs.Pose_V entry holding the model's TRUE world pose, and
                # the bridge renders that as a TFMessage whose child_frame_id is
                # the model name. MEASURED on gz-sim 8 / ROS 2 Jazzy on
                # 2026-07-31: a model spawned at (10, 20, 0.5) yaw 0.7 arrived
                # on the ROS side as translation (10, 20, 0.5) with
                # frame_id=<world>, child_frame_id=<model> -- i.e. the world
                # pose, not a spawn-relative one.
                #
                # This is the simulator standing in for a localisation stack.
                # It is NOT wired into the autonomy layer: only
                # world_odometry_node reads it, and selene_agent /
                # selene_orchestrator / selene_hal cannot ask the simulator
                # where a robot really is.
                f'/model/{robot_id}/pose@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V',
            ],
            remappings=[
                (f'/model/{robot_id}/cmd_vel', f'/{robot_id}/cmd_vel'),
                (f'/model/{robot_id}/odometry', f'/{robot_id}/odom'),
                (f'/model/{robot_id}/pose', f'/{robot_id}/pose_truth'),
            ],
            output='screen',
        ))

    # The container-fill sim nodes size themselves from the SAME RCDL file the
    # agent's HAL is built from (selene_agent/launch/agent.launch.py:23-27 uses
    # this identical construction). That is what makes "one source of truth for
    # capacity_kg" true rather than aspirational: the sim publishes a fraction
    # of that capacity and the HAL multiplies by that capacity, so the two
    # cannot disagree about how many kilograms a full hopper holds.
    #
    # Resolved per robot TYPE, not per robot: excavator.yaml / hauler.yaml.
    # FindPackageShare('selene_hal') is why selene_sim now carries an
    # <exec_depend> on selene_hal (package.xml) -- the node source still
    # imports nothing from it.
    def rcdl_for(robot_type):
        return PathJoinSubstitution([
            FindPackageShare('selene_hal'), 'config', f'{robot_type}.yaml',
        ])

    # THE ONE CONVERSION POINT FOR ROBOT POSITION.
    #
    # Gazebo's DiffDrive dead-reckons /{robot_id}/odom from the robot's SPAWN
    # POSE -- odom (0,0) is wherever that robot started, and the odom x-axis
    # points along its spawn heading. Every consumer in SELENE used to read that
    # as world coordinates, which put the resource map, the PSR shadow test and
    # navigation in a different frame per robot and drove robots off the finite
    # 500 m heightfield until ODE's broadphase aborted the simulator.
    #
    # world_odometry_node applies spawn (+) odom once and republishes
    # /{robot_id}/odom_world. The RCDLs (selene_hal/config/*.yaml) point the
    # agent's odometry sensor at that topic, and the four selene_sim consumer
    # nodes below subscribe to it too.
    #
    # THE POSE COMES FROM `pose` -- the same dict handed to `ros_gz_sim create`
    # above, in the same loop, from the same read of spawn_config. Not a second
    # parse of spawn_positions.yaml: a second parse would have to re-implement
    # the "first N of each group" selection and could disagree with the spawner
    # about which N. See selene_sim/selene_sim/world_odometry_node.py.
    #
    # IT IS ALSO THE ONLY PLACE THE POSE IS CHECKED. `pose_source` selects
    # which of the two estimates is published (see that node's docstring); the
    # comparison between them runs either way and raises a FleetAlert on drift
    # or on wheels-turning-body-still. The latter is not a hypothetical: on
    # 2026-07-31 a hauler reported 126.7 m of wheel travel over 320.7 s while
    # its body moved 6.6 cm, then unloaded 19 kg 241.577 m from the depot with
    # nothing in the system objecting.
    pose_source = arg('pose_source')
    frame_actions = []
    for robot_type, robot_id, pose in fleet:
        frame_actions.append(Node(
            package='selene_sim',
            executable='world_odometry_node',
            name=f'world_odom_{robot_id}',
            parameters=[{
                'robot_id': robot_id,
                'spawn_x': float(pose['x']),
                'spawn_y': float(pose['y']),
                'spawn_z': float(pose['z']),
                'spawn_yaw': float(pose.get('yaw', 0.0)),
                'pose_source': pose_source,
            }],
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
                parameters=[{
                    'robot_id': robot_id,
                    'ice_config_file': ice_config,
                    'rcdl_path': rcdl_for(robot_type),
                }],
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
                parameters=[{
                    'robot_id': robot_id,
                    'rcdl_path': rcdl_for(robot_type),
                }],
                output='screen',
            ))

    actions = [gz_resource_path,
               RegisterEventHandler(OnProcessExit(
                   on_exit=_diagnose_simulator_exit)),
               gz_sim, *spawn_actions, *bridge_actions,
               *frame_actions, *sensor_actions]

    # RViz2 comes from rviz.launch.py, which starts the viewer TOGETHER WITH the
    # static map->rviz_anchor transform it needs. A bare rviz2 Node was what
    # shipped until 2026-08-01, and it produced `Global Status: Warn - Frame
    # [map] does not exist` because nothing in SELENE publishes TF; the view had
    # to be established with a hand-run static_transform_publisher. That is
    # register open item 22(d) and the reason this include exists.
    if LaunchConfiguration('rviz').perform(context).lower() in ('true', '1'):
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                FindPackageShare('selene_sim'), '/launch/rviz.launch.py',
            ]),
            launch_arguments={'rviz_config': rviz_config}.items(),
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
        DeclareLaunchArgument(
            'pose_source', default_value='localisation',
            description='Which estimate /<robot>/odom_world carries. '
                        '"localisation" = the simulator\'s true world pose, '
                        'standing in for a localisation stack. '
                        '"dead_reckoning" = spawn SE(2) on wheel odometry, the '
                        'pre-2026-07-31 behaviour, whose error is unbounded. '
                        'The divergence between the two is measured and '
                        'alerted on either way.'),
        OpaqueFunction(function=_launch_setup),
    ])
