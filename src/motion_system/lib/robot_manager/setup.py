from setuptools import find_packages, setup

package_name = 'robot_manager'

packages = (
    find_packages(where='robots/src') +
    find_packages(where='robot_manager/src')
)

setup(
    name=package_name,
    version='0.0.0',
    packages=packages,
    package_dir={
        'robots': 'robots/src/robots',
        'robot_manager': 'robot_manager/src/robot_manager',
    },
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='csi',
    maintainer_email='seonilchoi98@gmail.com',
    description='Robot management library for motion control.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
        ],
    },
)
