"""Restart project-owned services without touching motor driver processes."""

import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from motion_common import topics


WORKSPACE = Path(os.environ.get('MOTION_WORKSPACE', Path.cwd())).expanduser()


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'config_file',
            default_value=str(WORKSPACE / 'config' / 'bootstrap_motor_config.yaml'),
        ),
        DeclareLaunchArgument(
            'motion_projects_dir',
            default_value=str(WORKSPACE / 'motion_projects'),
        ),
        DeclareLaunchArgument('host', default_value='0.0.0.0'),
        DeclareLaunchArgument('port', default_value='8000'),
        DeclareLaunchArgument('motion_state_topic', default_value=topics.MOTION_STATE),
        DeclareLaunchArgument(
            'safety_request_topic',
            default_value=topics.SAFETY_REQUEST,
        ),
        DeclareLaunchArgument('publish_hz', default_value='10.0'),
        DeclareLaunchArgument('max_jog_delta_deg', default_value='360.0'),
        Node(
            package='motion_runtime',
            executable='motion_mapping_manager',
            name='motion_mapping_manager',
            output='screen',
            parameters=[{
                'motion_state_topic': LaunchConfiguration('motion_state_topic'),
                'motion_projects_dir': LaunchConfiguration('motion_projects_dir'),
            }],
        ),
        Node(
            package='motion_runtime',
            executable='motion_run_manager',
            name='motion_run_manager',
            output='screen',
            parameters=[{
                'motion_projects_dir': LaunchConfiguration('motion_projects_dir'),
            }],
        ),
        Node(
            package='motion_schedule',
            executable='motion_schedule_node',
            name='motion_schedule_node',
            output='screen',
        ),
        Node(
            package='motion_web_bridge',
            executable='motion_web_bridge',
            name='motion_web_bridge',
            output='screen',
            parameters=[{
                'motion_state_topic': LaunchConfiguration('motion_state_topic'),
                'safety_request_topic': LaunchConfiguration('safety_request_topic'),
                'max_jog_delta_deg': LaunchConfiguration('max_jog_delta_deg'),
                'host': LaunchConfiguration('host'),
                'port': LaunchConfiguration('port'),
                'web_publish_hz': LaunchConfiguration('publish_hz'),
                'motor_config_file': LaunchConfiguration('config_file'),
                'motion_projects_dir': LaunchConfiguration('motion_projects_dir'),
            }],
        ),
    ])
