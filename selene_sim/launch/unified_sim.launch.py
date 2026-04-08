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

Note: Sprint 0's simulation.launch.py currently hardcodes a 2/1/1 fleet at the
Gazebo spawn level. The args here flow through to all downstream stages
(orchestrator, agents) and will fully drive the fleet once the spawn loop in
simulation.launch.py is parameterized in Phase 6.
"""

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    OpaqueFunction,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
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
        launch_arguments={'headless': 'true' if headless else 'false'}.items(),
    ))

    # 12s delay lets Gazebo finish robot spawning before agents start polling /odom
    return [sim_launch, TimerAction(period=12.0, actions=delayed)]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('num_scouts', default_value='2'),
        DeclareLaunchArgument('num_excavators', default_value='1'),
        DeclareLaunchArgument('num_haulers', default_value='1'),
        DeclareLaunchArgument('headless', default_value='false'),
        OpaqueFunction(function=_launch_setup),
    ])
