import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    IncludeLaunchDescription,
    RegisterEventHandler,
)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from motion_common import topics, upper_restart


WORKSPACE = Path(os.environ.get('MOTION_WORKSPACE', Path.cwd())).expanduser()
DEFAULT_CONFIG = str(WORKSPACE / 'config/bootstrap_motor_config.yaml')


def _shutdown_when_it_exits(node, name):
    """이 노드가 죽으면 launch 를 끝낸다 · 수정 목록 29-3 (2026-10-06)

    전에는 노드 하나가 죽어도 launch 와 서비스는 「active」 로 남아 systemd 의
    `Restart=always` 가 발동하지 않았다 · supervisor 가 죽으면 모터는 홀드(안전)지만
    아무도 다시 띄우지 않았다 · launch 를 끝내면 서비스가 통째로 다시 뜬다.
    """
    def on_exit(event, context):
        # 다시 뜬 웹 브리지가 운영 로그에 1건 남기게 표지를 쓴다 · 수정 목록 72 ·
        # launch 가 이미 끝나는 중(서비스 정지 · 프로그램 재시작)이면 쓰지 않는다 ·
        # 늦게 끝난 노드가 강제 종료(-9)돼도 비정상으로 적지 않게
        if not getattr(context, 'is_shutdown', False):
            upper_restart.write_marker(WORKSPACE, name, getattr(event, 'returncode', None))
        return [EmitEvent(event=Shutdown(reason=f'{name} 종료 · 서비스 재시작'))]

    return RegisterEventHandler(OnProcessExit(target_action=node, on_exit=on_exit))


def generate_launch_description():
    monitor_node = Node(
        package='motion_state_monitor',
        executable='motion_state_monitor',
        name='motion_state_monitor',
        output='screen',
        parameters=[{
            'input_topic': LaunchConfiguration('motor_status_topic'),
            'input_type': 'motor_status',
            'ethercat_status_topic': LaunchConfiguration('ethercat_status_topic'),
            'motor_config_file': LaunchConfiguration('config_file'),
            'project_generation': LaunchConfiguration('project_generation'),
            'output_topic': LaunchConfiguration('motion_state_topic'),
            'publish_hz': LaunchConfiguration('publish_hz'),
            'max_motors': LaunchConfiguration('max_motors'),
            'dynamixel_scan_id_fallback': True,
        }],
    )
    supervisor_node = Node(
        package='motion_supervisor',
        executable='motion_supervisor',
        name='motion_supervisor',
        output='screen',
        condition=IfCondition(LaunchConfiguration('start_motion_supervisor')),
        parameters=[{
            'motion_state_topic': LaunchConfiguration('motion_state_topic'),
            'jog_request_topic': topics.MANUAL_JOG_REQUEST,
            'jog_result_topic': topics.MANUAL_JOG_RESULT,
            'safety_request_topic': LaunchConfiguration('safety_request_topic'),
            'action_request_topic': topics.MANUAL_ACTION_REQUEST,
            'action_result_topic': topics.MANUAL_ACTION_RESULT,
            'motion_run_command_topic': topics.MOTION_RUN_COMMAND,
            'motor_command_topic': topics.MOTOR_COMMAND,
            'manual_stream_request_topic': topics.MANUAL_STREAM_REQUEST,
            'manual_stream_result_topic': topics.MANUAL_STREAM_RESULT,
            'max_jog_delta_deg': LaunchConfiguration('max_jog_delta_deg'),
            'config_file': LaunchConfiguration('config_file'),
        }],
    )
    return LaunchDescription([
        DeclareLaunchArgument(
            'config_file',
            default_value=DEFAULT_CONFIG,
            description='Absolute path to active motor YAML.',
        ),
        DeclareLaunchArgument('motion_state_topic', default_value=topics.MOTION_STATE),
        DeclareLaunchArgument(
            'project_generation',
            default_value=os.environ.get('PROJECT_GENERATION', '0'),
            description='Persisted generation of the selected project runtime.',
        ),
        DeclareLaunchArgument('motor_status_topic', default_value=topics.MOTOR_STATUS),
        DeclareLaunchArgument(
            'safety_request_topic',
            default_value=topics.SAFETY_REQUEST,
        ),
        DeclareLaunchArgument('ethercat_status_topic', default_value='/ethercat_status'),
        DeclareLaunchArgument('publish_hz', default_value='10.0'),
        DeclareLaunchArgument('max_motors', default_value='50'),
        DeclareLaunchArgument(
            'max_jog_delta_deg',
            default_value='360.0',
            description='Maximum single jog move in degrees.',
        ),
        DeclareLaunchArgument(
            'start_motor_manager',
            default_value='false',
            description='Start motor_manager_node. false keeps servo drivers untouched.',
        ),
        DeclareLaunchArgument(
            'start_motion_supervisor',
            default_value='true',
            description='Start motion_supervisor for upper-level command publishing.',
        ),
        DeclareLaunchArgument('host', default_value='0.0.0.0'),
        DeclareLaunchArgument('port', default_value='8000'),
        Node(
            package='motion_control_bridge',
            executable='motor_manager_node',
            name='motor_manager_node',
            output='screen',
            condition=IfCondition(LaunchConfiguration('start_motor_manager')),
            parameters=[{
                'config_file': LaunchConfiguration('config_file'),
            }],
        ),
        monitor_node,
        supervisor_node,
        _shutdown_when_it_exits(monitor_node, 'motion_state_monitor'),
        _shutdown_when_it_exits(supervisor_node, 'motion_supervisor'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                str(Path(__file__).with_name('project_services.launch.py'))
            ),
            launch_arguments={
                'config_file': LaunchConfiguration('config_file'),
                'motion_state_topic': LaunchConfiguration('motion_state_topic'),
                'safety_request_topic': LaunchConfiguration('safety_request_topic'),
                'publish_hz': LaunchConfiguration('publish_hz'),
                'max_jog_delta_deg': LaunchConfiguration('max_jog_delta_deg'),
                'host': LaunchConfiguration('host'),
                'port': LaunchConfiguration('port'),
            }.items(),
        ),
    ])
