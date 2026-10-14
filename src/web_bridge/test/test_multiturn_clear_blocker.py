"""다회전 클리어 뒤 기준점 보호 · 웹 브리지 · 검사 · 초기 이동 · 재생 · 하트비트 · 스케줄 · 상태 · 수정 목록 140 ③

표시는 PC 단위(작업 폴더 `runtime/multiturn_clear.json`) · 프로젝트를 바꾸거나 zip 으로 되돌려도 그대로 막는다 ·
수동 조그(`motor_action_blocker`)는 막지 않는다(몸을 정면·수평에 맞추려면 움직여야 한다).
"""

import threading
import time
from types import SimpleNamespace

import pytest

from motion_common import multiturn_clear
from motion_web_bridge import bridge_node
from motion_web_bridge.bridge_node import MotionWebBridge

REASON = '1번 모터 다회전 클리어 뒤 기준점 다시 지정 필요'


class Log:
    def __init__(self):
        self.entries = []

    def append(self, **entry):
        self.entries.append(entry)


def _bridge(tmp_path, rows=None):
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge.workspace_root = tmp_path
    bridge._lock = threading.Lock()
    bridge._motion_state_received_at = time.time()
    bridge._motion_state = {
        'motors': [{'controller_index': 1, 'connection_state': 'online', 'connection_connected': True, 'fault': False}],
        'minas_absolute': {'state': 'ok'},
    }
    bridge._motor_event_log = Log()
    bridge.test_rows = list(rows or [])
    bridge._active_mapping_rows = lambda: bridge.test_rows       # 지금 적용된 프로젝트의 매핑 줄
    bridge._request_motion_run = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('런타임에 보내면 안 된다'))
    return bridge


def _clear(bridge, axis=1):
    bridge._record_multiturn_clear([{'axis': axis, 'serial': 99, 'slave_position': axis, 'source': 'absolute_setup'}])


def test_no_marker_blocks_nothing(tmp_path):
    bridge = _bridge(tmp_path)
    assert bridge.multiturn_clear_blocker() == ''
    assert bridge.multiturn_clear_status()['blocked_axes'] == []


def test_a_clear_blocks_check_initialize_start_and_heartbeat_but_not_jog(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path, rows=[{'motion_id': '1-1', 'motor_axis': 1}])
    _clear(bridge)
    assert multiturn_clear.marker_path(tmp_path).is_file()
    assert bridge._motor_event_log.entries[-1]['event_type'] == 'minas_multiturn_clear_marked'
    assert bridge.multiturn_clear_blocker() == REASON

    check = bridge.motion_run_check({})
    assert check['success'] is False and REASON in check['message']

    for name in ('motion_command_block_reason', 'human_start_block_reason'):
        monkeypatch.setattr(bridge_node.run_mode_gate, name, lambda *_args, **_kwargs: '')
    bridge.schedule_end_start_blocker = lambda _payload: ''
    initialize = bridge.motion_run_initialize({'request_source': 'network_control'})
    assert initialize['success'] is False and initialize['message'] == f'초기 위치 이동 불가: {REASON}'
    bridge.schedule_start_blocked_by_manual_mode = lambda _payload: ''
    start = bridge.motion_run_start({'request_source': 'network_control'})
    assert start['success'] is False and start['message'] == f'모션 실행 불가: {REASON}'

    # 그룹 하트비트 · 마스터가 선택 때 미리 뺀다
    bridge._execution_context = SimpleNamespace(terminal_block_reason=lambda: '')
    assert bridge._cached_start_blocker() == f'실행 준비 안 됨 · {REASON}'

    # 수동 조그는 그대로(모터를 움직이는 기능 판단에 넣지 않는다)
    assert bridge.motor_runtime_control_blocker() == ''

    status = bridge.multiturn_clear_status()
    assert status['pending_axes'] == [1] and status['blocked_axes'] == [1]
    assert status['prompt'] == '다회전 클리어한 1번 모터 · 몸을 정면·수평에 맞추고 기준점을 다시 지정해 저장하세요'
    assert status['not_aligned_label'] == '클리어 뒤 아직 안 맞춤'


def test_saving_a_new_reference_releases_this_project_but_older_projects_stay_blocked(tmp_path):
    """다른 프로젝트를 고르거나 zip 으로 옛 매핑을 되돌려도 · 그 매핑의 기준점이 클리어 전 것이면 막힘"""
    bridge = _bridge(tmp_path, rows=[{'motion_id': '1-1', 'motor_axis': 1}])
    _clear(bridge)
    cleared_at = multiturn_clear.load(multiturn_clear.marker_path(tmp_path))['axes']['1']['cleared_at']

    saved = [{'motion_id': '1-1', 'motor_axis': 1, 'reference_set_at': cleared_at + 5}]
    assert bridge._release_multiturn_clear({'mapping': {'mappings': saved}}) == [1]
    assert bridge._motor_event_log.entries[-1]['event_type'] == 'minas_multiturn_clear_reference_set'
    bridge.test_rows = saved                                        # 이 프로젝트 · 저장한 줄
    assert bridge.multiturn_clear_blocker() == ''

    bridge.test_rows = [{'motion_id': '1-1', 'motor_axis': 1, 'reference_set_at': cleared_at - 100}]   # 다른 프로젝트
    assert bridge.multiturn_clear_blocker() == REASON
    bridge.test_rows = [{'motion_id': '1-1', 'motor_axis': 1}]       # zip 복원 · 칸 없는 옛 파일
    assert bridge.multiturn_clear_blocker() == REASON
    assert bridge.multiturn_clear_status()['stale_axes'] == [1]
    assert bridge.multiturn_clear_status()['pending_axes'] == []


def test_the_marker_survives_a_bridge_restart(tmp_path):
    first = _bridge(tmp_path)
    _clear(first)
    second = _bridge(tmp_path)                                       # 웹 브리지를 다시 켬 · 같은 작업 폴더
    assert second.multiturn_clear_blocker() == REASON


def test_schedule_start_blocker_includes_the_clear(tmp_path):
    from motion_web_bridge.schedule_service import ScheduleService

    bridge = _bridge(tmp_path)
    _clear(bridge)
    service = ScheduleService.__new__(ScheduleService)
    service.bridge = SimpleNamespace(
        motor_action_blocker=lambda: '', multiturn_clear_blocker=bridge.multiturn_clear_blocker,
    )
    assert service._start_blocker() == REASON
    service.bridge = SimpleNamespace(motor_action_blocker=lambda: '긴급정지', multiturn_clear_blocker=lambda: REASON)
    assert service._start_blocker() == '긴급정지'                    # 앞 사유가 먼저


@pytest.mark.parametrize('rows', [[], [{'motion_id': '2-1', 'motor_axis': 2}]])
def test_pending_blocks_regardless_of_the_active_mapping(tmp_path, rows):
    """「어느 프로젝트든 그 축 기준점을 다시 지정하기 전까지」 · 그 축이 없는 프로젝트도"""
    bridge = _bridge(tmp_path, rows=rows)
    _clear(bridge)
    assert bridge.multiturn_clear_blocker() == REASON
