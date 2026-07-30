"""SELENE unified simulation launch (Phase 5).

Single command brings up the entire system:
  Gazebo + lunar_psr world + 4-robot fleet + sensor sim nodes
  + orchestrator + per-robot agents + rosbridge + dashboard

Usage:
  ros2 launch selene_sim unified_sim.launch.py
  ros2 launch selene_sim unified_sim.launch.py num_scouts:=3 num_excavators:=2
  ros2 launch selene_sim unified_sim.launch.py headless:=true

Args:
  num_scouts     (default 2)
  num_excavators (default 1)
  num_haulers    (default 1)
  headless       (default false) — skip the React dashboard (rosbridge still up)
  prebuilt       (default false) — serve the prebuilt dashboard bundle instead of
                 the react-scripts dev server (see dashboard.launch.py; requires
                 `cd selene_dashboard && npm run build` beforehand)

FLEET SIZE
----------
The num_* arguments drive the fleet end to end: fleet_robot_ids is generated
from them and handed to the orchestrator and to one agent launch per robot, and
simulation.launch.py builds that exact number of Gazebo spawns, bridges and
sensor nodes from them.

That was not always true. Until 2026-07-30 simulation.launch.py declared the
same three arguments and then spawned from literal range(2)/range(1)/range(1),
so `num_scouts:=3` started a third AGENT — registering with the fleet, bidding
on tasks and winning them — with no Gazebo model behind it. It presented as a
coordination bug rather than a launch bug (FR-SIM-7(c), deviation D-07).

The fleet is bounded by spawn_positions.yaml, not by the arguments: every z
there is a MEASURED collision surface plus a 0.30 m margin, so asking for more
robots than the file describes now fails the launch with a message explaining
how to survey another pose. It does not invent one — a guessed z spawns a robot
inside the terrain, where it reports healthy odometry and never moves.

DASHBOARD CAVEAT
----------------
The dashboard must discover the fleet dynamically for any count other than the
2/1/1 default. A dashboard with a hardcoded robot list will not render the extra
robots, yet those robots still bid on and get assigned tasks — so they appear as
invisible assignees in the task table while never showing in the fleet view.
Until the dashboard's discovery path is confirmed, treat non-default counts as a
headless / CLI configuration.
"""

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    OpaqueFunction,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def _build_fleet_robot_ids(num_scouts, num_excavators, num_haulers):
    """Generate fleet_robot_ids list deterministically."""
    ids = []
    for i in range(int(num_scouts)):
        ids.append(f"scout_{i + 1:02d}")
    for i in range(int(num_excavators)):
        ids.append(f"excavator_{i + 1:02d}")
    for i in range(int(num_haulers)):
        ids.append(f"hauler_{i + 1:02d}")
    return ids


def _launch_setup(context, *args, **kwargs):
    num_scouts = int(LaunchConfiguration('num_scouts').perform(context))
    num_excavators = int(LaunchConfiguration('num_excavators').perform(context))
    num_haulers = int(LaunchConfiguration('num_haulers').perform(context))
    headless = LaunchConfiguration('headless').perform(context).lower() in ('true', '1')
    prebuilt = LaunchConfiguration('prebuilt').perform(context).lower() in ('true', '1')
    rviz = LaunchConfiguration('rviz').perform(context).lower() in ('true', '1')

    fleet_ids = _build_fleet_robot_ids(num_scouts, num_excavators, num_haulers)
    fleet_ids_str = "[" + ",".join(f"'{rid}'" for rid in fleet_ids) + "]"

    # 1. Gazebo + spawn + bridges + sim sensors via existing simulation.launch.py
    sim_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            FindPackageShare('selene_sim'),
            '/launch/simulation.launch.py',
        ]),
        launch_arguments={
            'num_scouts': str(num_scouts),
            'num_excavators': str(num_excavators),
            'num_haulers': str(num_haulers),
            # FR-SIM-7(d). Passed straight through; empty means the packaged
            # default. Without these the counts were configurable here and the
            # world was not, which is half a requirement.
            'world': LaunchConfiguration('world').perform(context),
            'ice_config': LaunchConfiguration('ice_config').perform(context),
            'spawn_config': LaunchConfiguration('spawn_config').perform(context),
        }.items(),
    )

    # 2. Delayed: orchestrator + agents + dashboard (after Gazebo spawn settles)
    delayed = []

    # Orchestrator
    delayed.append(IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            FindPackageShare('selene_orchestrator'),
            '/launch/orchestrator.launch.py',
        ]),
        launch_arguments={'fleet_robot_ids': fleet_ids_str}.items(),
    ))

    # Per-robot agents
    rcdl_map = {
        'scout': 'scout.yaml',
        'excavator': 'excavator.yaml',
        'hauler': 'hauler.yaml',
    }
    for robot_id in fleet_ids:
        robot_type = robot_id.rsplit('_', 1)[0]
        delayed.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                FindPackageShare('selene_agent'),
                '/launch/agent.launch.py',
            ]),
            launch_arguments={
                'robot_id': robot_id,
                'robot_type': robot_type,
                'rcdl': rcdl_map[robot_type],
                'orchestrated': 'true',
            }.items(),
        ))

    # Dashboard + rosbridge (rosbridge always; dashboard gated by headless)
    delayed.append(IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            FindPackageShare('selene_sim'),
            '/launch/dashboard.launch.py',
        ]),
        launch_arguments={
            'headless': 'true' if headless else 'false',
            'prebuilt': 'true' if prebuilt else 'false',
        }.items(),
    ))

    # RViz2 resource-map overlay (FR-MAP-4), off by default.
    #
    # Gated rather than always-on because this launch file is what
    # scripts/validate_phase5.sh drives, and that runs headless in WSL2 and CI
    # where starting a GUI would be pointless at best. `rviz:=true` is the
    # documented way to see the overlay:
    #     ros2 launch selene_sim unified_sim.launch.py rviz:=true
    #
    # It starts with the delayed group so the orchestrator's
    # /orchestrator/resource_map_markers publisher exists before RViz subscribes
    # — RViz copes either way, but a display that goes green immediately is
    # easier to trust than one that fills in later.
    if rviz:
        delayed.append(Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            arguments=['-d', PathJoinSubstitution([
                FindPackageShare('selene_sim'), 'rviz', 'selene_sim.rviz',
            ])],
            output='screen',
        ))

    # 12s delay lets Gazebo finish robot spawning before agents start polling /odom
    return [sim_launch, TimerAction(period=12.0, actions=delayed)]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('num_scouts', default_value='2'),
        DeclareLaunchArgument('num_excavators', default_value='1'),
        DeclareLaunchArgument('num_haulers', default_value='1'),
        DeclareLaunchArgument('headless', default_value='false'),
        DeclareLaunchArgument(
            'world', default_value='',
            description='World SDF to load. Empty = the packaged lunar_psr.sdf.'),
        DeclareLaunchArgument(
            'ice_config', default_value='',
            description='Ice deposit layout YAML. Empty = the packaged default.'),
        DeclareLaunchArgument(
            'spawn_config', default_value='',
            description='Robot spawn poses YAML. Empty = the packaged default.'),
        DeclareLaunchArgument(
            'rviz', default_value='false',
            description='Start RViz2 with the FR-MAP-4 resource-map overlay '
                        '(selene_sim/rviz/selene_sim.rviz).'),
        DeclareLaunchArgument(
            'prebuilt', default_value='false',
            description='Serve the prebuilt dashboard bundle (fast) instead of '
                        'the react-scripts dev server. Requires `npm run build`.'),
        OpaqueFunction(function=_launch_setup),
    ])
