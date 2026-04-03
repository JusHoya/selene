from setuptools import setup

package_name = 'selene_isru'

setup(
    name=package_name,
    version='0.1.0',
    packages=['selene_isru'],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='JusHoya',
    maintainer_email='jushoya@selene.dev',
    description='ISRU process models for SELENE lunar resource utilization',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={},
)
