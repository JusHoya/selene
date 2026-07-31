"""Per-robot agent launch wrapper.

Args:
  robot_id     (e.g. 'scout_01')
  robot_type   ('scout' | 'excavator' | 'hauler')
  rcdl         ('scout.yaml' | 'excavator.yaml' | 'hauler.yaml')
  orchestrated (default true)

THE THREE BID WEIGHTS LIVE HERE NOW — DEVIATION D-13. So does
``recharge_threshold``, for the identical reason — DEVIATION D-19.

They used to sit in ``selene_orchestrator/config/orchestrator_params.yaml``,
which only the orchestrator loads, and the orchestrator declares none of them.
ROS 2 drops an undeclared override silently, so editing a weight in that file
changed no bid anywhere in the fleet. Bidding is scored on the AGENT
(``selene_agent/agent_node.py:629-641``) from parameters the AGENT declares
(``:114-116``), and this launch file passed an inline parameter dict that did
not mention them — so every agent always used its own hardcoded defaults. Those
defaults happened to be the same three numbers, which is why the disconnect
produced no symptom in four phases.

Putting them in the dict below is the smallest change that makes them live:
this dict is what every agent actually receives, on the only path that starts a
fleet (``unified_sim.launch.py`` includes this file once per robot). Editing a
number here now changes bidding.

WHY NOT A YAML PARAMS FILE. That is the more idiomatic home and it is a
deliberate deferral, not an oversight: a new ``selene_agent/config/*.yaml``
reached through ``FindPackageShare`` must also be listed in
``selene_agent/setup.py``'s ``data_files``, or the file is simply not installed
and ``Node(parameters=[<missing path>])`` aborts the launch for every agent —
turning a silent config defect into a fleet that will not start. The two changes
have to land together, and ``setup.py`` was outside the scope of the change that
closed D-13.

``selene_orchestrator/test/test_params_files_are_applied.py`` fails the build if
any key in a params file is not declared by the node that loads it, so the
weights cannot drift back into the orchestrator's file.
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
            # FR-ORC-2 bid weights (D-13). Declared at agent_node.py:114-116
            # and read at :629-641, where the score is
            #   w_dist*dist_score + w_energy*energy_score + w_cap*cap_score.
            # They are floats and must stay floats: the node declares them as
            # doubles, and a string or an int override raises
            # ParameterTypeException at node start rather than being coerced.
            # These three values are identical to the node's own defaults, so
            # this change is behaviour-preserving by construction; the point is
            # that the numbers are now in the dict the agent is handed, so
            # changing one has an effect.
            'bid_weight_distance': 0.4,
            'bid_weight_energy': 0.35,
            'bid_weight_capability': 0.25,
            # THE RECHARGE FLOOR LIVES HERE NOW TOO — DEVIATION D-19, and it
            # is the same defect as the bid weights above with a different
            # name. `recharge_threshold` was declared by the ORCHESTRATOR
            # (orchestrator_node.py) and set in
            # selene_orchestrator/config/orchestrator_params.yaml, and read by
            # nothing anywhere: it was one of the two entries on
            # selene_orchestrator/test/test_no_orphan_parameters.py's
            # allow-list. The recharge decision is made by the AGENT, in
            # agent_node._recharge_reason(), from a parameter the AGENT now
            # declares. Both the orchestrator declaration and the yaml key are
            # deleted; the allow-list is down to one entry.
            #
            # 0.30 is the value orchestrator_params.yaml carried, preserved so
            # the move changes no number, only which node reads it. A float,
            # for the reason given above the bid weights: the node declares it
            # as a double and an int raises ParameterTypeException at start.
            #
            # It must stay strictly between energy_critical_threshold (0.15)
            # and energy_recharge_target (0.90); agent_node validates that at
            # construction and says so in the log when it does not hold.
            'recharge_threshold': 0.30,
        }],
    )

    return LaunchDescription([
        DeclareLaunchArgument('robot_id'),
        DeclareLaunchArgument('robot_type'),
        DeclareLaunchArgument('rcdl'),
        DeclareLaunchArgument('orchestrated', default_value='true'),
        agent,
    ])
