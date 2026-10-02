from glob import glob
from setuptools import find_packages, setup

package_name = 'motion_control_robot'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/motions', glob('motions/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='csi',
    maintainer_email='seonilchoi98@gmail.com',
    description='ROS 2 package that connects robot_manager to motion control topics.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'robot_manager_node = motion_control_robot.robot_manager_node:main',
        ],
    },
)
