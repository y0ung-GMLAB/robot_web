"""「오류 초기화」 는 알람이 있는 축에만 · 수정 목록 112 가 (사용자 결정 2026-10-13)

2026-10-12 floating4 · 알람이 없는데 「오류 초기화」 를 누르자 3축 서보가 모두 꺼졌다
(Operation enabled → Ready to switch on) · 리셋은 드라이브를 서보 OFF 로 떨어뜨린다.
"""

import json
from types import SimpleNamespace

from motion_web_bridge.manual_motor_commands import ManualMotorCommandService


def _service(motors):
    sent = []
    bridge = SimpleNamespace(
        motion_state=lambda: {'motors': motors},
        snapshot=lambda: {},
        new_project_request_id=lambda prefix: f'{prefix}-1',
        current_project_generation=lambda: 1,
    )
    service = ManualMotorCommandService(
        bridge, repository=None,
        jog_publisher=SimpleNamespace(publish=lambda msg: sent.append(json.loads(msg.data))),
        action_publisher=None, jog_result_topic='r', action_result_topic='a',
    )
    service.wait_for_jog_result = lambda _rid, timeout_sec=2.0: {'success': True, 'message': 'ok'}
    return service, sent


def _ac(axis, fault=False):
    return {'controller_index': axis, 'motor_type': 'ac_servo', 'driver_family': 'minas',
            'transport': 'ethercat', 'state': 'detected', 'fault': fault}


def test_no_alarm_sends_nothing_and_keeps_the_servo():
    service, sent = _service([_ac(0), _ac(1)])
    result = service.ac_servo_control('fault_reset', None, 'all')
    assert result['success'] is True
    assert '서보는 그대로' in result['message']
    assert sent == []


def test_only_the_faulted_axis_is_reset_even_for_scope_all():
    service, sent = _service([_ac(0), _ac(1, fault=True), _ac(2)])
    service.ac_servo_control('fault_reset', None, 'all')
    assert sent[0]['axes'] == [1]
    assert sent[0]['scope'] == 'selected'      # 감독은 all 이면 축 목록을 안 본다


def test_single_axis_without_alarm_is_skipped():
    service, sent = _service([_ac(0)])
    result = service.ac_servo_control('fault_reset', 0, 'selected')
    assert result['success'] is True and sent == []


def test_servo_on_off_are_unchanged():
    service, sent = _service([_ac(0), _ac(1)])
    service.ac_servo_control('servo_off', None, 'all')
    assert sent[0]['scope'] == 'all' and sent[0]['action'] == 'servo_off'
