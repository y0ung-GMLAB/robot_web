"""「초기 위치 이동」 뒤 서 있는 동안에도 재생 목록 등록 · 수정 목록 90 (실물 2026-10-08 · 확인 대기 84)

`initialized` = 초기 위치에 서 있음 · 아무것도 안 돈다 · 재생은 시작할 때 늘 지금 자리에서 새 첫 프레임까지
다시 천천히 간다 · 그래서 막지 않는다 · 그룹 초기 위치 이동 뒤(그룹 시작 대기)는 그대로 막는다.
"""

import threading
from pathlib import Path
from types import SimpleNamespace

from motion_web_bridge.project_service import ProjectService

PLAYER = Path(__file__).resolve().parents[2] / 'motion_runtime' / 'motion_runtime' / 'motion_player.py'


def _service(status):
    bridge = SimpleNamespace(_motion_run_lock=threading.Lock(), _motion_run_status=status)
    service = ProjectService.__new__(ProjectService)
    service.bridge = bridge
    service.repository = None
    return service


def test_standing_after_an_initial_move_does_not_block_registration():
    assert _service({'state': 'initialized'}).change_blocker() == ''


def test_a_group_waiting_to_start_and_moving_states_still_block():
    assert 'initialized' in _service({'state': 'initialized', 'group_execution': True}).change_blocker()
    for state in ('initializing', 'running', 'verifying'):
        assert state in _service({'state': state}).change_blocker()


def test_play_always_moves_from_where_it_stands_to_the_new_first_frame():
    """막지 않아도 되는 근거 · 재생 시작은 초기 이동부터(첫 프레임까지 잇기) · 건너뛰지 않는다"""
    source = PLAYER.read_text(encoding='utf-8')
    body = source[source.index('def _run_initialization_then_motion'):]
    body = body[:body.index('\n    def ', 10)]
    assert "self._run_initialization({**initialization_plan, 'blend_to_first_frame': True})" in body
