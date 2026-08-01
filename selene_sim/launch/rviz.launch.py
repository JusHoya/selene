"""RViz2 viewer for the FR-MAP-4 resource-map overlay, with the frame it needs.

WHY THIS FILE EXISTS — register open item 22(d).

RViz2 was started against ``selene_sim/rviz/selene_sim.rviz`` for the first time
on 2026-08-01 and could not establish a view. ``Global Status`` read
``Warn — Frame [map] does not exist``, and the only way anyone got a picture was
to run, by hand and outside the launch::

    ros2 run tf2_ros static_transform_publisher --frame-id map \
        --child-frame-id rviz_anchor

Nothing in SELENE publishes TF. ``/tf`` had **Publisher count: 0** and
``/tf_static`` had none either — measured again on 2026-08-01 at ``e276e60``,
with one subscriber, RViz2's own ``transform_listener_impl_*``. The overlay
messages still *render*, because tf2 has a same-frame identity shortcut and the
markers are stamped ``map``, the same string as the fixed frame. But the fixed
frame itself is not in the buffer, so RViz2 reports the view as unestablished and
an operator following the documented ``rviz:=true`` path gets a warning banner
and no confidence that what is drawn is where it claims to be.

That is the gap item 22(d) names: "the markers are published correctly", which
exit-gate check 10 proves, is not the same claim as "an operator can see them",
which nothing proved.

THE FIX, AND WHY IT IS SHAPED THIS WAY.

The anchor is published by ``tf2_ros/static_transform_publisher`` **from this
file**, which is included only behind ``rviz:=true``. Three alternatives were
considered and rejected:

* **The orchestrator broadcasts TF.** Rejected. The orchestrator runs on every
  path — headless, CI, and the exit gate — so this would make TF real everywhere
  in order to serve a viewer that is off by default, and it would put frame
  authority in the coordination layer.
* **A ``map -> odom`` identity transform.** Rejected as a measured falsehood.
  The odom frame is offset from world by a full SE(2) including a ~133° rotation
  (``scripts/check_drive.sh``; register D-33). Publishing identity there would
  assert something the repository has measured to be untrue.
* **``map -> map``.** Rejected by tf2 outright: a self-parented frame is an
  error, not a no-op.

So the honest statement about this repository changes from "nothing publishes
TF" to **"nothing publishes TF except this file, and only when a viewer is
started"**. Every headless run, every CI job and every exit-gate run still has
zero TF publishers. ``docs/phase5_deviation_register.md`` and ``CLAUDE.md`` say
so in those words.

``rviz_anchor`` is a leaf with no consumers, and that is deliberate: its whole
job is to put the string ``map`` into the tf buffer as a parent, which is what
``FrameManager`` tests when it decides whether the fixed frame exists. Naming it
after a robot or a sensor would imply a pose relationship that this file is not
entitled to assert.

USE IT STANDALONE, TOO::

    ros2 launch selene_sim rviz.launch.py     # attach a viewer to a running stack
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


#: The frame every SELENE producer stamps: ``resource_map_frame_id`` in
#: selene_orchestrator/config/orchestrator_params.yaml, ``Fixed Frame`` in
#: selene_sim/rviz/selene_sim.rviz, ``WORLD_FRAME_ID`` in
#: selene_sim/selene_sim/world_frame.py, and the frame the navigator stamps on
#: its nav_msgs/Path. Change one and you must change all of them; the exit gate's
#: check 10 asserts the first two against each other.
WORLD_FRAME = 'map'

#: A leaf frame with no consumers. See the module docstring.
ANCHOR_FRAME = 'rviz_anchor'


def generate_launch_description():
    rviz_config = os.path.join(
        get_package_share_directory('selene_sim'), 'rviz', 'selene_sim.rviz')

    return LaunchDescription([
        DeclareLaunchArgument(
            'rviz_config', default_value=rviz_config,
            description='RViz2 config to load. Defaults to the packaged '
                        'selene_sim/rviz/selene_sim.rviz.'),

        # THE ANCHOR. Identity, static, latched on /tf_static. Started BEFORE
        # the viewer so the frame is in the buffer by the time RViz2's
        # FrameManager first asks -- /tf_static is TRANSIENT_LOCAL so a late
        # subscriber gets it anyway, but a display that is green on the first
        # frame is easier to trust than one that goes green later.
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='selene_rviz_frame_anchor',
            arguments=[
                '--frame-id', WORLD_FRAME,
                '--child-frame-id', ANCHOR_FRAME,
            ],
            output='screen',
        ),

        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            arguments=['-d', LaunchConfiguration('rviz_config')],
            output='screen',
        ),
    ])
