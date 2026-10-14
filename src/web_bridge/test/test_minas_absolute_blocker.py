"""브리지 · 초기 이동 · 재생 시작 · 그룹 준비 · 검사 · 화면 차단 사유 · 수정 목록 62 ②"""

import threading
import time

from motion_web_bridge.bridge_node import MotionWebBridge

BLOCKED = {'state': 'blocked', 'drives': [], 'message': '앱솔루트 미확인 · 슬레이브 3(미등록) 확인 불가'}


def _bridge(minas_absolute, *, online=True):
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._lock = threading.Lock()
    bridge._motion_state_received_at = time.time()
    bridge._motion_state = {
        'motors': [{
            'controller_index': 0,
            'connection_state': 'online' if online else 'offline',
            'connection_connected': online,
            'fault': False,
        }],
        'minas_absolute': minas_absolute,
    }
    return bridge


def test_runtime_blocker_names_the_absolute_reason_after_axis_checks():
    assert _bridge({'state': 'ok'}).motor_runtime_control_blocker() == ''
    assert _bridge({'state': 'none'}).motor_runtime_control_blocker() == ''
    assert _bridge(BLOCKED).motor_runtime_control_blocker() == BLOCKED['message']
    assert '확인 중' in _bridge({'state': 'checking'}).motor_runtime_control_blocker()
    # 축이 오프라인이면 그 사유가 먼저 · 더 구체적이다
    assert '연결되지 않은 모터' in _bridge(BLOCKED, online=False).motor_runtime_control_blocker()


def test_motion_run_check_refuses_before_asking_the_runtime():
    bridge = _bridge(BLOCKED)
    bridge._request_motion_run = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError('검사를 런타임에 보내면 안 된다')
    )

    result = bridge.motion_run_check({'motion_file_id': 'a.json'})

    assert result['success'] is False
    assert BLOCKED['message'] in result['message']


def test_motion_run_check_goes_on_when_absolute_is_confirmed():
    bridge = _bridge({'state': 'ok'})
    bridge._request_motion_run = lambda action, payload, timeout_sec: {'success': True, 'action': action}
    assert bridge.motion_run_check({})['action'] == 'check'


def test_motor_event_log_records_block_and_release_once(tmp_path):
    from motion_web_bridge.motor_event_log import MotorEventLog

    events = []
    log = MotorEventLog.__new__(MotorEventLog)
    log._lock = threading.RLock()
    log._last_minas_absolute_message = None
    log.append = lambda **event: events.append(event)

    log.record_minas_absolute_transition({'minas_absolute': {'state': 'checking'}})
    log.record_minas_absolute_transition({'minas_absolute': {'state': 'ok'}})
    assert events == []                                   # 처음부터 정상 · 적지 않음

    log.record_minas_absolute_transition({'minas_absolute': BLOCKED})
    log.record_minas_absolute_transition({'minas_absolute': BLOCKED})
    log.record_minas_absolute_transition({'minas_absolute': {'state': 'checking'}})
    assert [event['event_type'] for event in events] == ['minas_absolute_blocked']
    assert BLOCKED['message'] in events[0]['content']

    log.record_minas_absolute_transition({'minas_absolute': {'state': 'ok'}})
    assert [event['event_type'] for event in events] == ['minas_absolute_blocked', 'minas_absolute_confirmed']


def test_motor_event_log_records_stuck_mailbox_and_release_once_per_drive():
    """수정 목록 139 ③ · 감시 노드의 `minas_absolute.stuck_mailboxes` · 바뀔 때만 드라이브마다 1건"""
    from motion_web_bridge.motor_event_log import MotorEventLog

    events = []
    log = MotorEventLog.__new__(MotorEventLog)
    log._lock = threading.RLock()
    log._stuck_mailboxes = {}
    log.append = lambda **event: events.append(event)
    stuck = {
        'master_index': 0, 'slave_position': 2, 'axis': 2, 'since': 1.0,
        'message': '2번 드라이브 메일박스 응답 없음 · 그 드라이브 제어 전원을 껐다 켜세요',
    }

    log.record_mailbox_stuck_transition({'minas_absolute': {'state': 'ok', 'stuck_mailboxes': []}})
    log.record_mailbox_stuck_transition({'minas_absolute': {'state': 'ok'}})          # 옛 감시 노드 · 칸 없음
    assert events == []

    log.record_mailbox_stuck_transition({'minas_absolute': {'state': 'ok', 'stuck_mailboxes': [stuck]}})
    log.record_mailbox_stuck_transition({'minas_absolute': {'state': 'checking', 'stuck_mailboxes': [stuck]}})
    assert [event['event_type'] for event in events] == ['ethercat_mailbox_stuck']
    assert events[0]['category'] == 'error'
    assert events[0]['content'] == stuck['message'] and events[0]['target'] == '2번 드라이브'

    log.record_mailbox_stuck_transition({'minas_absolute': None})                     # 정보 없음 · 그대로
    log.record_mailbox_stuck_transition({'minas_absolute': {'state': 'ok', 'stuck_mailboxes': []}})
    assert [event['event_type'] for event in events] == ['ethercat_mailbox_stuck', 'ethercat_mailbox_recovered']
    assert events[1]['target'] == '2번 드라이브'


def test_bridge_moves_the_crash_marker_into_one_motor_event(tmp_path):
    """수정 목록 72"""
    from types import SimpleNamespace

    from motion_common import upper_restart

    upper_restart.write_marker(tmp_path, 'motion_supervisor', -9, now=1000.0)
    events = []
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge.workspace_root = tmp_path
    bridge.get_logger = lambda: SimpleNamespace(error=lambda *_: None)
    bridge._motor_event_log = SimpleNamespace(append=lambda **event: events.append(event))

    bridge._record_upper_service_crash()
    bridge._record_upper_service_crash()          # 표지는 한 번만

    assert [event['event_type'] for event in events] == ['upper_service_crashed']
    assert events[0]['target'] == 'motion_supervisor'
    assert '코드 -9' in events[0]['content']
