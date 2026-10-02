"""수동 조작은 「수동」 모드에서만 · 2026-10-02 사용자 결정

스케줄 모드에서는 스케줄이 60초마다 「구간 안인데 멈춰 있다」며 재생을 다시
켠다 · 서버가 조그를 막는 것은 조그가 실제로 움직이는 0.15~0.5초뿐이라, 조그
사이 빈틈에 걸리면 사람이 만지던 축으로 초기 위치 이동이 시작됐다 · 그래서
규칙을 하나로 한다: 손으로 만질 땐 수동.

막는 것 · 조그 · 다이얼 · 동작(절대 이동)·범위 복귀 · 페이더(수동 스트림)
막지 않는 것 · 정지 · 긴급정지 · 서보 켜고 끄기 · 알람 해제
"""

import json
from pathlib import Path
from types import SimpleNamespace

from motion_web_bridge import run_mode_gate

BRIDGE_DIR = Path(__file__).resolve().parents[1] / 'motion_web_bridge'


def _bridge(tmp_path, mode, project_id='시험-0001'):
    project_dir = tmp_path / 'motion_projects' / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / 'schedule_store.json').write_text(
        json.dumps({'version': 2, 'mode': mode, 'schedules': []}, ensure_ascii=False),
        encoding='utf-8',
    )
    warns = []
    return SimpleNamespace(
        workspace_root=tmp_path,
        project_repository=SimpleNamespace(selected_project_id=lambda: project_id),
        get_logger=lambda: SimpleNamespace(warn=warns.append),
        _warns=warns,
    )


def test_manual_mode_opens_the_gate(tmp_path):
    assert run_mode_gate.manual_control_block_reason(_bridge(tmp_path, 'manual')) == ''


def test_schedule_mode_refuses_with_a_way_out(tmp_path):
    reason = run_mode_gate.manual_control_block_reason(_bridge(tmp_path, 'schedule'))
    assert '스케줄 모드' in reason
    assert '「수동」' in reason


def test_off_mode_still_refuses(tmp_path):
    reason = run_mode_gate.manual_control_block_reason(_bridge(tmp_path, 'off'))
    assert '오프 모드' in reason


def test_no_project_does_not_block(tmp_path):
    bridge = SimpleNamespace(
        workspace_root=tmp_path,
        project_repository=SimpleNamespace(selected_project_id=lambda: ''),
        get_logger=lambda: SimpleNamespace(warn=lambda *_: None),
    )
    assert run_mode_gate.manual_control_block_reason(bridge) == ''


def test_unreadable_mode_warns_and_lets_through(tmp_path):
    def broken():
        raise OSError('디스크 오류')
    warns = []
    bridge = SimpleNamespace(
        workspace_root=tmp_path,
        project_repository=SimpleNamespace(selected_project_id=broken),
        get_logger=lambda: SimpleNamespace(warn=warns.append),
    )
    assert run_mode_gate.manual_control_block_reason(bridge) == ''
    assert warns and '통과' in warns[0]


def test_playback_start_keeps_its_own_off_only_gate(tmp_path):
    """애니메이션 재생 시작은 사람 조작이 아니다 · 스케줄 모드에서도 된다."""
    assert run_mode_gate.motion_command_block_reason(_bridge(tmp_path, 'schedule')) == ''


def test_manual_entry_points_use_the_manual_gate_and_servo_does_not():
    manual = (BRIDGE_DIR / 'manual_motor_commands.py').read_text(encoding='utf-8')
    start = manual.index('def _off_mode_block')
    body = manual[start:start + 500]
    assert 'run_mode_gate.manual_control_block_reason(self.bridge)' in body
    for entry in ('def ac_servo_jog', 'def dynamixel_jog',
                  'def ac_servo_action', 'def dynamixel_action'):
        start = manual.index(entry)
        assert '_off_mode_block()' in manual[start:start + 400], entry
    servo = manual.index('def ac_servo_control')
    assert '_off_mode_block' not in manual[servo:servo + 400], '서보 제어는 막으면 안 된다'
    socket = (BRIDGE_DIR / 'manual_stream_socket.py').read_text(encoding='utf-8')
    assert socket.count('manual_control_block_reason') >= 3   # import + 시작 + 0.5초 재확인
