from setuptools import setup

package_name = 'selene_hal'

setup(
    name=package_name,
    version='0.1.0',
    packages=['selene_hal'],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', [
            'config/scout.yaml',
            'config/excavator.yaml',
            'config/hauler.yaml',
        ]),
    ],
    install_requires=['setuptools', 'pyyaml', 'pydantic>=2.0', 'numpy'],
    zip_safe=True,
    maintainer='JusHoya',
    maintainer_email='jushoya@selene.dev',
    description='Hardware Abstraction Layer for SELENE lunar ISRU robots',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={},
)
