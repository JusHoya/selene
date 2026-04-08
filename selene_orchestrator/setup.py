from glob import glob
from setuptools import setup

package_name = 'selene_orchestrator'

setup(
    name=package_name,
    version='0.1.0',
    packages=['selene_orchestrator'],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/orchestrator_params.yaml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='JusHoya',
    maintainer_email='jushoya@selene.dev',
    description='Fleet orchestration engine for SELENE lunar ISRU operations',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'orchestrator_node = selene_orchestrator.orchestrator_node:main',
        ],
    },
)
