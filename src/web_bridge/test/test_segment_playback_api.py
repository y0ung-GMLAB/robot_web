"""구간 재생 · 브리지 · 받기 전에 검사 · 칸 이름 맞춤 · 스케줄은 통째로 · 그룹에 싣기 (2026-10-16)"""

from types import SimpleNamespace

import pytest

from motion_web_bridge import run_mode_gate
from motion_web_bridge.bridge_node import MotionWebBridge
from motion_web_bridge.coordination_bridge import (
    CoordinationWebBridge,
    local_motion_control,
    local_motion_readiness,
)
from test_coordination_bridge import _assets, _Bridge, _Node, _Repository


def _bridge(monkeypatch):
    monkeypatch.setattr(run_mode_gate, 'motion_command_block_reason', lambda _node: '')
    monkeypatch.setattr(run_mode_gate, 'human_start_block_reason', lambda _node, _payload: '')
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge.get_logger = lambda: SimpleNamespace(warn=lambda *_: None, info=lambda *_: None)
    bridge.coordination_execution_blocker = lambda: ''
    bridge.multiturn_clear_blocker = lambda: ''
    bridge.motor_runtime_control_blocker = lambda: ''
    bridge.schedule_end_start_blocker = lambda _payload: ''
    bridge.schedule_start_blocked_by_manual_mode = lambda _payload: ''
    bridge._with_active_project_files = lambda payload: dict(payload)
    sent = []
    bridge._request_motion_run = lambda command, payload, **_k: sent.append((command, payload)) or {'success': True}
    return bridge, sent


def test_start_flattens_the_screen_segment(monkeypatch):
    bridge, sent = _bridge(monkeypatch)
    result = bridge.motion_run_start({'motion_file_id': 'a.json', 'segment': {'start_sec': 80, 'end_sec': 105}})
    assert result['success'] is True
    [(command, payload)] = sent
    assert command == 'start'
    assert 'segment' not in payload
    assert (payload['segment_start_sec'], payload['segment_end_sec']) == (80.0, 105.0)


def test_initialize_goes_to_the_segment_start_pose(monkeypatch):
    bridge, sent = _bridge(monkeypatch)
    bridge.motion_run_initialize({'segment': {'start_sec': 30}})
    [(command, payload)] = sent
    assert command == 'initialize' and payload['segment_start_sec'] == 30.0


@pytest.mark.parametrize('segment, words', [
    ({'start_sec': 90, 'end_sec': 80}, '구간 끝 1:20 이 구간 시작 1:30 보다 뒤여야 합니다'),
    ({'start_sec': -2}, '0초 이상'),
    ({'start_sec': 'x'}, '숫자가 아닙니다'),
])
def test_a_wrong_segment_is_refused_before_the_runtime(monkeypatch, segment, words):
    bridge, sent = _bridge(monkeypatch)
    started = bridge.motion_run_start({'segment': segment})
    initialized = bridge.motion_run_initialize({'segment': segment})
    assert started['success'] is False and started['message'].startswith('모션 실행 불가: ')
    assert initialized['success'] is False and initialized['message'].startswith('초기 위치 이동 불가: ')
    assert words in started['message']
    assert sent == []


def test_schedule_and_automation_starts_are_always_whole(monkeypatch):
    bridge, sent = _bridge(monkeypatch)
    bridge.motion_run_start({'schedule_id': 's1', 'segment': {'start_sec': 80}})
    bridge.motion_run_start({'automation_run': True, 'segment_start_sec': 80})
    assert [(p['segment_start_sec'], p['segment_end_sec']) for _c, p in sent] == [(0.0, 0.0), (0.0, 0.0)]


def test_without_a_segment_the_request_is_whole(monkeypatch):
    bridge, sent = _bridge(monkeypatch)
    bridge.motion_run_start({'motion_file_id': 'a.json'})
    assert (sent[0][1]['segment_start_sec'], sent[0][1]['segment_end_sec']) == (0.0, 0.0)


# -- 그룹 ----------------------------------------------------------------------- #

def _group_service(tmp_path, monkeypatch):
    monkeypatch.setattr(run_mode_gate, 'current_run_mode', lambda _node: 'manual')
    node = _Node()
    service = CoordinationWebBridge(node, tmp_path, lambda: node.generation[0])
    calls = []
    service._local_api = lambda path, payload=None: calls.append((path, payload)) or {'success': True}
    return service, calls


def test_group_start_carries_the_segment_to_the_coordinator(tmp_path, monkeypatch):
    service, calls = _group_service(tmp_path, monkeypatch)
    result = service.request_control({'command': 'start_group', 'segment': {'start_sec': 80, 'end_sec': 105}})
    assert result['success'] is True
    [(path, request)] = calls
    assert path == '/control'
    assert (request['segment_start_sec'], request['segment_end_sec']) == (80.0, 105.0)

    service.request_control({'command': 'initialize_group', 'segment': {'start_sec': 12}})
    assert calls[-1][1]['segment_start_sec'] == 12.0


def test_group_start_refuses_a_wrong_segment_and_schedule_is_whole(tmp_path, monkeypatch):
    service, calls = _group_service(tmp_path, monkeypatch)
    refused = service.request_control({'command': 'start_group', 'segment': {'start_sec': 9, 'end_sec': 3}})
    assert refused['success'] is False and '보다 뒤여야' in refused['message']
    assert calls == []
    service.request_control({'command': 'start_group', 'schedule_id': 's1', 'segment': {'start_sec': 9}})
    assert calls[-1][1]['segment_start_sec'] == 0.0


def test_readiness_checks_item_one_with_the_segment(tmp_path):
    _assets(tmp_path)
    bridge = _Bridge(_Repository(tmp_path))
    local_motion_readiness(bridge, {'budget_sec': 6.0, 'segment_start_sec': 80.0, 'segment_end_sec': 0.0})
    assert (bridge.payload['segment_start_sec'], bridge.payload['segment_end_sec']) == (80.0, 0.0)
    assert bridge.payload['request_source'] == 'network_readiness'
    local_motion_readiness(bridge, {'budget_sec': 6.0})
    assert bridge.payload['segment_start_sec'] == 0.0


def test_group_prepare_and_join_carry_the_segment(tmp_path):
    _assets(tmp_path)
    bridge = _Bridge(_Repository(tmp_path))
    base = {'command': 'group_prepare', 'execution_id': 'exec-a',
            'initialize_monotonic': 100.0, 'network_operation_id': 'command-a'}
    local_motion_control(bridge, {**base, 'segment_start_sec': 80.0, 'segment_end_sec': 105.0})
    assert (bridge.payload['segment_start_sec'], bridge.payload['segment_end_sec']) == (80.0, 105.0)
    local_motion_control(bridge, base)
    assert (bridge.payload['segment_start_sec'], bridge.payload['segment_end_sec']) == (0.0, 0.0)
    local_motion_control(bridge, {**base, 'command': 'group_join', 'join_cycle_number': 3, 'segment_start_sec': 7.0})
    assert bridge.payload['segment_start_sec'] == 7.0
    # 깨진 값(옛 · 이상한 명령)은 통째로
    local_motion_control(bridge, {**base, 'segment_start_sec': 9.0, 'segment_end_sec': 3.0})
    assert bridge.payload['segment_start_sec'] == 0.0
