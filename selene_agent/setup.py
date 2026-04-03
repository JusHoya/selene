from setuptools import setup

package_name = 'selene_agent'

setup(
    name=package_name,
    version='0.1.0',
    packages=['selene_agent', 'selene_agent.skills'],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='JusHoya',
    maintainer_email='jushoya@selene.dev',
    description='Per-robot autonomy stack for SELENE lunar ISRU fleet',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'agent_node = selene_agent.agent_node:main',
        ],
    },
)
