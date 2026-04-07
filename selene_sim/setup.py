from glob import glob
from setuptools import setup

package_name = 'selene_sim'

setup(
    name=package_name,
    version='0.1.0',
    packages=['selene_sim'],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/worlds', glob('worlds/*.sdf')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/rviz', glob('rviz/*.rviz')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='JusHoya',
    maintainer_email='jushoya@selene.dev',
    description='Simulation environment for SELENE lunar ISRU fleet',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'battery_node = selene_sim.battery_node:main',
            'neutron_spectrometer_node = selene_sim.neutron_spectrometer_node:main',
            'hopper_node = selene_sim.hopper_node:main',
            'bin_load_node = selene_sim.bin_load_node:main',
            'extraction_node = selene_sim.extraction_node:main',
        ],
    },
)
