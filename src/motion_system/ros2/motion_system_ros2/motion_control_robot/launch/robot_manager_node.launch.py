import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    motion_control_robot_pkg_share = get_package_share_directory('motion_control_robot')
    motion_control_bridge_pkg_share = get_package_share_directory('motion_control_bridge')

    robot_config_file = os.path.join(
        motion_control_robot_pkg_share,
        'config',
        'rocking_chair.yaml',
    )
    motor_config_file = os.path.join(
        motion_control_bridge_pkg_share,
        'config',
        'example_ethercat_zeroerr.yaml',
    )

    robot_config_file_arg = DeclareLaunchArgument(
        'robot_config_file',
        default_value=robot_config_file,
        description='Absolute path to robot_manager YAML.',
    )
    motor_config_file_arg = DeclareLaunchArgument(
        'motor_config_file',
        default_value=motor_config_file,
        description='Absolute path to motor_manager YAML.',
    )
    hw_type_arg = DeclareLaunchArgument(
        'hw_type',
        default_value='DualSense',
        description='PlayStation controller hardware type used by p9n_node.',
    )

    return LaunchDescription([
        robot_config_file_arg,
        motor_config_file_arg,
        hw_type_arg,
        Node(
            package='joy',
            executable='joy_node',
            name='joy_node',
            output='screen',
        ),
        Node(
            package='p9n_node',
            executable='teleop_twist_joy_node_exec',
            name='teleop_twist_joy_node',
            output='screen',
            parameters=[{
                'hw_type': LaunchConfiguration('hw_type'),
            }],
        ),
        Node(
            package='motion_control_bridge',
            executable='motor_manager_node',
            name='motor_manager_node',
            output='screen',
            parameters=[{
                'config_file': LaunchConfiguration('motor_config_file'),
            }],
        ),
        Node(
            package='motion_control_robot',
            executable='robot_manager_node',
            name='robot_manager_node',
            output='screen',
            parameters=[{
                'config_file': LaunchConfiguration('robot_config_file'),
            }],
        ),
    ])
