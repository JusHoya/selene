"""Dashboard + rosbridge launch.

Launches:
  - rosbridge_websocket on ws://localhost:9090 (always)
  - React dashboard via npm start on http://localhost:3000 (unless headless:=true)

Args:
  headless (default false) — skip the dashboard process

The dashboard is served via `npm start` rather than as an installed ament
package because selene_dashboard is COLCON_IGNORE'd. The launch resolves the
dashboard source path from $SELENE_PROJECT_ROOT, falling back to ~/selene.
"""

import os

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
)
from launch.conditions import UnlessCondition
from launch.launch_description_sources import XMLLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    headless = LaunchConfiguration('headless')

    rosbridge = IncludeLaunchDescription(
        XMLLaunchDescriptionSource([
            FindPackageShare('rosbridge_server'),
            '/launch/rosbridge_websocket_launch.xml',
        ]),
    )

    project_root = os.environ.get('SELENE_PROJECT_ROOT', os.path.expanduser('~/selene'))
    dashboard_path = os.path.join(project_root, 'selene_dashboard')

    dashboard = ExecuteProcess(
        cmd=['/usr/bin/npm', 'start'],
        cwd=dashboard_path,
        additional_env={'BROWSER': 'none', 'HOST': '0.0.0.0'},
        condition=UnlessCondition(headless),
        output='screen',
    )

    return LaunchDescription([
        DeclareLaunchArgument('headless', default_value='false'),
        rosbridge,
        dashboard,
    ])
