"""스케줄 모드에서는 스케줄이 보낸 시작만 · 사람이 누른 재생·초기 이동·그룹 시작은 거절 · 수정 목록 70

실물 2026-10-07 시험 19 · 스케줄 모드에서 조그·절대 이동은 막히는데 화면 「1회 재생」 은
초기 이동까지 갔다 · 스케줄과 사람의 재생이 섞이지 않게 한다 (사용자 결정 2026-10-07).
"""

import json
from types import SimpleNamespace

import pytest

from motion_web_bridge import run_mode_gate
from motion_web_bridge.bridge_node import MotionWebBridge


def _bridge(tmp_path, mode):
    project_id = 'p-0001'
    project_dir = tmp_path / 'motion_projects' / project_id
    project_dir.mkdir(parents=True)
    (project_dir / 'schedule_store.json').write_text(
        json.dumps({'version': 1, 'mode': mode, 'schedules': []}), encoding='utf-8',
    )
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge.workspace_root = tmp_path
    bridge.project_repository = SimpleNamespace(selected_project_id=lambda: project_id)
    bridge.get_logger = lambda: SimpleNamespace(warn=lambda *_: None, info=lambda *_: None)
    return bridge


@pytest.mark.parametrize('payload', [
    {},
    {'motion_file_id': 'a.json'},
    {'request_source': 'web'},
])
def test_human_start_is_refused_in_schedule_mode(tmp_path, payload):
    reason = run_mode_gate.human_start_block_reason(_bridge(tmp_path, 'schedule'), payload)
    assert reason == run_mode_gate.SCHEDULE_MANUAL_BLOCK_MESSAGE


@pytest.mark.parametrize('payload', [
    {'schedule_id': 's1'},
    {'request_source': 'network_control'},
    {'request_source': 'network_readiness'},
    {'request_source': 'schedule_end'},
])
def test_schedule_and_group_starts_pass_in_schedule_mode(tmp_path, payload):
    assert run_mode_gate.human_start_block_reason(_bridge(tmp_path, 'schedule'), payload) == ''


def test_human_start_passes_in_manual_mode(tmp_path):
    assert run_mode_gate.human_start_block_reason(_bridge(tmp_path, 'manual'), {}) == ''


def test_motion_run_start_and_initialize_refuse_before_anything_else(tmp_path):
    bridge = _bridge(tmp_path, 'schedule')
    bridge._request_motion_run = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('런타임에 가면 안 된다'))

    started = bridge.motion_run_start({'motion_file_id': 'a.json'})
    initialized = bridge.motion_run_initialize({})

    assert started['success'] is False and '스케줄 모드' in started['message']
    assert initialized['success'] is False and '스케줄 모드' in initialized['message']
