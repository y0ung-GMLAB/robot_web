"""오프 모드 = 움직임 명령 전부 차단 · 서보는 홀드 유지.

게이트는 **저장 파일**(schedule_store.json)을 읽는다 · 조회 경유는 브리지가
잠깐 막히면 기본값(스케줄)으로 둔갑했던 전력이 있다 (§6-270).

막는 것 · 조그 / 절대 이동 / 애니메이션 재생·초기 위치 이동 / 그룹 시작.
막지 않는 것 · 정지·긴급정지 · 서보 켜고 끄기 · 조회 — 그 경로들에는
게이트를 달지 않는 것으로 보장한다 (아래 배선 검사).
"""

import json
from pathlib import Path
from types import SimpleNamespace

from motion_web_bridge import run_mode_gate

BRIDGE_DIR = Path(__file__).resolve().parents[1] / 'motion_web_bridge'


def _bridge(tmp_path, mode, project_id='시험-0001'):
    project_dir = tmp_path / 'motion_projects' / project_id
    project_dir.mkdir(parents=True)
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


def test_off_mode_blocks_with_a_reason(tmp_path):
    reason = run_mode_gate.motion_command_block_reason(_bridge(tmp_path, 'off'))
    assert '오프 모드' in reason
    assert '차단' in reason


def test_schedule_and_manual_modes_do_not_block(tmp_path):
    schedule = _bridge(tmp_path, 'schedule', project_id='스케줄-0001')
    manual = _bridge(tmp_path, 'manual', project_id='수동-0001')
    assert run_mode_gate.motion_command_block_reason(schedule) == ''
    assert run_mode_gate.motion_command_block_reason(manual) == ''


def test_no_project_does_not_block(tmp_path):
    bridge = _bridge(tmp_path, 'off')
    bridge.project_repository = SimpleNamespace(selected_project_id=lambda: '')
    assert run_mode_gate.motion_command_block_reason(bridge) == ''


def test_a_read_failure_lets_commands_through_with_a_warning(tmp_path):
    """게이트가 죽어서 전시가 서면 안 된다 · 못 읽으면 통과시키고 알린다."""
    bridge = _bridge(tmp_path, 'off')
    bridge.project_repository = SimpleNamespace(
        selected_project_id=lambda: '없는/프로젝트',   # ScheduleStore 가 ValueError
    )
    assert run_mode_gate.motion_command_block_reason(bridge) == ''


# --------------------------------------------------------------------------- #
# 배선 · 게이트가 정확히 움직임 명령에만 달려 있다
# --------------------------------------------------------------------------- #

def _source(name):
    return (BRIDGE_DIR / name).read_text(encoding='utf-8')


def test_every_motion_command_entry_point_is_gated():
    manual = _source('manual_motor_commands.py')
    for entry in ('def ac_servo_jog', 'def dynamixel_jog',
                  'def ac_servo_action', 'def dynamixel_action'):
        start = manual.index(entry)
        body = manual[start:start + 400]
        assert '_off_mode_block()' in body, f'{entry} 에 오프 게이트가 없다'

    bridge = _source('bridge_node.py')
    for entry in ('def motion_run_start', 'def motion_run_initialize'):
        start = bridge.index(entry)
        body = bridge[start:start + 400]
        assert 'run_mode_gate.motion_command_block_reason' in body, (
            f'{entry} 에 오프 게이트가 없다'
        )

    for entry in ('def motion_group_prepare',):
        start = bridge.index(entry)
        body = bridge[start:start + 500]
        assert 'run_mode_gate.motion_command_block_reason' in body, (
            f'{entry} 에 오프 게이트가 없다 · 원격 그룹 시작이 뚫린다'
        )

    coordination = _source('coordination_bridge.py')
    start = coordination.index("if command in {'start_group', 'initialize_group'}:")
    assert 'run_mode_gate.motion_command_block_reason' in coordination[start:start + 300], (
        '그룹 시작에 오프 게이트가 없다'
    )


def test_stop_and_servo_paths_are_not_gated():
    """정지·서보 제어는 오프에서도 되어야 한다 · 잠긴 문에 소화전까지 걸면 안 된다."""
    manual = _source('manual_motor_commands.py')
    for entry in ('def ac_servo_control',):
        if entry in manual:
            start = manual.index(entry)
            assert '_off_mode_block' not in manual[start:start + 400], (
                f'{entry} 는 막으면 안 된다'
            )
    safety = _source('routes/safety_routes.py')
    assert 'run_mode_gate' not in safety, '안전 정지 경로에 게이트가 있다'


def test_the_gate_reads_the_file_not_a_query():
    gate = _source('run_mode_gate.py')
    assert 'ScheduleStore(' in gate
    assert 'schedule/status' not in gate, '조회로 물어보면 §6-270 의 함정에 빠진다'
