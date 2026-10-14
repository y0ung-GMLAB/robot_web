"""그룹 즉시 정지가 이 PC 가 돌지 않는 실행 것이면 단독 재생 · 조그를 세우지 않는다 · 수정 목록 136 ②

실물 V-4 · V-5 (2026-10-13/14 · floating4 마스터) · 그룹 시작이 취소되고 정리 중 다른 PC 의 늦은
거절로 전체 정지가 나가자 브리지가 실행 번호를 안 보고 무조건 세웠다 · 단독 연속 재생과 조그(97.5°
에서 멈춤)가 섰다 · 브리지 쪽 몫만 · rclpy 없이 돈다.
"""

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from motion_web_bridge.coordination_bridge import local_motion_control, stop_now_not_ours
from motion_web_bridge.execution_context_service import ExecutionContextService


def _bridge(run, safety=None):
    stopped = []
    bridge = SimpleNamespace(
        _motion_run_lock=threading.Lock(), _motion_run_status=dict(run),
        _safety_status_lock=threading.Lock(), _safety_status=dict(safety or {}),
        coordination_stop_now=lambda: stopped.append('stop') or {'success': True},
    )
    return bridge, stopped


@pytest.mark.parametrize('run, safety', [
    ({'state': 'running'}, {}),                                       # V-4 · 단독 연속 재생
    ({'state': 'idle'}, {'manual_activity_modes': ['jog']}),          # V-5 · 조그
    ({'state': 'idle'}, {'command_owner': 'stream'}),                 # 페이더
])
def test_a_group_stop_for_someone_elses_execution_leaves_this_pc_alone(run, safety):
    bridge, stopped = _bridge(run, safety)

    result = local_motion_control(bridge, {'command': 'stop_now', 'execution_id': 'exec-other'})

    assert stopped == []
    assert result['success'] is True and result['ignored'] is True
    assert 'exec-other' in result['message']


@pytest.mark.parametrize('run', [
    {'state': 'running', 'group_execution': True, 'execution_id': 'exec-a'},   # 그 실행을 도는 중
    {'state': 'running', 'group_execution': True, 'execution_id': 'exec-old'},  # 다른 그룹 세션 · 그래도 세운다
    {'state': 'idle'},                                                          # 쉬는 중 · 세워도 해 없음
    {},                                                                         # 못 읽음 · 세운다
])
def test_a_group_stop_still_stops_whatever_could_be_that_group(run):
    bridge, stopped = _bridge(run)

    local_motion_control(bridge, {'command': 'stop_now', 'execution_id': 'exec-a'})

    assert stopped == ['stop']


def test_a_stop_without_an_execution_id_stops_as_before():
    bridge, stopped = _bridge({'state': 'running'})

    local_motion_control(bridge, {'command': 'stop_now'})

    assert stopped == ['stop']
    assert stop_now_not_ours(bridge, '') == ''


def _context(state, message=''):
    service = ExecutionContextService(
        SimpleNamespace(), project=None, repository=None, workspace_root=Path('.'),
    )
    service._status.update({'state': state, 'message': message})
    return service


@pytest.mark.parametrize('state', ['configuration_required', 'no_project', 'error'])
def test_a_context_only_a_person_can_fix_is_a_start_blocker(state):
    """⑤ · floating1~3 (모터 설정 없음) · 선택 때 미리 뺀다"""
    assert _context(state, '모터 설정과 조인트 매핑을 저장해 확정하세요').terminal_block_reason() \
        == '모터 설정과 조인트 매핑을 저장해 확정하세요'


@pytest.mark.parametrize('state', ['starting', 'ready', 'applying', 'waiting_nodes', 'stale', 'selected'])
def test_a_context_that_preparation_can_fix_is_not_a_start_blocker(state):
    assert _context(state, '적용 중').terminal_block_reason() == ''
