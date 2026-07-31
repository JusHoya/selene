"""Orchestrator launch wrapper.

Args:
  fleet_robot_ids (string list, e.g. "['scout_01','scout_02','excavator_01','hauler_01']")

THE NODE IS DELIBERATELY UNNAMED HERE, AND THAT IS THE FIX FOR DEVIATION D-12.

This action used to carry ``name='orchestrator'``. ROS 2 matches a parameter
file against the node's RUNTIME name, and ``orchestrator_params.yaml``'s
top-level key is ``orchestrator_node`` — the name the node gives itself at
``selene_orchestrator/orchestrator_node.py:873``. So the file below was loaded
and then matched nothing: every parameter in it fell back to its
``declare_parameter`` default, with no warning, no error and no log line.
``scripts/start.sh`` passes the same file to ``ros2 run`` with no name remap and
therefore got ``orchestrator_node`` and the file *did* apply — two entry points,
two node names, one file that could only ever match one of them. It stayed
latent only because every value in the file equalled its declared default.

Dropping ``name=`` lets launch_ros leave the node's own name alone, so the
runtime name is ``orchestrator_node`` on every path: ``ros2 run``, this launch
file, and ``unified_sim.launch.py`` which includes it. The alternative — keeping
the override and renaming the YAML key to ``orchestrator`` — would have fixed
the launch path and broken ``start.sh`` in exactly the same silent way.

The node therefore appears in ``ros2 node list`` as ``/orchestrator_node``,
which is what ``scripts/validate_phase5.sh``'s ``EXPECTED_NODES`` asserts.
``scripts/phase5_probe.py``'s ``find_node`` accepts either spelling and needs no
change. Topic and service names are unaffected: every one of them is declared
absolute (``/orchestrator/task_assignment`` and friends), so they do not follow
the node name.

``selene_orchestrator/test/test_params_files_are_applied.py`` pins this: it
parses this file and the YAML and fails if the key and the runtime name ever
disagree again.
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
        # No name= — see the module docstring. The node keeps the name it gives
        # itself, which is the key orchestrator_params.yaml is written under.
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
