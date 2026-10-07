"""supervisor 가 재생 명령 **수신** 시각을 따로 적는다 · 수정 목록 14 · 29-3 (2026-10-06)"""

from pathlib import Path
from types import SimpleNamespace

from motion_supervisor.supervisor_node import MotionSupervisor

ROOT = Path(__file__).resolve().parents[3]


def test_rejected_commands_still_count_as_received():
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor._last_motion_run_received_at = 0.0
    supervisor._motor_command_shape_error = lambda _msg: 'malformed'
    supervisor.get_logger = lambda: SimpleNamespace(error=lambda *_a, **_k: None)

    supervisor._motion_run_command_callback(object())

    # 내보내지 않았어도 받기는 받았다 · 브리지는 이것으로 「수신 정지」 를 가린다
    assert supervisor._last_motion_run_received_at > 0.0


def test_safety_status_reports_the_reception_age_and_threads_can_be_dumped():
    text = (ROOT / 'src/motion_supervisor/motion_supervisor/supervisor_node.py').read_text(encoding='utf-8')
    assert "'motion_run_received_age_sec'" in text
    assert 'faulthandler.register(signal.SIGUSR1' in text


def test_launch_ends_when_supervisor_or_monitor_dies():
    text = (ROOT / 'src/motion_state_monitor/launch/motion_monitor.launch.py').read_text(encoding='utf-8')
    assert "_shutdown_when_it_exits(supervisor_node, 'motion_supervisor')" in text
    assert "_shutdown_when_it_exits(monitor_node, 'motion_state_monitor')" in text
    assert 'OnProcessExit' in text and 'Shutdown(' in text


def test_launch_leaves_a_crash_marker_unless_it_is_already_shutting_down():
    """수정 목록 72 · 다시 뜬 웹 브리지가 운영 로그에 남기게"""
    text = (ROOT / 'src/motion_state_monitor/launch/motion_monitor.launch.py').read_text(encoding='utf-8')
    assert 'upper_restart.write_marker(WORKSPACE, name,' in text
    assert "getattr(context, 'is_shutdown', False)" in text
