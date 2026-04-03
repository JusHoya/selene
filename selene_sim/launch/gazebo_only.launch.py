"""Launch Gazebo Harmonic with the SELENE lunar world only (no robots)."""

import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory('selene_sim')
    world_file = os.path.join(pkg_share, 'worlds', 'lunar_psr.sdf')
    models_path = os.path.join(pkg_share, 'models')

    gz_resource_path = SetEnvironmentVariable(
        'GZ_SIM_RESOURCE_PATH', models_path)

    gz_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('ros_gz_sim'),
                'launch', 'gz_sim.launch.py'
            )
        ),
        launch_arguments={'gz_args': ['-r ', world_file]}.items(),
    )

    return LaunchDescription([gz_resource_path, gz_sim])
