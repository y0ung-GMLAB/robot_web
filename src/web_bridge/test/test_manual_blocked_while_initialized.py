"""초기 위치에서 대기 중이거나 재생 중이면 손으로 움직이는 명령은 「정지」 뒤에만 · 사용자 2026-10-12

재생이 축을 쥐고 서 있는데 조그·페이더로 움직이면 재생 계획과 실제 자세가 어긋난다 ·
문구는 화면(새 UI manual.js)과 같다 · 재생 시작 문(`human_start_block_reason`)은
막지 않는다 · 초기 위치에서 대기 중일 때 「1회 시작」 은 되어야 한다.
"""

import json
import threading
from types import SimpleNamespace

import pytest

from motion_web_bridge import run_mode_gate


def _bridge(tmp_path, run_state, mode='manual'):
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
        _motion_run_status={'state': run_state} if run_state is not None else None,
    )


def test_initialized_asks_to_stop_first(tmp_path):
    reason = run_mode_gate.manual_motion_block_reason(_bridge(tmp_path, 'initialized'))
    assert reason == '초기 위치에서 대기 중입니다. 「정지」를 누른 뒤 수동 조작을 하세요.'


@pytest.mark.parametrize('state', ['running', 'initializing', 'waiting', 'countdown'])
def test_playing_asks_to_stop_first(tmp_path, state):
    assert '재생 중입니다' in run_mode_gate.manual_motion_block_reason(_bridge(tmp_path, state))


@pytest.mark.parametrize('state', ['idle', 'stopped', 'completed', 'error', '', None])
def test_stopped_or_unknown_lets_the_hand_move(tmp_path, state):
    assert run_mode_gate.manual_motion_block_reason(_bridge(tmp_path, state)) == ''


def test_mode_gate_still_comes_first(tmp_path):
    reason = run_mode_gate.manual_motion_block_reason(_bridge(tmp_path, 'initialized', mode='schedule'))
    assert '스케줄 모드' in reason


def test_starting_playback_from_the_initial_pose_is_not_blocked(tmp_path):
    assert run_mode_gate.human_start_block_reason(_bridge(tmp_path, 'initialized'), {}) == ''
