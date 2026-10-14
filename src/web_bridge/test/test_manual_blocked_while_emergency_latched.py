"""긴급 정지 잠김 중 수동 조작 거절은 잠김을 이유로 · 실물 R-23 (2026-10-13)

잠김 중 조그가 「초기 위치에서 대기 중…」 · 「서보 꺼짐」 으로 거절됐다 · 사람은 정지를 누르거나
서보를 켜려다 또 막힌다 · 진짜 이유와 할 일(프로그램 다시 시작)을 말한다.
"""

import json
import threading
from pathlib import Path
from types import SimpleNamespace

from motion_web_bridge import run_mode_gate


def _bridge(tmp_path, *, latched, run_state='initialized', mode='manual'):
    project_dir = tmp_path / 'motion_projects' / 'p'
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / 'schedule_store.json').write_text(
        json.dumps({'version': 2, 'mode': mode, 'schedules': []}), encoding='utf-8',
    )
    return SimpleNamespace(
        workspace_root=tmp_path,
        project_repository=SimpleNamespace(selected_project_id=lambda: 'p'),
        get_logger=lambda: SimpleNamespace(warn=lambda *_: None),
        _motion_run_lock=threading.Lock(),
        _motion_run_status={'state': run_state},
        _safety_status_lock=threading.Lock(),
        _safety_status={'emergency_latched': latched, 'commands_blocked': latched},
    )


def test_latch_is_the_reason_not_the_initial_pose(tmp_path):
    reason = run_mode_gate.manual_motion_block_reason(_bridge(tmp_path, latched=True))
    assert reason == run_mode_gate.EMERGENCY_MANUAL_BLOCK_MESSAGE
    assert '긴급정지 잠김' in reason and '프로그램 다시 시작' in reason
    assert '초기 위치' not in reason


def test_latch_comes_before_the_mode_gate(tmp_path):
    reason = run_mode_gate.manual_motion_block_reason(_bridge(tmp_path, latched=True, mode='schedule'))
    assert reason == run_mode_gate.EMERGENCY_MANUAL_BLOCK_MESSAGE


def test_without_latch_the_old_reasons_stay(tmp_path):
    reason = run_mode_gate.manual_motion_block_reason(_bridge(tmp_path, latched=False))
    assert reason == run_mode_gate.INITIALIZED_MANUAL_BLOCK_MESSAGE
    assert run_mode_gate.manual_motion_block_reason(_bridge(tmp_path, latched=False, run_state='idle')) == ''


def test_missing_safety_status_does_not_block(tmp_path):
    bridge = _bridge(tmp_path, latched=False, run_state='idle')
    bridge._safety_status = None
    assert run_mode_gate.manual_motion_block_reason(bridge) == ''


def test_the_gate_runs_before_the_servo_check():
    """서버 선검사 순서 · 잠김·운전 모드 문이 서보 꺼짐 검사(readiness)보다 먼저"""
    source = (Path(run_mode_gate.__file__).parent / 'manual_motor_commands.py').read_text(encoding='utf-8')
    for name, following in (('ac_servo_jog', 'dynamixel_jog'), ('ac_servo_action', 'dynamixel_action')):
        body = source.split(f'def {name}', 1)[1].split(f'def {following}', 1)[0]
        assert body.index('_off_mode_block') < body.index('_readiness_error')
