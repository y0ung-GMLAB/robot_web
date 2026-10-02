import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    record_motion = LaunchConfiguration('record_motion')
    record_file_name = LaunchConfiguration('record_file_name')

    motion_control_bridge_pkg_share = get_package_share_directory('motion_control_bridge')
    motor_config_file = os.path.join(
        motion_control_bridge_pkg_share,
        'config',
        'example_ethercat_zeroerr.yaml',
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'record_motion',
            default_value='false',
            description='Enable recording current motor_status positions when btn3 is activated.',
        ),
        DeclareLaunchArgument(
            'record_file_name',
            default_value='rocking_chair.csv',
            description='CSV file name for recorded motion data.',
        ),
        Node(
            package='motion_control_bridge',
            executable='motor_manager_node',
            name='motor_manager_node',
            output='screen',
            parameters=[{
                'config_file': motor_config_file,
            }],
        ),
        Node(
            package='xtouch_midi',
            executable='xtouch_node',
            name='xtouch_node',
            output='screen',
            parameters=[{
                'btn0_requires_fader_update': True,
                'btn3_requires_fader_update': True,
            }],
        ),
        Node(
            package='motion_control_midi',
            executable='motion_control_midi_node',
            name='motion_control_midi_node',
            output='screen',
            parameters=[{
                'record_motion': ParameterValue(record_motion, value_type=bool),
                'record_file_name': record_file_name,
            }],
        ),
    ])
